"""SQLite persistence for active match series."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict


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
        return sqlite3.connect(self.database_path)

    def load_all(self) -> Dict[int, Dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT channel_id, series_json FROM active_series"
            ).fetchall()

        series_by_channel: Dict[int, Dict[str, Any]] = {}
        for channel_id, series_json in rows:
            series = json.loads(series_json)
            if not isinstance(series, dict):
                raise ValueError(f"Stored series for channel {channel_id} is not an object.")
            series_by_channel[channel_id] = series
        return series_by_channel

    def save(self, channel_id: int, series: Dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO active_series (channel_id, series_json)
                    VALUES (?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET series_json = excluded.series_json
                    """,
                    (channel_id, json.dumps(series)),
                )

    def delete(self, channel_id: int) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM active_series WHERE channel_id = ?",
                    (channel_id,),
                )
