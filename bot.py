"""
Call of Duty League Discord Bot
Automatically extracts player stats from scoreboard screenshots,
aggregates kills/deaths/assists/damage/score across maps, calculates averages,
and generates infographics and CSV exports.
"""
import io
import os
import sys
import logging
from typing import Optional, Dict, Any, List

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load local modules
from extractor import ScoreboardExtractor
from stats_manager import StatsManager
from image_generator import GraphicGenerator
from csv_exporter import CSVExporter
from series_storage import SeriesStorage

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cod_bot")

# Tokens and Config
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "gemini")
SERIES_DB_PATH = os.getenv("SERIES_DB_PATH") or "cod_bot.db"

# Initialize Discord Client
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!cod ", intents=intents)

# Active series tracking per channel: channel_id -> SeriesData
series_storage = SeriesStorage(SERIES_DB_PATH)
active_series: Dict[int, Dict[str, Any]] = series_storage.load_all()
logger.info("Restored %s active series from %s", len(active_series), SERIES_DB_PATH)

# Active engine setting per guild/channel
channel_engine_preference: Dict[int, str] = {}


def get_extractor() -> ScoreboardExtractor:
    """Helper to instantiate or return extractor."""
    return ScoreboardExtractor(gemini_api_key=os.getenv("GEMINI_API_KEY"))


def format_players_table(players: List[Dict[str, Any]]) -> str:
    """Format players into a clean monospaced Discord table."""
    lines = ["```", f"{'Player':<16} {'Team':<10} {'K':<4} {'D':<4} {'+/-':<5} {'K/D':<6} {'Dmg':<6}", "-" * 55]
    for p in players:
        name = p.get("name", "Player")[:15]
        team = str(p.get("team", "-"))[:9]
        k = p.get("kills", 0)
        d = p.get("deaths", 0)
        diff = k - d
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        kd = StatsManager.calculate_kd(k, d)
        dmg = p.get("damage", 0)
        lines.append(f"{name:<16} {team:<10} {k:<4} {d:<4} {diff_str:<5} {kd:<6.2f} {dmg:<6}")
    lines.append("```")
    return "\n".join(lines)


@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user.name} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} application (slash) commands.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")


# ==========================================
# SLASH COMMANDS
# ==========================================

