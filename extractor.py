"""
Call of Duty Scoreboard Extractor
Supports Gemini AI Vision (primary, high-accuracy) and Local OCR fallback.
Extracts player stats (Kills, Deaths, Assists, Damage, Score, Objective) from screenshots.
"""
import asyncio
import io
import json
import logging
import os
import random
import re
import warnings
from typing import Any, Dict, List, Optional

from PIL import Image, ImageEnhance
from pydantic import BaseModel, Field

from safety import clamp_int, clean_untrusted_text, normalize_api_key, redact_secrets

logger = logging.getLogger("cod_extractor")

# The SDK warns that a Pydantic response_schema is sent via function calling.
# The response is still parsed as the schema, so the warning is noise.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# gemini-3.5-flash is deprecated and aliased to gemini-3.6-flash.
DEFAULT_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_EDGE = 1920
MAX_PLAYERS = 16
_MODEL_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")


class ImageRejected(ValueError):
    """The upload is not a screenshot we should decode."""


class PlayerRow(BaseModel):
    name: str = Field(description="Player gamertag or username (clan tags like [XYZ] can be included or stripped)")
    team: str = Field(description="Team name or label (e.g., 'Team 1', 'Team 2', 'OpTic', 'FaZe', 'Blue', 'Red')")
    kills: int = Field(default=0, description="Kills or Eliminations count")
    deaths: int = Field(default=0, description="Deaths count")
    assists: int = Field(default=0, description="Assists count")
    damage: int = Field(default=0, description="Total damage dealt")
    score: int = Field(default=0, description="Player in-game score")
    objective: Optional[str] = Field(default="", description="Objective stat like time on hill (e.g. 1:12), captures, defends, or plants")


class ScoreboardResult(BaseModel):
    game_title: Optional[str] = Field(default="Call of Duty", description="Game title, e.g. Black Ops 6, Modern Warfare III")
    game_mode: Optional[str] = Field(default="Multiplayer", description="Game mode, e.g. Hardpoint, Search & Destroy, Control, TDM")
    map_name: Optional[str] = Field(default="Unknown Map", description="Map name, e.g. Skyline, Babylon, Rewind, Karachi, Rio")
    team1_name: Optional[str] = Field(default="Team 1", description="Name of Team 1 / Blue team")
    team1_score: Optional[int] = Field(default=0, description="Final score of Team 1")
    team2_name: Optional[str] = Field(default="Team 2", description="Name of Team 2 / Red/Orange team")
    team2_score: Optional[int] = Field(default=0, description="Final score of Team 2")
    players: List[PlayerRow] = Field(default_factory=list, description="List of all players on the scoreboard with their stats")


def gemini_models() -> List[str]:
    raw = os.getenv("GEMINI_MODELS", "")
    models = [part.strip() for part in raw.split(",") if _MODEL_NAME.fullmatch(part.strip())]
    return models or list(DEFAULT_GEMINI_MODELS)


