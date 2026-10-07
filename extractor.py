"""
Call of Duty Scoreboard Extractor
Supports Gemini AI Vision (primary, high-accuracy) and Local OCR fallback.
Extracts player stats (Kills, Deaths, Assists, Damage, Score, Objective) from screenshots.
"""
import io
import os
import json
import logging
from typing import Dict, Any, List, Optional
from PIL import Image, ImageEnhance, ImageFilter
from pydantic import BaseModel, Field

# Setup logging
logger = logging.getLogger("cod_extractor")


# Pydantic Schemas for Structured Gemini Output
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


class ScoreboardExtractor:
    """Extracts scoreboard tables from Call of Duty screenshots."""

    def __init__(self, gemini_api_key: Optional[str] = None):
        self.api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        self._gemini_client = None

    def _get_gemini_client(self):
        """Lazy load Gemini client."""
        if not self._gemini_client:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file or bot settings.")
            from google import genai
            self._gemini_client = genai.Client(api_key=self.api_key)
        return self._gemini_client

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
        if preferred_engine == "gemini" and self.api_key:
            try:
                return await self._extract_with_gemini(image_bytes, mime_type)
            except Exception as e:
                logger.warning(f"Gemini extraction failed: {e}. Attempting local OCR fallback.")
                return await self._extract_with_local_ocr(image_bytes)
        else:
            return await self._extract_with_local_ocr(image_bytes)

    async def _extract_with_gemini(self, image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """Use Gemini 3.8 Flash to extract structured scoreboard data."""
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

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=ScoreboardResult,
            temperature=0.1
        )

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[image_part, "Extract the full scoreboard statistics for both teams and all players."],
            config=config
        )

        # Parse result
        raw_text = response.text
        data = json.loads(raw_text)

        # Clean and validate players
        players = []
        for p in data.get("players", []):
            pname = p.get("name", "").strip()
            if pname:
                players.append({
                    "name": pname,
                    "team": p.get("team", "Unknown"),
                    "kills": int(p.get("kills", 0) or 0),
                    "deaths": int(p.get("deaths", 0) or 0),
                    "assists": int(p.get("assists", 0) or 0),
                    "damage": int(p.get("damage", 0) or 0),
                    "score": int(p.get("score", 0) or 0),
                    "objective": str(p.get("objective", "") or "")
                })

        return {
            "success": True,
            "engine": "gemini",
            "game_title": data.get("game_title", "Call of Duty"),
            "game_mode": data.get("game_mode", "Multiplayer"),
            "map_name": data.get("map_name", "Unknown Map"),
            "team1_name": data.get("team1_name", "Team 1"),
            "team1_score": int(data.get("team1_score", 0) or 0),
            "team2_name": data.get("team2_name", "Team 2"),
            "team2_score": int(data.get("team2_score", 0) or 0),
            "players": players
        }

    async def _extract_with_local_ocr(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Local OCR fallback using Pillow image preprocessing and pytesseract.
        """
        try:
            import pytesseract
        except ImportError:
            return {
                "success": False,
                "error": "Pytesseract is not installed and no GEMINI_API_KEY was provided.",
                "players": []
            }

        try:
            image = Image.open(io.BytesIO(image_bytes))

            # Preprocess image to enhance text contrast (game scoreboards have dark transparent backgrounds)
            gray = image.convert("L")
            # Increase contrast
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(2.0)
            # Thresholding
            thresh = enhanced.point(lambda p: 255 if p > 120 else 0)

            # Perform OCR
            text = pytesseract.image_to_string(thresh)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Basic heuristic extraction from OCR lines
            players = []
            for line in lines:
                parts = line.split()
                # If line has multiple numbers at the end, it might be a player row
                nums = [p for p in parts if p.isdigit()]
                if len(nums) >= 2:
                    name_parts = [p for p in parts if not p.isdigit()]
                    name = " ".join(name_parts) if name_parts else "Player"
                    k = int(nums[0]) if len(nums) > 0 else 0
                    d = int(nums[1]) if len(nums) > 1 else 0
                    a = int(nums[2]) if len(nums) > 2 else 0
                    dmg = int(nums[3]) if len(nums) > 3 else 0
                    players.append({
                        "name": name,
                        "team": "Team 1",
                        "kills": k,
                        "deaths": d,
                        "assists": a,
                        "damage": dmg,
                        "score": 0,
                        "objective": ""
                    })

            if not players:
                return {
                    "success": False,
                    "engine": "local_ocr",
                    "error": "Local OCR could not reliably detect scoreboard rows. For best results, use Gemini AI Vision (free API key).",
                    "raw_text": "\n".join(lines[:15]),
                    "players": []
                }

            return {
                "success": True,
                "engine": "local_ocr",
                "game_title": "Call of Duty",
                "game_mode": "Multiplayer",
                "map_name": "Map",
                "team1_name": "Team 1",
                "team1_score": 0,
                "team2_name": "Team 2",
                "team2_score": 0,
                "players": players
            }

        except Exception as e:
            return {
                "success": False,
                "engine": "local_ocr",
                "error": f"OCR processing failed: {str(e)}",
                "players": []
            }
