"""Tests for persistent active-series storage."""
import tempfile
import unittest
from pathlib import Path

from series_storage import SeriesStorage


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


if __name__ == "__main__":
    unittest.main()
