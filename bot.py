"""
Call of Duty League Discord Bot
Automatically extracts player stats from scoreboard screenshots,
aggregates kills/deaths/assists/damage/score across maps, calculates averages,
and generates infographics and CSV exports.
"""
import asyncio
import io
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from csv_exporter import CSVExporter
from extractor import ScoreboardExtractor
from image_generator import GraphicGenerator
from safety import clean_untrusted_text, normalize_api_key, redact_secrets
from series_storage import SeriesStorage, resolve_database_path
from stats_manager import StatsManager

load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("discord").setLevel(logging.WARNING)


class _HideUnusedVoiceWarnings(logging.Filter):
    """This bot never joins voice, so missing voice libraries are not a failure."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()


logging.getLogger("discord.client").addFilter(_HideUnusedVoiceWarnings())
logger = logging.getLogger("cod_bot")

SERIES_DB_PATH = resolve_database_path(
    os.getenv("SERIES_DB_PATH"),
    Path(__file__).resolve().parent,
)
MAX_MAPS = 20
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
STAT_CHOICES = [
    app_commands.Choice(name="Kills", value="kills"),
    app_commands.Choice(name="Deaths", value="deaths"),
    app_commands.Choice(name="Assists", value="assists"),
    app_commands.Choice(name="Damage", value="damage"),
    app_commands.Choice(name="Score", value="score"),
]

# Slash commands carry their own arguments. Message Content is a privileged
# intent, and requesting it makes login fail when the portal toggle is off.
intents = discord.Intents.default()
intents.message_content = False
intents.members = False
intents.presences = False

bot = commands.Bot(
    command_prefix="!cod ",
    intents=intents,
    help_command=None,
    allowed_mentions=discord.AllowedMentions.none(),
)

try:
    series_storage = SeriesStorage(SERIES_DB_PATH)
    active_series: Dict[int, Dict[str, Any]] = series_storage.load_all()
    logger.info("Restored %s active series from %s", len(active_series), SERIES_DB_PATH)
except Exception:
    logger.exception("Could not open the series database at %s", SERIES_DB_PATH)
    raise

channel_engine_preference: Dict[int, str] = {}
_series_locks: Dict[int, asyncio.Lock] = {}
_last_extraction: Dict[int, float] = {}
_extractor: Optional[ScoreboardExtractor] = None
_last_sync_attempt = 0.0


def configured_token() -> Optional[str]:
    token = (os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN") or "").strip()
    if not token or token in {"your_discord_bot_token_here", "your_token_here"}:
        return None
    return token


def default_engine() -> str:
    value = (os.getenv("DEFAULT_ENGINE") or "gemini").strip().lower()
    return value if value in {"gemini", "ocr"} else "gemini"


def engine_for(channel_id: int) -> str:
    return channel_engine_preference.get(channel_id, default_engine())


def get_extractor() -> ScoreboardExtractor:
    global _extractor
    key = normalize_api_key(os.getenv("GEMINI_API_KEY"))
    if _extractor is None or _extractor.api_key != key:
        _extractor = ScoreboardExtractor(gemini_api_key=key)
    return _extractor


def lock_for(channel_id: int) -> asyncio.Lock:
    lock = _series_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _series_locks[channel_id] = lock
    return lock


def extraction_cooldown_remaining(user_id: int) -> float:
    try:
        cooldown = float(os.getenv("EXTRACT_COOLDOWN_SECONDS", "5"))
    except ValueError:
        cooldown = 5.0
    if cooldown <= 0:
        return 0.0
    remaining = cooldown - (time.monotonic() - _last_extraction.get(user_id, 0.0))
    return remaining if remaining > 0 else 0.0


def mark_extraction(user_id: int) -> None:
    _last_extraction[user_id] = time.monotonic()


def series_maps(series: Dict[str, Any]) -> List[Dict[str, Any]]:
    maps = series.get("maps")
    if not isinstance(maps, list):
        series["maps"] = []
        return series["maps"]
    return maps


def actor_can_modify(user_id: Optional[int], manage_messages: bool, series: Dict[str, Any]) -> bool:
    """Series owner or a channel mod can edit. Older saved series have no owner id."""
    owner_id = series.get("created_by_id")
    if owner_id is None:
        return True
    try:
        return int(owner_id) == user_id or manage_messages
    except (TypeError, ValueError):
        return manage_messages


def user_can_modify(interaction: discord.Interaction, series: Dict[str, Any]) -> bool:
    user = getattr(interaction, "user", None)
    user_id = getattr(user, "id", None)
    permissions = getattr(interaction, "permissions", None)
    manage_messages = bool(permissions and getattr(permissions, "manage_messages", False))
    return actor_can_modify(user_id, manage_messages, series)


def attachment_problem(filename: str, content_type: Optional[str], size: Optional[int]) -> Optional[str]:
    kind = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()
    looks_like_image = kind in ALLOWED_IMAGE_TYPES or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
    if not looks_like_image:
        return "Upload a PNG, JPG, WEBP, or GIF screenshot."
    if size and size > 8 * 1024 * 1024:
        return "That file is too large. Upload a screenshot under 8 MB."
    return None


def persist_series(channel_id: int, series: Dict[str, Any]) -> bool:
    try:
        series_storage.save(channel_id, series)
        return True
    except sqlite3.Error:
        logger.exception("Could not save series for channel %s", channel_id)
        return False


def fit_embed(text: str, limit: int = 1024) -> str:
    cleaned = (text or "").strip() or "—"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def format_players_table(players: List[Dict[str, Any]]) -> str:
    """Format players into a clean monospaced Discord table."""
    lines = ["```", f"{'Player':<16} {'Team':<10} {'K':<4} {'D':<4} {'+/-':<5} {'K/D':<6} {'Dmg':<6}", "-" * 55]
    for player in players[:8]:
        name = clean_untrusted_text(player.get("name"), 15) or "Player"
        team = clean_untrusted_text(player.get("team"), 9) or "-"
        kills = int(player.get("kills") or 0)
        deaths = int(player.get("deaths") or 0)
        diff = kills - deaths
        diff_text = f"+{diff}" if diff > 0 else str(diff)
        kd = StatsManager.calculate_kd(kills, deaths)
        damage = int(player.get("damage") or 0)
        lines.append(f"{name:<16} {team:<10} {kills:<4} {deaths:<4} {diff_text:<5} {kd:<6.2f} {damage:<6}")
    lines.append("```")
    return "\n".join(lines)


def number_text(value, digits: Optional[int] = None) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0" if digits is None else f"{0:.{digits}f}"
    if digits is None:
        return str(int(number))
    return f"{number:.{digits}f}"


async def reply(interaction: discord.Interaction, content: Optional[str] = None, **kwargs):
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


async def refuse(interaction: discord.Interaction, content: str):
    try:
        await reply(interaction, content, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Could not send an error reply")


@bot.event
async def on_ready():
    global _last_sync_attempt
    logger.info("Bot logged in as %s (%s)", bot.user, getattr(bot.user, "id", "?"))
    if os.getenv("SYNC_COMMANDS", "true").strip().lower() in {"0", "false", "no"}:
        logger.info("SYNC_COMMANDS is off, so slash commands were not synced.")
        return
    now = time.monotonic()
    if now - _last_sync_attempt < 600:
        logger.info("Slash commands were synced recently; skipping.")
        return
    _last_sync_attempt = now
    try:
        guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_raw:
            guild = discord.Object(id=int(guild_raw))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands to guild %s.", len(synced), guild_raw)
        else:
            synced = await bot.tree.sync()
            logger.info("Synced %s global slash commands.", len(synced))
    except (discord.HTTPException, ValueError) as exc:
        logger.error("Failed to sync slash commands: %s", redact_secrets(str(exc)))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error("Command failed: %s", redact_secrets(str(error), [os.getenv("GEMINI_API_KEY") or ""]))
    await refuse(interaction, "Something went wrong while running that command. The details were logged.")


def require_channel(interaction: discord.Interaction) -> Optional[int]:
    return interaction.channel_id


@bot.tree.command(name="start_series", description="Start a new multi-map Call of Duty match series in this channel")
@app_commands.describe(
    name="Series name or title (e.g. CDL Week 1)",
    team1="Team 1 Name (e.g. OpTic)",
    team2="Team 2 Name (e.g. FaZe)",
    best_of="Best of X maps (e.g. 3 or 5)",
)
async def start_series(
    interaction: discord.Interaction,
    name: str = "Call of Duty League Match",
    team1: str = "Team 1",
    team2: str = "Team 2",
    best_of: int = 3,
):
    channel_id = require_channel(interaction)
    if channel_id is None:
        await refuse(interaction, "Use this command in a channel.")
        return
    if not 1 <= best_of <= 9:
        await refuse(interaction, "Best of must be between 1 and 9.")
        return

    title = clean_untrusted_text(name, 80) or "Call of Duty League Match"
    team1_name = clean_untrusted_text(team1, 32) or "Team 1"
    team2_name = clean_untrusted_text(team2, 32) or "Team 2"
    async with lock_for(channel_id):
        existing = active_series.get(channel_id)
        if existing and not user_can_modify(interaction, existing):
            await refuse(
                interaction,
                "A series is already running here. The person who started it, or someone with Manage Messages, can reset it.",
            )
            return
        active_series[channel_id] = {
            "title": title,
            "team1": team1_name,
            "team2": team2_name,
            "best_of": best_of,
            "maps": [],
            "created_by": clean_untrusted_text(getattr(interaction.user, "display_name", "Unknown"), 32),
            "created_by_id": interaction.user.id,
        }
        saved = persist_series(channel_id, active_series[channel_id])

    embed = discord.Embed(
        title="Series tracking started",
        description=fit_embed(
            f"**{title}**\n"
            f"**{team1_name}** vs **{team2_name}** (Best of {best_of})\n\n"
            "Upload an end-game screenshot with `/upload_map` after each map.\n"
            "When the series is done, `/series_summary` builds the averages, graphic, and CSV.",
            4096,
        ),
        color=discord.Color.blue(),
    )
    if not saved:
        embed.add_field(name="Not saved", value="The series is running, but the database write failed. It may disappear after a restart.", inline=False)
    embed.set_footer(text="Call of Duty League Bot")
    await reply(interaction, embed=embed)


@bot.tree.command(name="upload_map", description="Upload a scoreboard screenshot for the current series")
@app_commands.describe(
    screenshot="Screenshot image of the scoreboard",
    map_number="Map number in the series (e.g. 1, 2, 3)",
    map_name="Optional map name (e.g. Skyline, Babylon, Karachi)",
    game_mode="Optional game mode (e.g. Hardpoint, SnD, Control)",
)
async def upload_map(
    interaction: discord.Interaction,
    screenshot: discord.Attachment,
    map_number: Optional[int] = None,
    map_name: Optional[str] = None,
    game_mode: Optional[str] = None,
):
    channel_id = require_channel(interaction)
    if channel_id is None:
        await refuse(interaction, "Use this command in a channel.")
        return
    if channel_id not in active_series:
        await refuse(interaction, "No active series in this channel. Start one with `/start_series`, or use `/quick_scan` for a single screenshot.")
        return
    problem = attachment_problem(screenshot.filename, screenshot.content_type, screenshot.size)
    if problem:
        await refuse(interaction, problem)
        return
    if map_number is not None and not 1 <= map_number <= MAX_MAPS:
        await refuse(interaction, f"Map number must be between 1 and {MAX_MAPS}.")
        return
    remaining = extraction_cooldown_remaining(interaction.user.id)
    if remaining > 0:
        await refuse(interaction, f"Wait {remaining:.0f}s before uploading another screenshot.")
        return
    mark_extraction(interaction.user.id)

    await interaction.response.defer(thinking=True)
    try:
        image_bytes = await screenshot.read()
        result = await get_extractor().extract_from_bytes(
            image_bytes,
            preferred_engine=engine_for(channel_id),
        )
        if not result.get("success"):
            await refuse(interaction, f"Could not parse that screenshot. {result.get('error') or 'Try a clearer image.'}")
            return

        async with lock_for(channel_id):
            series = active_series.get(channel_id)
            if series is None:
                await refuse(interaction, "This series was reset while the screenshot was being read.")
                return
            maps = series_maps(series)
            current_map_num = map_number or (len(maps) + 1)
            existing_idx = next((index for index, item in enumerate(maps) if isinstance(item, dict) and item.get("map_number") == current_map_num), None)
            if existing_idx is None and len(maps) >= MAX_MAPS:
                await refuse(interaction, f"This series already has {MAX_MAPS} maps. Remove one with `/remove_map`.")
                return

            detected_map = clean_untrusted_text(map_name, 32) or result.get("map_name") or f"Map {current_map_num}"
            detected_mode = clean_untrusted_text(game_mode, 32) or result.get("game_mode") or "Multiplayer"
            map_entry = {
                "map_number": current_map_num,
                "map_name": detected_map,
                "game_mode": detected_mode,
                "team1_name": result.get("team1_name") or series.get("team1", "Team 1"),
                "team2_name": result.get("team2_name") or series.get("team2", "Team 2"),
                "team1_score": result.get("team1_score", 0),
                "team2_score": result.get("team2_score", 0),
                "players": result.get("players", []),
            }
            if existing_idx is not None:
                maps[existing_idx] = map_entry
                action_text = f"Updated Map {current_map_num}"
            else:
                maps.append(map_entry)
                maps.sort(key=lambda item: item.get("map_number", 0) if isinstance(item, dict) else 0)
                action_text = f"Added Map {current_map_num}"
            saved = persist_series(channel_id, series)
            recorded = len(maps)
            best_of = series.get("best_of", 3)

        embed = discord.Embed(
            title=fit_embed(f"{action_text}: {detected_map} ({detected_mode})", 256),
            description=fit_embed(
                f"**Score:** {map_entry['team1_name']} **{map_entry['team1_score']}** - **{map_entry['team2_score']}** {map_entry['team2_name']}\n"
                f"**Extracted {len(map_entry['players'])} players** using `{result.get('engine', 'unknown')}`.\n"
                f"Progress: **{recorded} / {best_of}** maps recorded.",
                4096,
            ),
            color=discord.Color.green(),
        )
        if map_entry["players"]:
            embed.add_field(name="Scoreboard preview", value=fit_embed(format_players_table(map_entry["players"])), inline=False)
        if result.get("warning"):
            embed.add_field(name="Check these numbers", value=fit_embed(result["warning"]), inline=False)
        if not saved:
            embed.add_field(name="Not saved", value="The map is in memory, but the database write failed.", inline=False)
        embed.set_footer(text="Upload the next map with /upload_map, or finish with /series_summary")
        await reply(interaction, embed=embed)
    except Exception:
        logger.exception("Error processing screenshot upload")
        await refuse(interaction, "Could not process that screenshot.")


@bot.tree.command(name="quick_scan", description="Scan a single scoreboard screenshot without starting a series")
@app_commands.describe(screenshot="Scoreboard screenshot image")
async def quick_scan(interaction: discord.Interaction, screenshot: discord.Attachment):
    channel_id = require_channel(interaction)
    problem = attachment_problem(screenshot.filename, screenshot.content_type, screenshot.size)
    if problem:
        await refuse(interaction, problem)
        return
    remaining = extraction_cooldown_remaining(interaction.user.id)
    if remaining > 0:
        await refuse(interaction, f"Wait {remaining:.0f}s before scanning another screenshot.")
        return
    mark_extraction(interaction.user.id)
    await interaction.response.defer(thinking=True)

    try:
        image_bytes = await screenshot.read()
        result = await get_extractor().extract_from_bytes(
            image_bytes,
            preferred_engine=engine_for(channel_id) if channel_id is not None else default_engine(),
        )
        if not result.get("success"):
            await refuse(interaction, f"Could not parse that screenshot. {result.get('error') or ''}".strip())
            return
        players = result.get("players") or []
        if not players:
            await refuse(interaction, "No players were detected on this scoreboard.")
            return

        map_data = [{
            "map_number": 1,
            "map_name": result.get("map_name", "Game 1"),
            "game_mode": result.get("game_mode", "Multiplayer"),
            "team1_name": result.get("team1_name", "Team 1"),
            "team2_name": result.get("team2_name", "Team 2"),
            "team1_score": result.get("team1_score", 0),
            "team2_score": result.get("team2_score", 0),
            "players": players,
        }]
        aggregated = StatsManager.aggregate_series_stats(map_data)
        mvp = aggregated.get("mvp") or {}
        embed = discord.Embed(
            title=fit_embed(f"Scoreboard analysis: {result.get('map_name', 'Game 1')}", 256),
            description=fit_embed(
                f"**Mode:** {result.get('game_mode', 'Multiplayer')}  |  "
                f"**Score:** {result.get('team1_name', 'Team 1')} {result.get('team1_score', 0)} - "
                f"{result.get('team2_score', 0)} {result.get('team2_name', 'Team 2')}\n"
                f"**MVP:** **{clean_untrusted_text(mvp.get('name'), 32) or 'Unknown'}** "
                f"(K/D: {number_text(mvp.get('kd'), 2)}, Kills: {mvp.get('kills', 0)}, Dmg: {int(mvp.get('damage') or 0):,})",
                4096,
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Stats table", value=fit_embed(format_players_table(players)), inline=False)
        if result.get("warning"):
            embed.add_field(name="Check these numbers", value=fit_embed(result["warning"]), inline=False)
        embed.set_footer(text=f"Engine: {result.get('engine', 'gemini')}")
        await reply(interaction, embed=embed)
    except Exception:
        logger.exception("Error in quick_scan")
        await refuse(interaction, "Could not process that screenshot.")


@bot.tree.command(name="series_summary", description="Calculate consolidated stats, averages, MVP card, and CSV for the series")
async def series_summary(interaction: discord.Interaction):
    channel_id = require_channel(interaction)
    if channel_id is None or channel_id not in active_series:
        await refuse(interaction, "No active series in this channel. Start one with `/start_series`.")
        return
    series = active_series[channel_id]
    if not series_maps(series):
        await refuse(interaction, "No maps have been uploaded yet. Use `/upload_map` to add one.")
        return

    await interaction.response.defer(thinking=True)
    try:
        aggregated = StatsManager.aggregate_series_stats(series["maps"])
        players = aggregated.get("players") or []
        if not players:
            await refuse(interaction, "Those maps don't contain any player rows. Upload the scoreboards again.")
            return

        series_title = series.get("title") or "Call of Duty League Match"
        image_buffer = GraphicGenerator.generate_series_card(aggregated, series_title=series_title)
        graphic_file = discord.File(image_buffer, filename="cod_match_summary.png")
        csv_stream = CSVExporter.generate_series_csv(aggregated, series_title=series_title)
        csv_bytes = io.BytesIO(csv_stream.getvalue().encode("utf-8-sig"))
        csv_file = discord.File(csv_bytes, filename=f"cod_series_{channel_id}.csv")

        mvp = aggregated.get("mvp") or players[0]
        team_wins = aggregated.get("team_wins") or {}
        record = " vs ".join(f"**{clean_untrusted_text(team, 32)}** ({wins}W)" for team, wins in team_wins.items())
        embed = discord.Embed(
            title=fit_embed(f"{series_title} — final summary", 256),
            description=fit_embed(
                f"**Series result:** {record or 'Completed'}\n"
                f"**Total maps:** {aggregated.get('total_maps')}\n"
                f"**Series MVP:** **{clean_untrusted_text(mvp.get('name'), 32)}** "
                f"(K/D: `{number_text(mvp.get('kd'), 2)}`, Avg kills: `{mvp.get('avg_kills', 0)}`, "
                f"Total damage: `{int(mvp.get('damage') or 0):,}`)\n\n"
                "The infographic and CSV are attached.",
                4096,
            ),
            color=discord.Color.gold(),
        )

        highlights = []
        top_kd = aggregated.get("top_kd")
        top_kills = aggregated.get("top_kills")
        top_damage = aggregated.get("top_damage")
        if top_kd:
            highlights.append(f"**Best K/D:** {clean_untrusted_text(top_kd.get('name'), 32)} (`{number_text(top_kd.get('kd'), 2)}`)")
        if top_kills:
            highlights.append(f"**Most kills:** {clean_untrusted_text(top_kills.get('name'), 32)} (`{top_kills.get('kills')}`)")
        if top_damage:
            highlights.append(f"**Most damage:** {clean_untrusted_text(top_damage.get('name'), 32)} (`{int(top_damage.get('damage') or 0):,}`)")
        if highlights:
            embed.add_field(name="Performance highlights", value=fit_embed("\n".join(highlights)), inline=False)

        podium = ["1.", "2.", "3."]
        top_lines = []
        for place, player in enumerate(aggregated.get("top_players") or [], start=1):
            if place > len(podium):
                break
            top_lines.append(
                f"{podium[place - 1]} **{clean_untrusted_text(player.get('name'), 32)}** "
                f"({clean_untrusted_text(player.get('team'), 24)}) — "
                f"Rating `{player.get('mvp_rating', 0)}` | K/D `{number_text(player.get('kd'), 2)}` | "
                f"Kills `{player.get('kills', 0)}` | Damage `{int(player.get('damage') or 0):,}`"
            )
        if top_lines:
            embed.add_field(name="Top 3 players", value=fit_embed("\n".join(top_lines)), inline=False)

        overview = ["```", f"{'Player':<15} {'Maps':<5} {'K/D':<6} {'Avg K':<6} {'Total Dmg':<9}", "-" * 45]
        for player in players[:10]:
            name = clean_untrusted_text(player.get("name"), 14)
            overview.append(
                f"{name:<15} {player.get('maps_played', 0):<5} {number_text(player.get('kd'), 2):<6} "
                f"{float(player.get('avg_kills') or 0):<6.1f} {int(player.get('damage') or 0):<9,}"
            )
        overview.append("```")
        embed.add_field(name="Player averages", value=fit_embed("\n".join(overview)), inline=False)
        embed.set_image(url="attachment://cod_match_summary.png")
        embed.set_footer(text="Upload more maps with /upload_map, or start over with /start_series")
        await reply(interaction, embed=embed, files=[graphic_file, csv_file])
    except Exception:
        logger.exception("Error in series_summary")
        await refuse(interaction, "Could not generate the series summary.")


@bot.tree.command(name="series_status", description="Check the status of the current series and list recorded maps")
async def series_status(interaction: discord.Interaction):
    channel_id = require_channel(interaction)
    if channel_id is None or channel_id not in active_series:
        await refuse(interaction, "No active series in this channel. Start one with `/start_series`.")
        return
    series = active_series[channel_id]
    maps = [item for item in series_maps(series) if isinstance(item, dict)]
    embed = discord.Embed(
        title=fit_embed(f"Active series: {series.get('title') or 'Untitled'}", 256),
        description=fit_embed(
            f"**{series.get('team1')}** vs **{series.get('team2')}** (Best of {series.get('best_of')})",
            4096,
        ),
        color=discord.Color.blue(),
    )
    if not maps:
        embed.add_field(name="Recorded maps", value="No maps uploaded yet. Use `/upload_map` to add one.")
    else:
        lines = []
        hidden = 0
        for item in maps:
            line = (
                f"• **Map {item.get('map_number')}**: {clean_untrusted_text(item.get('map_name'), 32)} "
                f"({clean_untrusted_text(item.get('game_mode'), 24)}) — "
                f"{clean_untrusted_text(item.get('team1_name'), 24)} {item.get('team1_score', 0)} vs "
                f"{item.get('team2_score', 0)} {clean_untrusted_text(item.get('team2_name'), 24)} "
                f"({len(item.get('players') or [])} players)"
            )
            if sum(len(existing) for existing in lines) + len(line) > 900:
                hidden = len(maps) - len(lines)
                break
            lines.append(line)
        if hidden:
            lines.append(f"…and {hidden} more.")
        embed.add_field(
            name=f"Recorded maps ({len(maps)}/{series.get('best_of')})",
            value=fit_embed("\n".join(lines)),
            inline=False,
        )
    await reply(interaction, embed=embed)


@bot.tree.command(name="edit_stat", description="Manually correct a player stat on a map if OCR misread a number")
@app_commands.describe(
    player_name="Player gamertag to edit",
    stat_name="Stat to change",
    new_value="The correct numeric value",
    map_number="Map number to edit (defaults to latest map)",
)
@app_commands.choices(stat_name=STAT_CHOICES)
async def edit_stat(
    interaction: discord.Interaction,
    player_name: str,
    stat_name: app_commands.Choice[str],
    new_value: int,
    map_number: Optional[int] = None,
):
    channel_id = require_channel(interaction)
    if channel_id is None or channel_id not in active_series or not series_maps(active_series[channel_id]):
        await refuse(interaction, "No active series or maps to edit in this channel.")
        return
    if not 0 <= new_value <= 1_000_000:
        await refuse(interaction, "The new value must be between 0 and 1,000,000.")
        return
    if map_number is not None and not 1 <= map_number <= MAX_MAPS:
        await refuse(interaction, f"Map number must be between 1 and {MAX_MAPS}.")
        return

    async with lock_for(channel_id):
        series = active_series[channel_id]
        if not user_can_modify(interaction, series):
            await refuse(interaction, "Only the person who started this series, or someone with Manage Messages, can edit it.")
            return
        maps = [item for item in series_maps(series) if isinstance(item, dict)]
        target_map_num = map_number or maps[-1].get("map_number")
        target_map = next((item for item in maps if item.get("map_number") == target_map_num), None)
        if target_map is None:
            await refuse(interaction, f"Map {target_map_num} is not in this series.")
            return
        wanted = player_name.strip().lower()
        roster = [player for player in target_map.get("players") or [] if isinstance(player, dict)]
        matches = [player for player in roster if str(player.get("name", "")).lower() == wanted]
        if not matches:
            matches = [player for player in roster if wanted and wanted in str(player.get("name", "")).lower()]
        if len(matches) != 1:
            if len(matches) > 1:
                names = ", ".join(clean_untrusted_text(player.get("name"), 32) for player in matches[:8])
                await refuse(interaction, f"That name matches more than one player: {names}")
            else:
                await refuse(interaction, f"Player '{clean_untrusted_text(player_name, 32)}' is not on map {target_map_num}.")
            return
        player = matches[0]
        stat_key = stat_name.value
        old_value = player.get(stat_key, 0)
        player[stat_key] = int(new_value)
        saved = persist_series(channel_id, series)

    message = (
        f"Updated **{clean_untrusted_text(player.get('name'), 32)}** on map {target_map_num}: "
        f"`{stat_key}` changed from **{old_value}** to **{new_value}**."
    )
    if not saved:
        message += " The change is in memory, but the database write failed."
    await reply(interaction, message)


@bot.tree.command(name="remove_map", description="Remove a specific map from the active series")
@app_commands.describe(map_number="The map number to delete")
async def remove_map(interaction: discord.Interaction, map_number: int):
    channel_id = require_channel(interaction)
    if channel_id is None or channel_id not in active_series:
        await refuse(interaction, "No active series in this channel.")
        return
    async with lock_for(channel_id):
        series = active_series[channel_id]
        if not user_can_modify(interaction, series):
            await refuse(interaction, "Only the person who started this series, or someone with Manage Messages, can remove a map.")
            return
        maps = series_maps(series)
        kept = [item for item in maps if not (isinstance(item, dict) and item.get("map_number") == map_number)]
        if len(kept) == len(maps):
            await refuse(interaction, f"Map {map_number} is not in this series.")
            return
        series["maps"] = kept
        saved = persist_series(channel_id, series)
    message = f"Removed map {map_number} from the series."
    if not saved:
        message += " The change is in memory, but the database write failed."
    await reply(interaction, message)


@bot.tree.command(name="reset_series", description="Reset and clear the active series in this channel")
async def reset_series(interaction: discord.Interaction):
    channel_id = require_channel(interaction)
    if channel_id is None or channel_id not in active_series:
        await reply(interaction, "No active series was running in this channel.")
        return
    async with lock_for(channel_id):
        series = active_series.get(channel_id)
        if series is None:
            await reply(interaction, "No active series was running in this channel.")
            return
        if not user_can_modify(interaction, series):
            await refuse(interaction, "Only the person who started this series, or someone with Manage Messages, can reset it.")
            return
        try:
            series_storage.delete(channel_id)
        except sqlite3.Error:
            logger.exception("Could not delete series for channel %s", channel_id)
            await refuse(interaction, "Could not clear the saved series. Nothing was removed.")
            return
        active_series.pop(channel_id, None)
    await reply(interaction, "Series data cleared. Start a fresh one with `/start_series`.")


@bot.tree.command(name="set_engine", description="Switch between Gemini AI Vision and local OCR")
@app_commands.describe(engine="Choose Gemini for accurate vision, or local OCR as a fallback")
@app_commands.choices(engine=[
    app_commands.Choice(name="Gemini Flash (recommended)", value="gemini"),
    app_commands.Choice(name="Local OCR / Tesseract (fallback)", value="ocr"),
])
async def set_engine(interaction: discord.Interaction, engine: app_commands.Choice[str]):
    channel_id = require_channel(interaction)
    if channel_id is None:
        await refuse(interaction, "Use this command in a channel.")
        return
    if engine.value not in {"gemini", "ocr"}:
        await refuse(interaction, "Choose Gemini or local OCR.")
        return
    channel_engine_preference[channel_id] = engine.value
    await reply(interaction, f"Scoreboard parsing engine set to **{clean_untrusted_text(engine.name, 60)}**.")


@bot.tree.command(name="cod_help", description="Show how to use the Call of Duty stats bot")
async def cod_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Call of Duty League stats bot",
        description=(
            "Upload end-game scoreboard screenshots. The bot reads kills, deaths, assists, and damage, "
            "tracks them across a series, and calculates totals, averages, K/D, and an MVP."
        ),
        color=discord.Color.brand_green(),
    )
    embed.add_field(
        name="1. Start a series",
        value="`/start_series` with a name, two teams, and best-of number.",
        inline=False,
    )
    embed.add_field(
        name="2. Upload each scoreboard",
        value="`/upload_map` with the screenshot. Add a map number to replace one.",
        inline=False,
    )
    embed.add_field(
        name="3. Finish",
        value="`/series_summary` posts the infographic and a CSV file.",
        inline=False,
    )
    embed.add_field(
        name="One screenshot only",
        value="`/quick_scan` reads a single scoreboard without starting a series.",
        inline=False,
    )
    embed.add_field(
        name="Corrections",
        value=(
            "`/edit_stat`, `/remove_map`, and `/reset_series` can be used by the person who started the series "
            "or by someone with Manage Messages.\n"
            "`/series_status` shows the maps recorded so far.\n"
            "`/set_engine` switches between Gemini and local OCR for this channel."
        ),
        inline=False,
    )
    embed.set_footer(text="Built for Call of Duty scoreboard screenshots")
    await reply(interaction, embed=embed)


def main():
    if sys.version_info < (3, 11):
        logger.error("Python 3.11 or newer is required.")
        sys.exit(1)
    token = configured_token()
    if not token:
        logger.error(
            "DISCORD_BOT_TOKEN is not set. Copy .env.example to .env next to bot.py and paste the token from the Discord Developer Portal."
        )
        sys.exit(1)
    logger.info("Starting Call of Duty League Bot")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
