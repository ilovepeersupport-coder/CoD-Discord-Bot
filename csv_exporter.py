"""
Call of Duty Stats CSV Exporter
Exports series summary and map-by-map player performance to CSV format.
"""
import io
import csv
from typing import Dict, Any, List


class CSVExporter:
    """Exports league match statistics to CSV."""

    @classmethod
    def generate_series_csv(cls, series_data: Dict[str, Any], series_title: str = "Series") -> io.StringIO:
        """
        Generates a detailed CSV with both the overall series averages
        and the individual map-by-map breakdowns.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header Info
        writer.writerow(["=== CALL OF DUTY LEAGUE STATS EXPORT ==="])
        writer.writerow(["Series Title", series_title])
        writer.writerow(["Total Maps", series_data.get("total_maps", 0)])

        team_wins = series_data.get("team_wins", {})
        if team_wins:
            writer.writerow(["Team Record", " vs ".join([f"{t}: {w}" for t, w in team_wins.items()])])

        mvp = series_data.get("mvp")
        if mvp:
            writer.writerow(["Series MVP", mvp.get("name"), f"K/D: {mvp.get('kd')}", f"Avg Kills: {mvp.get('avg_kills')}"])
        writer.writerow([])

        # Section 1: Consolidated Overall Series Averages
        writer.writerow(["--- OVERALL SERIES STATS & AVERAGES ---"])
        writer.writerow([
            "Player",
            "Team",
            "Maps Played",
            "Total Kills",
            "Total Deaths",
            "+/- Differential",
            "K/D Ratio",
            "Avg Kills/Map",
            "Avg Deaths/Map",
            "Total Assists",
            "Avg Assists/Map",
            "Total Damage",
            "Avg Damage/Map",
            "Total Score",
            "Avg Score/Map",
            "MVP Rating"
        ])

        for p in series_data.get("players", []):
            writer.writerow([
                p.get("name"),
                p.get("team"),
                p.get("maps_played"),
                p.get("kills"),
                p.get("deaths"),
                p.get("plus_minus"),
                f"{p.get('kd'):.2f}",
                p.get("avg_kills"),
                p.get("avg_deaths"),
                p.get("assists"),
                p.get("avg_assists"),
                p.get("damage"),
                p.get("avg_damage"),
                p.get("score"),
                p.get("avg_score"),
                p.get("mvp_rating")
            ])

        writer.writerow([])

        # Section 2: Map by Map Breakdown
        writer.writerow(["--- MAP-BY-MAP BREAKDOWN ---"])
        writer.writerow([
            "Map #",
            "Map Name",
            "Game Mode",
            "Player",
            "Team",
            "Kills",
            "Deaths",
            "+/-",
            "K/D",
            "Assists",
            "Damage",
            "Score",
            "Objective"
        ])

        for p in series_data.get("players", []):
            for rec in p.get("map_records", []):
                writer.writerow([
                    rec.get("map_number"),
                    rec.get("map_name"),
                    rec.get("game_mode"),
                    p.get("name"),
                    p.get("team"),
                    rec.get("kills"),
                    rec.get("deaths"),
                    rec.get("plus_minus"),
                    f"{rec.get('kd'):.2f}",
                    rec.get("assists"),
                    rec.get("damage"),
                    rec.get("score"),
                    rec.get("objective", "")
                ])

        output.seek(0)
        return output