@bot.tree.command(name="start_series", description="Start a new multi-map Call of Duty match series in this channel")
@app_commands.describe(
    name="Series name or title (e.g. CDL Week 1)",
    team1="Team 1 Name (e.g. OpTic)",
    team2="Team 2 Name (e.g. FaZe)",
    best_of="Best of X maps (e.g. 3 or 5)"
)
async def start_series(
    interaction: discord.Interaction,
    name: str = "Call of Duty League Match",
    team1: str = "Team 1",
    team2: str = "Team 2",
    best_of: int = 3
):
    channel_id = interaction.channel_id
    active_series[channel_id] = {
        "title": name,
        "team1": team1,
        "team2": team2,
        "best_of": best_of,
        "maps": [],
        "created_by": interaction.user.display_name
    }
    series_storage.save(channel_id, active_series[channel_id])

    embed = discord.Embed(
        title="🎮 Series Tracking Started!",
        description=(
            f"**{name}**\n"
            f"⚔️ **{team1}** vs **{team2}** (Best of {best_of})\n\n"
            f"**Next Steps:**\n"
            f"Upload your end-game screenshots using `/upload_map` after each game!\n"
            f"When all games are played, use `/series_summary` to get full averages, an esports graphic card, and CSV!"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Call of Duty League Bot • Upload screenshots to track")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="upload_map", description="Upload a scoreboard screenshot for the current series")
@app_commands.describe(
    screenshot="Screenshot image of the scoreboard",
    map_number="Map number in the series (e.g. 1, 2, 3)",
    map_name="Optional map name (e.g. Skyline, Babylon, Karachi)",
    game_mode="Optional game mode (e.g. Hardpoint, SnD, Control)"
)
async def upload_map(
    interaction: discord.Interaction,
    screenshot: discord.Attachment,
    map_number: Optional[int] = None,
    map_name: Optional[str] = None,
    game_mode: Optional[str] = None
):
    channel_id = interaction.channel_id
    if channel_id not in active_series:
        await interaction.response.send_message(
            "⚠️ No active series in this channel! Start one first with `/start_series`, or use `/quick_scan` for a one-off screenshot.",
            ephemeral=True
        )
        return

    # Defer to allow AI processing time
    await interaction.response.defer(thinking=True)

    series = active_series[channel_id]
    current_map_num = map_number or (len(series["maps"]) + 1)

    try:
        # Download image bytes
        image_bytes = await screenshot.read()
        mime_type = screenshot.content_type or "image/png"

        # Determine engine
        engine = channel_engine_preference.get(channel_id, DEFAULT_ENGINE)
        extractor = get_extractor()

        result = await extractor.extract_from_bytes(image_bytes, mime_type=mime_type, preferred_engine=engine)

        if not result.get("success"):
            error_msg = result.get("error", "Failed to extract text from scoreboard.")
            await interaction.followup.send(f"❌ **Error parsing screenshot:** {error_msg}")
            return

        # Override detected names if user explicitly provided them
        detected_map = map_name or result.get("map_name") or f"Map {current_map_num}"
        detected_mode = game_mode or result.get("game_mode") or "Multiplayer"
        t1_name = result.get("team1_name") or series.get("team1", "Team 1")
        t2_name = result.get("team2_name") or series.get("team2", "Team 2")
        t1_score = result.get("team1_score", 0)
        t2_score = result.get("team2_score", 0)

        # Store in series
        map_entry = {
            "map_number": current_map_num,
            "map_name": detected_map,
            "game_mode": detected_mode,
            "team1_name": t1_name,
            "team2_name": t2_name,
            "team1_score": t1_score,
            "team2_score": t2_score,
            "players": result.get("players", [])
        }

        # Check if map_number already exists and replace, else append
        existing_idx = next((i for i, m in enumerate(series["maps"]) if m["map_number"] == current_map_num), None)
        if existing_idx is not None:
            series["maps"][existing_idx] = map_entry
            action_text = f"Updated Map {current_map_num}"
        else:
            series["maps"].append(map_entry)
            series["maps"].sort(key=lambda x: x["map_number"])
            action_text = f"Added Map {current_map_num}"
        series_storage.save(channel_id, series)

        # Generate confirmation embed
        embed = discord.Embed(
            title=f"✅ {action_text}: {detected_map} ({detected_mode})",
            description=(
                f"**Score:** {t1_name} **{t1_score}** - **{t2_score}** {t2_name}\n"
                f"**Extracted {len(result.get('players', []))} players** using `{result.get('engine', 'unknown')}` engine.\n"
                f"Progress: **{len(series['maps'])} / {series.get('best_of', 3)}** maps recorded."
            ),
            color=discord.Color.green()
        )

        if result.get("players"):
            embed.add_field(
                name="Scoreboard Preview",
                value=format_players_table(result["players"][:8]),
                inline=False
            )

        embed.set_footer(text="Upload next map with /upload_map or finish with /series_summary")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.exception("Error processing screenshot upload")
        await interaction.followup.send(f"❌ An error occurred while processing the screenshot: {str(e)}")


@bot.tree.command(name="quick_scan", description="Scan a single scoreboard screenshot without starting a series")
@app_commands.describe(screenshot="Scoreboard screenshot image")
async def quick_scan(interaction: discord.Interaction, screenshot: discord.Attachment):
    await interaction.response.defer(thinking=True)

    try:
        image_bytes = await screenshot.read()
        mime_type = screenshot.content_type or "image/png"
        engine = channel_engine_preference.get(interaction.channel_id, DEFAULT_ENGINE)
        extractor = get_extractor()

        result = await extractor.extract_from_bytes(image_bytes, mime_type=mime_type, preferred_engine=engine)

        if not result.get("success"):
            await interaction.followup.send(f"❌ **Error parsing screenshot:** {result.get('error')}")
            return

        players = result.get("players", [])
        if not players:
            await interaction.followup.send("⚠️ No players were detected on this scoreboard image.")
            return

        # Single map summary
        map_data = [{
            "map_number": 1,
            "map_name": result.get("map_name", "Game 1"),
            "game_mode": result.get("game_mode", "Multiplayer"),
            "team1_name": result.get("team1_name", "Team 1"),
            "team2_name": result.get("team2_name", "Team 2"),
            "team1_score": result.get("team1_score", 0),
            "team2_score": result.get("team2_score", 0),
            "players": players
        }]

        aggregated = StatsManager.aggregate_series_stats(map_data)
        mvp = aggregated.get("mvp")

        embed = discord.Embed(
            title=f"📊 Scoreboard Analysis: {result.get('map_name', 'Game 1')}",
            description=(
                f"**Mode:** {result.get('game_mode', 'Multiplayer')}  |  "
                f"**Score:** {result.get('team1_name', 'Team 1')} {result.get('team1_score', 0)} - {result.get('team2_score', 0)} {result.get('team2_name', 'Team 2')}\n"
                f"**MVP:** 🌟 **{mvp.get('name')}** (K/D: {mvp.get('kd'):.2f}, Kills: {mvp.get('kills')}, Dmg: {mvp.get('damage'):,})"
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="Stats Table", value=format_players_table(players), inline=False)
        embed.set_footer(text=f"Engine: {result.get('engine', 'gemini')}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.exception("Error in quick_scan")
        await interaction.followup.send(f"❌ Failed to process screenshot: {str(e)}")


@bot.tree.command(name="series_summary", description="Calculate consolidated stats, averages, MVP card, and CSV for the series")
async def series_summary(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in active_series:
        await interaction.response.send_message("⚠️ No active series in this channel! Start one with `/start_series`.", ephemeral=True)
        return

    series = active_series[channel_id]
    if not series.get("maps"):
        await interaction.response.send_message("⚠️ No maps have been uploaded yet for this series. Use `/upload_map` to add maps.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    try:
        # 1. Aggregate statistics
        aggregated = StatsManager.aggregate_series_stats(series["maps"])

        # 2. Generate Graphic Infographic Card
        series_title = series.get("title", "Call of Duty League Match")
        image_buffer = GraphicGenerator.generate_series_card(aggregated, series_title=series_title)
        graphic_file = discord.File(image_buffer, filename="cod_match_summary.png")

        # 3. Generate CSV Export
        csv_stream = CSVExporter.generate_series_csv(aggregated, series_title=series_title)
        csv_bytes = io.BytesIO(csv_stream.getvalue().encode("utf-8"))
        csv_file = discord.File(csv_bytes, filename=f"cod_series_{channel_id}.csv")

        # 4. Generate Discord Embed
        mvp = aggregated.get("mvp")
        team_wins = aggregated.get("team_wins", {})

        record_str = " vs ".join([f"**{t}** ({w}W)" for t, w in team_wins.items()]) if team_wins else "Completed"

        embed = discord.Embed(
            title=f"🏆 {series_title} - Final Summary",
            description=(
                f"**Series Result:** {record_str}\n"
                f"**Total Maps:** {aggregated.get('total_maps')}\n"
                f"🌟 **Series MVP:** **{mvp.get('name')}** (K/D: `{mvp.get('kd'):.2f}`, Avg Kills: `{mvp.get('avg_kills')}`, Total Dmg: `{mvp.get('damage'):,}`)\n\n"
                f"See the attached **infographic card** and **CSV spreadsheet** below!"
            ),
            color=discord.Color.gold()
        )

        # Leader highlights
        top_k = aggregated.get("top_kills")
        top_dmg = aggregated.get("top_damage")
        top_kd = aggregated.get("top_kd")

        highlights = []
        if top_kd:
            highlights.append(f"🎯 **Best K/D:** {top_kd.get('name')} (`{top_kd.get('kd'):.2f}`)")
        if top_k:
            highlights.append(f"💥 **Most Kills:** {top_k.get('name')} (`{top_k.get('kills')}` total)")
        if top_dmg:
            highlights.append(f"💣 **Most Damage:** {top_dmg.get('name')} (`{top_dmg.get('damage'):,}`)")

        if highlights:
            embed.add_field(name="Performance Highlights", value="\n".join(highlights), inline=False)

        # Quick text overview table
        overview_lines = ["```", f"{'Player':<15} {'Maps':<5} {'K/D':<6} {'Avg K':<6} {'Total Dmg':<9}", "-" * 45]
        for p in aggregated.get("players", [])[:10]:
            overview_lines.append(f"{p['name'][:14]:<15} {p['maps_played']:<5} {p['kd']:<6.2f} {p['avg_kills']:<6.1f} {p['damage']:<9,}")
        overview_lines.append("```")
        embed.add_field(name="Top Player Averages", value="\n".join(overview_lines), inline=False)

        embed.set_image(url="attachment://cod_match_summary.png")
        embed.set_footer(text="Upload more maps with /upload_map or start a new series with /start_series")

        await interaction.followup.send(embed=embed, files=[graphic_file, csv_file])

    except Exception as e:
        logger.exception("Error in series_summary")
        await interaction.followup.send(f"❌ Failed to generate series summary: {str(e)}")


@bot.tree.command(name="series_status", description="Check the status of the current series and list recorded maps")
async def series_status(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in active_series:
        await interaction.response.send_message("ℹ️ No active series in this channel. Start one with `/start_series`.", ephemeral=True)
        return

    series = active_series[channel_id]
    maps = series.get("maps", [])

    embed = discord.Embed(
        title=f"📋 Active Series: {series.get('title')}",
        description=f"⚔️ **{series.get('team1')}** vs **{series.get('team2')}** (Best of {series.get('best_of')})",
        color=discord.Color.blue()
    )

    if not maps:
        embed.add_field(name="Recorded Maps", value="*No maps uploaded yet. Use `/upload_map` to add one!*")
    else:
        map_lines = []
        for m in maps:
            map_lines.append(f"• **Map {m['map_number']}**: {m['map_name']} ({m['game_mode']}) - {m['team1_name']} {m['team1_score']} vs {m['team2_score']} {m['team2_name']} ({len(m.get('players', []))} players)")
        embed.add_field(name=f"Recorded Maps ({len(maps)}/{series.get('best_of')})", value="\n".join(map_lines), inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="edit_stat", description="Manually correct a player stat on a map if OCR misread a number")
@app_commands.describe(
    player_name="Player gamertag to edit",
    stat_name="Stat to change (kills, deaths, assists, damage, score)",
    new_value="The correct numeric value",
    map_number="Map number to edit (defaults to latest map)"
)
async def edit_stat(
    interaction: discord.Interaction,
    player_name: str,
    stat_name: str,
    new_value: int,
    map_number: Optional[int] = None
):
    channel_id = interaction.channel_id
    if channel_id not in active_series or not active_series[channel_id]["maps"]:
        await interaction.response.send_message("⚠️ No active series or maps to edit in this channel.", ephemeral=True)
        return

    series = active_series[channel_id]
    target_map_num = map_number or series["maps"][-1]["map_number"]
    target_map = next((m for m in series["maps"] if m["map_number"] == target_map_num), None)

    if not target_map:
        await interaction.response.send_message(f"⚠️ Map {target_map_num} not found in current series.", ephemeral=True)
        return

    stat_lower = stat_name.lower().strip()
    valid_stats = ["kills", "deaths", "assists", "damage", "score"]
    if stat_lower not in valid_stats:
        await interaction.response.send_message(f"⚠️ Invalid stat '{stat_name}'. Choose from: {', '.join(valid_stats)}", ephemeral=True)
        return

    player = next((p for p in target_map.get("players", []) if p["name"].lower() == player_name.lower()), None)
    if not player:
        # Check partial match
        player = next((p for p in target_map.get("players", []) if player_name.lower() in p["name"].lower()), None)

    if not player:
        await interaction.response.send_message(f"⚠️ Player '{player_name}' not found on Map {target_map_num}.", ephemeral=True)
        return

    old_val = player.get(stat_lower, 0)
    player[stat_lower] = int(new_value)
    series_storage.save(channel_id, series)

    await interaction.response.send_message(
        f"✅ Updated **{player['name']}** on Map {target_map_num}: `{stat_lower}` changed from **{old_val}** to **{new_value}**."
    )


@bot.tree.command(name="remove_map", description="Remove a specific map from the active series")
@app_commands.describe(map_number="The map number to delete")
async def remove_map(interaction: discord.Interaction, map_number: int):
    channel_id = interaction.channel_id
    if channel_id not in active_series:
        await interaction.response.send_message("⚠️ No active series in this channel.", ephemeral=True)
        return

    series = active_series[channel_id]
    before_count = len(series["maps"])
    series["maps"] = [m for m in series["maps"] if m["map_number"] != map_number]

    if len(series["maps"]) < before_count:
        series_storage.save(channel_id, series)
        await interaction.response.send_message(f"🗑️ Removed Map {map_number} from the series.")
    else:
        await interaction.response.send_message(f"⚠️ Map {map_number} was not found.")


@bot.tree.command(name="reset_series", description="Reset and clear the active series in this channel")
async def reset_series(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id in active_series:
        del active_series[channel_id]
        series_storage.delete(channel_id)
        await interaction.response.send_message("🧹 Series data cleared. You can start a fresh series with `/start_series`.")
    else:
        await interaction.response.send_message("ℹ️ No active series was running in this channel.")


@bot.tree.command(name="set_engine", description="Switch between Gemini AI Vision and Local OCR")
@app_commands.describe(engine="Choose 'gemini' for high-accuracy AI Vision or 'ocr' for local OCR")
@app_commands.choices(engine=[
    app_commands.Choice(name="Gemini 3.8 Flash AI Vision (Recommended - Highly accurate)", value="gemini"),
    app_commands.Choice(name="Local OCR / Tesseract (Fallback)", value="ocr")
])
async def set_engine(interaction: discord.Interaction, engine: app_commands.Choice[str]):
    channel_engine_preference[interaction.channel_id] = engine.value
    await interaction.response.send_message(f"⚙️ Scoreboard parsing engine set to: **{engine.name}**")


@bot.tree.command(name="cod_help", description="Show detailed guide and commands for the Call of Duty Stats Bot")
async def cod_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Call of Duty League Stats Bot - User Guide",
        description=(
            "Tired of averaging scoreboard stats by hand after your Call of Duty matches? "
            "This bot reads scoreboard screenshots, tracks stats across 3+ maps, and automatically calculates "
            "all player totals, averages, K/D ratios, damage, and MVP standings!\n"
        ),
        color=discord.Color.brand_green()
    )

    embed.add_field(
        name="1️⃣ Start a Match Series",
        value="`/start_series [name] [team1] [team2] [best_of]`\nInitializes a multi-map match session (e.g. Best of 3 or 5).",
        inline=False
    )
    embed.add_field(
        name="2️⃣ Upload Game Screenshots",
        value="`/upload_map [screenshot] [map_number]`\nUpload the end-game scoreboard after each map. The bot parses player names, kills, deaths, assists, and damage instantly.",
        inline=False
    )
    embed.add_field(
        name="3️⃣ Generate Series Summary",
        value="`/series_summary`\nCalculates the full series stats! Generates a **broadcast-quality infographic card** and a **CSV file** ready for Google Sheets or Excel.",
        inline=False
    )
    embed.add_field(
        name="🔍 Single Game Quick Scan",
        value="`/quick_scan [screenshot]`\nInstantly scan and display stats for a single game without starting a series.",
        inline=False
    )
    embed.add_field(
        name="✏️ Corrections & Editing",
        value="`/edit_stat [player] [stat] [value]` - Fix any OCR typo in seconds.\n`/remove_map [map_number]` - Remove an incorrectly uploaded map.",
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings",
        value="`/set_engine` - Switch between Gemini AI Vision and Local OCR.\n`/series_status` - View currently uploaded maps.",
        inline=False
    )

    embed.set_footer(text="Built for Call of Duty: Black Ops 6 & Modern Warfare III")
    await interaction.response.send_message(embed=embed)


# ==========================================
# RUN BOT
# ==========================================

def main():
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        print("\n" + "=" * 60)
        print("⚠️ ERROR: DISCORD_BOT_TOKEN not found!")
        print("Please create a .env file and set your DISCORD_BOT_TOKEN.")
        print("Example .env:")
        print("  DISCORD_BOT_TOKEN=your_token_here")
        print("  GEMINI_API_KEY=your_gemini_api_key_here")
        print("=" * 60 + "\n")
        sys.exit(1)

    print("Starting Call of Duty League Bot...")
    bot.run(token)


if __name__ == "__main__":
    main()
