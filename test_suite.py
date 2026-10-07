"""
Test suite for Call of Duty League Stats Bot
Verifies StatsManager calculations, GraphicGenerator image output, and CSVExporter.
"""
import io
import os
import unittest
from stats_manager import StatsManager
from image_generator import GraphicGenerator
from csv_exporter import CSVExporter

# Mock data simulating a 3-game Call of Duty match series
MOCK_SERIES_MAPS = [
    {
        "map_number": 1,
        "map_name": "Skyline",
        "game_mode": "Hardpoint",
        "team1_name": "OpTic Texas",
        "team2_name": "Atlanta FaZe",
        "team1_score": 250,
        "team2_score": 215,
        "players": [
            {"name": "Shotzzy", "team": "OpTic Texas", "kills": 34, "deaths": 25, "assists": 8, "damage": 4650, "score": 4100},
            {"name": "Dashy", "team": "OpTic Texas", "kills": 28, "deaths": 20, "assists": 12, "damage": 4300, "score": 3800},
            {"name": "Kenny", "team": "OpTic Texas", "kills": 25, "deaths": 26, "assists": 10, "damage": 3900, "score": 3450},
            {"name": "Pred", "team": "OpTic Texas", "kills": 26, "deaths": 23, "assists": 7, "damage": 4050, "score": 3600},
            {"name": "Simp", "team": "Atlanta FaZe", "kills": 31, "deaths": 27, "assists": 9, "damage": 4500, "score": 3950},
            {"name": "aBeZy", "team": "Atlanta FaZe", "kills": 27, "deaths": 29, "assists": 6, "damage": 4100, "score": 3500},
            {"name": "Cellium", "team": "Atlanta FaZe", "kills": 22, "deaths": 18, "assists": 14, "damage": 3850, "score": 3300},
            {"name": "Drazah", "team": "Atlanta FaZe", "kills": 24, "deaths": 29, "assists": 8, "damage": 3700, "score": 3200}
        ]
    },
    {
        "map_number": 2,
        "map_name": "Karachi",
        "game_mode": "Search & Destroy",
        "team1_name": "OpTic Texas",
        "team2_name": "Atlanta FaZe",
        "team1_score": 4,
        "team2_score": 6,
        "players": [
            {"name": "Shotzzy", "team": "OpTic Texas", "kills": 8, "deaths": 7, "assists": 2, "damage": 1200, "score": 950},
            {"name": "Dashy", "team": "OpTic Texas", "kills": 6, "deaths": 6, "assists": 3, "damage": 1050, "score": 800},
            {"name": "Kenny", "team": "OpTic Texas", "kills": 5, "deaths": 7, "assists": 1, "damage": 850, "score": 650},
            {"name": "Pred", "team": "OpTic Texas", "kills": 7, "deaths": 7, "assists": 2, "damage": 1100, "score": 850},
            {"name": "Simp", "team": "Atlanta FaZe", "kills": 11, "deaths": 6, "assists": 3, "damage": 1650, "score": 1400},
            {"name": "aBeZy", "team": "Atlanta FaZe", "kills": 8, "deaths": 7, "assists": 4, "damage": 1300, "score": 1050},
            {"name": "Cellium", "team": "Atlanta FaZe", "kills": 5, "deaths": 6, "assists": 5, "damage": 950, "score": 750},
            {"name": "Drazah", "team": "Atlanta FaZe", "kills": 6, "deaths": 7, "assists": 2, "damage": 900, "score": 700}
        ]
    },
    {
        "map_number": 3,
        "map_name": "Sub Base",
        "game_mode": "Control",
        "team1_name": "OpTic Texas",
        "team2_name": "Atlanta FaZe",
        "team1_score": 3,
        "team2_score": 1,
        "players": [
            {"name": "Shotzzy", "team": "OpTic Texas", "kills": 29, "deaths": 19, "assists": 7, "damage": 3800, "score": 3300},
            {"name": "Dashy", "team": "OpTic Texas", "kills": 24, "deaths": 15, "assists": 9, "damage": 3500, "score": 3100},
            {"name": "Kenny", "team": "OpTic Texas", "kills": 21, "deaths": 20, "assists": 8, "damage": 3100, "score": 2700},
            {"name": "Pred", "team": "OpTic Texas", "kills": 27, "deaths": 18, "assists": 6, "damage": 3600, "score": 3200},
            {"name": "Simp", "team": "Atlanta FaZe", "kills": 23, "deaths": 25, "assists": 8, "damage": 3400, "score": 2950},
            {"name": "aBeZy", "team": "Atlanta FaZe", "kills": 20, "deaths": 27, "assists": 5, "damage": 3050, "score": 2600},
            {"name": "Cellium", "team": "Atlanta FaZe", "kills": 18, "deaths": 22, "assists": 11, "damage": 2900, "score": 2500},
            {"name": "Drazah", "team": "Atlanta FaZe", "kills": 19, "deaths": 27, "assists": 4, "damage": 2800, "score": 2400}
        ]
    }
]


class TestCoDStats(unittest.TestCase):

    def test_stats_aggregation(self):
        result = StatsManager.aggregate_series_stats(MOCK_SERIES_MAPS)
        self.assertEqual(result["total_maps"], 3)
        self.assertEqual(result["team_wins"]["OpTic Texas"], 2)
        self.assertEqual(result["team_wins"]["Atlanta FaZe"], 1)

        # Check Shotzzy total kills: 34 + 8 + 29 = 71
        shotzzy = next(p for p in result["players"] if p["name"] == "Shotzzy")
        self.assertEqual(shotzzy["kills"], 71)
        self.assertEqual(shotzzy["deaths"], 51)
        self.assertEqual(shotzzy["maps_played"], 3)
        # Avg kills = 71 / 3 = 23.7
        self.assertEqual(shotzzy["avg_kills"], 23.7)
        # Total damage = 4650 + 1200 + 3800 = 9650
        self.assertEqual(shotzzy["damage"], 9650)
        self.assertEqual(shotzzy["avg_damage"], round(9650 / 3, 1))

        # Check MVP exists
        mvp = result["mvp"]
        self.assertIsNotNone(mvp)
        print(f"\n[Test] Calculated MVP: {mvp['name']} with K/D {mvp['kd']} and Rating {mvp['mvp_rating']}")

    def test_graphic_generation(self):
        result = StatsManager.aggregate_series_stats(MOCK_SERIES_MAPS)
        img_buffer = GraphicGenerator.generate_series_card(result, series_title="CDL CHAMPIONSHIP: OPTIC VS FAZE")
        self.assertGreater(img_buffer.getbuffer().nbytes, 50000)

        # Save sample card for inspection
        with open("sample_match_summary.png", "wb") as f:
            f.write(img_buffer.getvalue())
        print(f"[Test] Successfully generated 'sample_match_summary.png' ({img_buffer.getbuffer().nbytes} bytes)")

    def test_csv_export(self):
        result = StatsManager.aggregate_series_stats(MOCK_SERIES_MAPS)
        csv_stream = CSVExporter.generate_series_csv(result, series_title="OpTic vs FaZe Best of 3")
        csv_content = csv_stream.getvalue()
        self.assertIn("OVERALL SERIES STATS & AVERAGES", csv_content)
        self.assertIn("Shotzzy", csv_content)
        self.assertIn("Simp", csv_content)
        self.assertIn("MAP-BY-MAP BREAKDOWN", csv_content)

        with open("sample_export.csv", "w", encoding="utf-8") as f:
            f.write(csv_content)
        print(f"[Test] Successfully generated 'sample_export.csv' ({len(csv_content)} characters)")


if __name__ == "__main__":
    unittest.main()