def is_transient_gemini_error(exc: Exception) -> bool:
    """True for overload, rate limit, and server errors worth retrying."""
    code = getattr(exc, "code", None)
    if code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    status = str(getattr(exc, "status", "") or "").upper()
    if status in {"UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "ABORTED"}:
        return True
    text = str(exc).lower()
    return any(token in text for token in ("unavailable", "overloaded", "resource_exhausted", "timed out", "timeout"))


def is_model_unavailable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code == 404:
        return True
    text = str(exc).lower()
    return any(token in text for token in ("not found", "unknown model", "is not supported", "not_found"))


def prepare_image_bytes(image_bytes: bytes) -> bytes:
    """Decode an untrusted upload into a bounded RGB PNG."""
    if not image_bytes:
        raise ImageRejected("The upload was empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageRejected("That image is too large. Upload a screenshot under 8 MB.")

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.load()
                if image.width < 16 or image.height < 16:
                    raise ImageRejected("That image is too small to be a scoreboard.")
                frame = image.convert("RGB")
                frame.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                frame.save(buffer, format="PNG")
                return buffer.getvalue()
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("That image is too large to process safely.")
    except Exception as exc:
        logger.info("Rejected upload before decoding finished: %s", type(exc).__name__)
        raise ImageRejected("That file is not a readable screenshot.") from exc


def normalize_scoreboard(data: Dict[str, Any], engine: str) -> Dict[str, Any]:
    """Turn model or OCR output into the dict the rest of the bot stores."""
    players = []
    raw_players = data.get("players") or []
    if not isinstance(raw_players, list):
        raw_players = []
    for raw in raw_players:
        if not isinstance(raw, dict):
            continue
        name = clean_untrusted_text(raw.get("name"), 32)
        if not name:
            continue
        players.append({
            "name": name,
            "team": clean_untrusted_text(raw.get("team"), 32) or "Unknown",
            "kills": clamp_int(raw.get("kills")),
            "deaths": clamp_int(raw.get("deaths")),
            "assists": clamp_int(raw.get("assists")),
            "damage": clamp_int(raw.get("damage")),
            "score": clamp_int(raw.get("score")),
            "objective": clean_untrusted_text(raw.get("objective"), 24),
        })
        if len(players) >= MAX_PLAYERS:
            break

    def label(key: str, default: str, limit: int = 40) -> str:
        return clean_untrusted_text(data.get(key), limit) or default

    return {
        "success": True,
        "engine": engine,
        "game_title": label("game_title", "Call of Duty"),
        "game_mode": label("game_mode", "Multiplayer"),
        "map_name": label("map_name", "Unknown Map"),
        "team1_name": label("team1_name", "Team 1", 32),
        "team1_score": clamp_int(data.get("team1_score")),
        "team2_name": label("team2_name", "Team 2", 32),
        "team2_score": clamp_int(data.get("team2_score")),
        "players": players,
    }


def scoreboard_dict_from_response(response) -> Dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed
    text = getattr(response, "text", None)
    if text is None or not str(text).strip():
        raise RuntimeError("Gemini returned an empty response.")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("Gemini response was not a JSON object.")
    return data


class ScoreboardExtractor:
    """Extracts scoreboard tables from Call of Duty screenshots."""

    def __init__(self, gemini_api_key: Optional[str] = None):
        if gemini_api_key is None:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.api_key = normalize_api_key(gemini_api_key)
        self._gemini_client = None

    def _get_gemini_client(self):
        """Lazy load Gemini client."""
        if self._gemini_client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set. Add it to the .env file next to bot.py.")
            from google import genai
            self._gemini_client = genai.Client(api_key=self.api_key)
        return self._gemini_client

    def _safe_error(self, exc: Exception) -> str:
        text = redact_secrets(str(exc), [self.api_key or ""])
        return " ".join(text.split())[:180]

    async def extract_from_bytes(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        preferred_engine: str = "gemini"
    ) -> Dict[str, Any]:
        """
        Extract scoreboard data from image bytes.
        preferred_engine: 'gemini' or 'ocr'
        """
        del mime_type  # Uploads are re-encoded to PNG before either engine sees them.
        try:
            safe_png = prepare_image_bytes(image_bytes)
        except ImageRejected as exc:
            return {"success": False, "error": str(exc), "players": []}

        engine = (preferred_engine or "gemini").strip().lower()
        if engine == "gemini":
            if not self.api_key:
                return {
                    "success": False,
                    "error": "Gemini is selected, but GEMINI_API_KEY is not set. Add the key, or switch this channel to local OCR with /set_engine.",
                    "players": [],
                }
            try:
                return await self._extract_with_gemini(safe_png)
            except Exception as exc:
                logger.warning("Gemini extraction failed: %s. Attempting local OCR fallback.", self._safe_error(exc))
                ocr_result = await self._extract_with_local_ocr(safe_png)
                if ocr_result.get("success"):
                    ocr_result["warning"] = "Gemini could not read this image, so local OCR was used. Check the numbers before trusting them."
                else:
                    reason = self._safe_error(exc)
                    ocr_error = ocr_result.get("error") or "Could not read that screenshot."
                    ocr_result["error"] = f"{ocr_error} Gemini said: {reason}" if reason else ocr_error
                return ocr_result
        return await self._extract_with_local_ocr(safe_png)

    async def _extract_with_gemini(self, image_bytes: bytes) -> Dict[str, Any]:
        """Use Gemini Flash to extract structured scoreboard data."""
        from google.genai import types

        client = self._get_gemini_client()
        system_instruction = (
            "You are an expert Call of Duty League (CDL) esports statistician. "
            "Your task is to accurately extract all scoreboard data from an end-game Call of Duty screenshot "
            "(such as Black Ops 6, Modern Warfare III, or Warzone). "
            "Instructions:\n"
            "1. Read the player table accurately. Identify each player's Gamertag / Name, Team, Kills (or Eliminations), Deaths, "
            "Assists, Damage, Score, and Objective (e.g. Hill time, captures, defends).\n"
            "2. Distinguish between the two teams (e.g. Friendly vs Enemy, Team 1 vs Team 2, or custom team names if CDL).\n"
            "3. Identify the Game Mode (Hardpoint, Search & Destroy, Control, etc.), Map Name, and final Team Scores if visible.\n"
            "4. Return clean, strictly structured JSON."
        )
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ScoreboardResult,
            temperature=0.1,
        )

        max_retries_per_model = 2
        base_delay = 2.0
        response = None
        for model_name in gemini_models():
            def _call_gemini(model=model_name):
                return client.models.generate_content(
                    model=model,
                    contents=[image_part, "Extract the full scoreboard statistics for both teams and all players."],
                    config=config,
                )

            for attempt in range(1, max_retries_per_model + 1):
                try:
                    response = await asyncio.to_thread(_call_gemini)
                    logger.info("Gemini extraction succeeded with model: %s", model_name)
                    break
                except Exception as exc:
                    detail = self._safe_error(exc)
                    if is_model_unavailable(exc):
                        logger.info("Model %s is unavailable (%s). Trying the next model.", model_name, detail)
                        response = None
                        break
                    if is_transient_gemini_error(exc) and attempt < max_retries_per_model:
                        delay = base_delay * (2 ** (attempt - 1)) + random.random()
                        logger.info(
                            "Gemini attempt %s/%s on %s failed (%s). Retrying in %.1fs.",
                            attempt, max_retries_per_model, model_name, detail, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if is_transient_gemini_error(exc):
                        logger.info("Model %s kept failing (%s). Trying the next model.", model_name, detail)
                        response = None
                        break
                    raise
            if response is not None:
                break

        if response is None:
            raise RuntimeError("All Gemini models returned errors.")

        data = scoreboard_dict_from_response(response)
        result = normalize_scoreboard(data, "gemini")
        if not result["players"]:
            raise RuntimeError("Gemini did not return any player rows.")
        return result

    async def _extract_with_local_ocr(self, image_bytes: bytes) -> Dict[str, Any]:
        """Local OCR fallback using Pillow preprocessing and pytesseract."""
        try:
            import pytesseract
        except ImportError:
            return {
                "success": False,
                "error": "Pytesseract is not installed, and Gemini did not return a scoreboard.",
                "players": [],
            }

        try:
            image = Image.open(io.BytesIO(image_bytes))
            gray = image.convert("L")
            enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
            thresh = enhanced.point(lambda pixel: 255 if pixel > 120 else 0)
            text = pytesseract.image_to_string(thresh)
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            players = []
            for line in lines:
                parts = line.split()
                nums = [part for part in parts if part.isdigit()]
                if len(nums) >= 2:
                    name_parts = [part for part in parts if not part.isdigit()]
                    name = " ".join(name_parts) if name_parts else "Player"
                    players.append({
                        "name": name,
                        "team": "Team 1",
                        "kills": nums[0] if nums else 0,
                        "deaths": nums[1] if len(nums) > 1 else 0,
                        "assists": nums[2] if len(nums) > 2 else 0,
                        "damage": nums[3] if len(nums) > 3 else 0,
                        "score": 0,
                        "objective": "",
                    })

            if not players:
                return {
                    "success": False,
                    "engine": "local_ocr",
                    "error": "Local OCR could not find scoreboard rows. Gemini reads these screenshots much more reliably.",
                    "players": [],
                }

            result = normalize_scoreboard(
                {
                    "game_title": "Call of Duty",
                    "game_mode": "Multiplayer",
                    "map_name": "Map",
                    "team1_name": "Team 1",
                    "team1_score": 0,
                    "team2_name": "Team 2",
                    "team2_score": 0,
                    "players": players,
                },
                "local_ocr",
            )
            result["warning"] = "Local OCR cannot tell the teams apart and often misreads digits. Use Gemini when you can."
            return result
        except Exception as exc:
            error = "OCR processing failed."
            if exc.__class__.__name__ == "TesseractNotFoundError":
                error = "Tesseract OCR is not installed on this host. Install the tesseract-ocr package, or use Gemini."
            else:
                logger.info("OCR failed: %s", redact_secrets(str(exc)))
            return {
                "success": False,
                "engine": "local_ocr",
                "error": error,
                "players": [],
            }
