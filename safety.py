"""Guards for untrusted scoreboard text, CSV cells, and secret redaction."""
import re
from typing import Optional

_GOOGLE_API_KEY = re.compile(r"AIza[0-9A-Za-z\-_]{20,}")
_QUERY_SECRET = re.compile(r"(?i)(key|token|api_key|secret)=([^&\s]+)")
_PLACEHOLDER_KEYS = {
    "your_gemini_api_key_here",
    "your_discord_bot_token_here",
    "your_token_here",
}


def normalize_api_key(value: Optional[str]) -> Optional[str]:
    """Return a usable API key, or None for blanks and example placeholders."""
    key = (value or "").strip()
    if not key or key in _PLACEHOLDER_KEYS:
        return None
    return key


def redact_secrets(text: str, extra_secrets: Optional[list] = None) -> str:
    """Remove API keys from text before it is logged or shown to a channel."""
    redacted = "" if text is None else str(text)
    for secret in extra_secrets or []:
        if secret and len(str(secret)) >= 8:
            redacted = redacted.replace(str(secret), "[REDACTED]")
    redacted = _GOOGLE_API_KEY.sub("[REDACTED]", redacted)
    redacted = _QUERY_SECRET.sub(r"\1=[REDACTED]", redacted)
    return redacted


def clean_untrusted_text(value, limit: int = 80) -> str:
    """Flatten OCR/AI text so it cannot break embeds, mentions, or code blocks."""
    text = "" if value is None else str(value)
    text = text.replace("`", "'").replace("\\", "")
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def csv_cell(value) -> str:
    """Neutralize spreadsheet formulas in text cells. Leave real numbers alone."""
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def clamp_int(value, upper: int = 1_000_000) -> int:
    """Parse a stat into a non-negative int, ignoring blanks and absurd values."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value:
            return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return 0
    if number < 0:
        return 0
    if number > upper:
        return upper
    return number
