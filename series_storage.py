"""SQLite persistence for active match series."""
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("cod_bot.storage")


def resolve_database_path(raw: Optional[str], base_dir: Optional[Path] = None) -> str:
    """Resolve a database path. Relative paths stay next to the bot, not the shell cwd."""
    configured = (raw or "").strip() or "cod_bot.db"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        root = base_dir or Path.cwd()
        path = root / path
    return str(path)


class SeriesStorage:
    """Stores active series by Discord channel ID."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS active_series (
                        channel_id INTEGER PRIMARY KEY,
                        series_json TEXT NOT NULL
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def load_all(self) -> Dict[int, Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT channel_id, series_json FROM active_series"
            ).fetchall()

        series_by_channel: Dict[int, Dict[str, Any]] = {}
        for channel_id, series_json in rows:
            try:
                series = json.loads(series_json)
            except json.JSONDecodeError:
                logger.warning("Skipping unreadable series for channel %s", channel_id)
                continue
            if not isinstance(series, dict):
                logger.warning("Skipping series for channel %s because it is not an object", channel_id)
                continue
            series_by_channel[int(channel_id)] = series
        return series_by_channel

    def save(self, channel_id: int, series: Dict[str, Any]) -> None:
        payload = json.dumps(series, ensure_ascii=False)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO active_series (channel_id, series_json)
                    VALUES (?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET series_json = excluded.series_json
                    """,
                    (int(channel_id), payload),
                )

    def delete(self, channel_id: int) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM active_series WHERE channel_id = ?",
                    (int(channel_id),),
                )
