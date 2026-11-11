"""Tests for persistent active-series storage."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from series_storage import SeriesStorage, resolve_database_path


class TestSeriesStorage(unittest.TestCase):
    def test_series_survive_storage_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "series.db")
            first_storage = SeriesStorage(database_path)
            first_storage.save(
                123,
                {
                    "title": "Match night",
                    "maps": [{"map_number": 1, "players": [{"name": "Player"}]}],
                },
            )

            restored = SeriesStorage(database_path).load_all()

        self.assertEqual(
            restored,
            {
                123: {
                    "title": "Match night",
                    "maps": [{"map_number": 1, "players": [{"name": "Player"}]}],
                }
            },
        )

    def test_save_replaces_series_and_delete_removes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SeriesStorage(str(Path(directory) / "series.db"))
            storage.save(123, {"title": "Old title", "maps": []})
            storage.save(123, {"title": "Updated title", "maps": []})

            self.assertEqual(storage.load_all()[123]["title"], "Updated title")

            storage.delete(123)

            self.assertEqual(storage.load_all(), {})

    def test_corrupt_rows_are_skipped_and_left_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "series.db")
            storage = SeriesStorage(database_path)
            storage.save(1, {"title": "ok", "maps": []})
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "INSERT INTO active_series (channel_id, series_json) VALUES (?, ?)",
                    (2, "not-json"),
                )
                connection.execute(
                    "INSERT INTO active_series (channel_id, series_json) VALUES (?, ?)",
                    (3, "[1, 2, 3]"),
                )
                connection.commit()

            self.assertEqual(list(storage.load_all()), [1])
            with closing(sqlite3.connect(database_path)) as connection:
                remaining = connection.execute("SELECT channel_id FROM active_series ORDER BY channel_id").fetchall()
            self.assertEqual(remaining, [(1,), (2,), (3,)])

    def test_relative_database_path_uses_the_given_base_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            resolved = resolve_database_path("nested/series.db", Path(directory))
            self.assertEqual(resolved, str(Path(directory) / "nested" / "series.db"))
            self.assertTrue(Path(resolve_database_path("/tmp/cod-series.db")).is_absolute())


if __name__ == "__main__":
    unittest.main()
