"""
Standalone CLI Tester for Call of Duty League Stats
Allows testing scoreboard screenshots and series averaging directly from terminal
without needing a live Discord bot.
Usage:
  python cli_test.py screenshot1.png screenshot2.png screenshot3.png
"""
import sys
import os
import asyncio
from extractor import ScoreboardExtractor
from stats_manager import StatsManager
from image_generator import GraphicGenerator
from csv_exporter import CSVExporter
from dotenv import load_dotenv

load_dotenv()


async def process_screenshots(image_paths):
    print("=" * 60)
    print("🎯 CALL OF DUTY LEAGUE STATS PROCESSOR (CLI TEST)")
    print("=" * 60)

    extractor = ScoreboardExtractor(gemini_api_key=os.getenv("GEMINI_API_KEY"))
    maps_data = []

    for idx, path in enumerate(image_paths, start=1):
        if not os.path.exists(path):
            print(f"⚠️ File not found: {path}")
            continue

        print(f"\n[Map {idx}] Processing: {os.path.basename(path)}...")
        with open(path, "rb") as f:
            img_bytes = f.read()

        mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        res = await extractor.extract_from_bytes(img_bytes, mime_type=mime)

        if not res.get("success"):
            print(f"❌ Failed to extract from {path}: {res.get('error')}")
            continue

        map_entry = {
            "map_number": idx,
            "map_name": res.get("map_name", f"Map {idx}"),
            "game_mode": res.get("game_mode", "Multiplayer"),
            "team1_name": res.get("team1_name", "Team 1"),
            "team2_name": res.get("team2_name", "Team 2"),
            "team1_score": res.get("team1_score", 0),
            "team2_score": res.get("team2_score", 0),
            "players": res.get("players", [])
        }
        maps_data.append(map_entry)
        print(f"✅ Extracted {len(map_entry['players'])} players from {map_entry['map_name']} ({map_entry['game_mode']})")

    if not maps_data:
        print("\n⚠️ No map data extracted. Ensure images are valid scoreboard screenshots.")
        return

    # Aggregate
    print("\n" + "=" * 60)
    print("📊 AGGREGATING SERIES STATS & AVERAGES...")
    print("=" * 60)
    series_result = StatsManager.aggregate_series_stats(maps_data)

    mvp = series_result.get("mvp")
    print(f"\n🌟 SERIES MVP: {mvp.get('name')} | K/D: {mvp.get('kd'):.2f} | Avg Kills: {mvp.get('avg_kills')} | Damage: {mvp.get('damage'):,}")

    print("\n--- PLAYER SERIES AVERAGES ---")
    header = f"{'Player':<16} {'Team':<12} {'Maps':<5} {'K':<4} {'D':<4} {'+/-':<5} {'K/D':<6} {'Avg K':<6} {'Avg D':<6} {'Total Dmg':<10}"
    print(header)
    print("-" * len(header))
    for p in series_result.get("players", []):
        diff = p.get("plus_minus", 0)
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        print(f"{p['name'][:15]:<16} {p['team'][:11]:<12} {p['maps_played']:<5} {p['kills']:<4} {p['deaths']:<4} {diff_str:<5} {p['kd']:<6.2f} {p['avg_kills']:<6.1f} {p['avg_deaths']:<6.1f} {p['damage']:<10,}")

    # Generate Image
    img_buffer = GraphicGenerator.generate_series_card(series_result, series_title="CALL OF DUTY LEAGUE MATCH")
    out_img = "cli_series_summary.png"
    with open(out_img, "wb") as f:
        f.write(img_buffer.getvalue())
    print(f"\n🖼️ Generated infographic graphic: {out_img}")

    # Generate CSV
    csv_stream = CSVExporter.generate_series_csv(series_result, series_title="CLI Series Summary")
    out_csv = "cli_series_summary.csv"
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write(csv_stream.getvalue())
    print(f"📄 Generated CSV spreadsheet: {out_csv}")
    print("\n Done!")


def main():
    if len(sys.argv) < 2:
        print("Usage: python cli_test.py <screenshot1.png> [screenshot2.png ...]")
        sys.exit(0)
    asyncio.run(process_screenshots(sys.argv[1:]))


if __name__ == "__main__":
    main()
