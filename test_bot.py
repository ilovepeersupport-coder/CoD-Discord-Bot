"""Offline tests for command registration, permissions, and startup."""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_TEST_DIR = tempfile.mkdtemp(prefix="cod-bot-test-")
os.environ["SERIES_DB_PATH"] = str(Path(_TEST_DIR) / "series.db")
os.environ.pop("DISCORD_BOT_TOKEN", None)
os.environ.pop("DISCORD_TOKEN", None)

import discord

import bot


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.done = False

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})
        self.done = True

    async def defer(self, *args, **kwargs):
        self.done = True


class FakeUser:
    def __init__(self, user_id, name):
        self.id = user_id
        self.display_name = name


class FakeInteraction:
    def __init__(self, channel_id, user, permissions=None):
        self.channel_id = channel_id
        self.user = user
        self.response = FakeResponse()
        self.permissions = permissions or discord.Permissions.none()
        self.followups = []

    async def followup_send(self, content=None, **kwargs):
        self.followups.append({"content": content, **kwargs})


class TestBotSetup(unittest.TestCase):
    def test_privileged_intents_are_not_requested(self):
        self.assertFalse(bot.bot.intents.message_content)
        self.assertFalse(bot.bot.intents.members)
        self.assertFalse(bot.bot.intents.presences)
        self.assertIsNone(bot.bot.help_command)
        self.assertFalse(bot.bot.allowed_mentions.everyone)
        self.assertFalse(bot.bot.allowed_mentions.users)
        self.assertFalse(bot.bot.allowed_mentions.roles)

    def test_slash_commands_are_registered(self):
        names = {command.name for command in bot.bot.tree.get_commands()}
        self.assertEqual(
            names,
            {
                "start_series",
                "upload_map",
                "quick_scan",
                "series_summary",
                "series_status",
                "edit_stat",
                "remove_map",
                "reset_series",
                "set_engine",
                "cod_help",
            },
        )

    def test_placeholder_token_is_rejected(self):
        previous = os.environ.get("DISCORD_BOT_TOKEN")
        os.environ["DISCORD_BOT_TOKEN"] = "your_discord_bot_token_here"
        try:
            self.assertIsNone(bot.configured_token())
        finally:
            if previous is None:
                os.environ.pop("DISCORD_BOT_TOKEN", None)
            else:
                os.environ["DISCORD_BOT_TOKEN"] = previous

    def test_main_exits_before_connecting_when_token_is_missing(self):
        env = os.environ.copy()
        env.pop("DISCORD_BOT_TOKEN", None)
        env.pop("DISCORD_TOKEN", None)
        env["SERIES_DB_PATH"] = str(Path(_TEST_DIR) / "startup.db")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "bot.py")],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, combined)
        self.assertIn("DISCORD_BOT_TOKEN", combined)
        self.assertNotIn("Bot logged in", combined)

    def test_attachment_and_permission_rules(self):
        self.assertIsNone(bot.attachment_problem("score.png", "image/png", 1000))
        self.assertIsNotNone(bot.attachment_problem("notes.txt", "text/plain", 1000))
        self.assertIsNotNone(bot.attachment_problem("huge.png", "image/png", 9 * 1024 * 1024))
        self.assertTrue(bot.actor_can_modify(5, False, {"created_by_id": 5}))
        self.assertFalse(bot.actor_can_modify(6, False, {"created_by_id": 5}))
        self.assertTrue(bot.actor_can_modify(6, True, {"created_by_id": 5}))
        self.assertTrue(bot.actor_can_modify(6, False, {"title": "legacy"}))

    def test_series_commands_respect_the_starter(self):
        bot._series_locks.clear()
        owner = FakeUser(5, "Owner")
        other = FakeUser(6, "Other")
        channel_id = 424242

        async def scenario():
            try:
                interaction = FakeInteraction(channel_id, owner)
                await bot.start_series.callback(interaction, "Week 1", "OpTic", "FaZe", 3)
                self.assertEqual(bot.active_series[channel_id]["created_by_id"], 5)
                self.assertTrue(interaction.response.messages)

                hijack = FakeInteraction(channel_id, other)
                await bot.start_series.callback(hijack, "Hijack", "A", "B", 3)
                self.assertEqual(bot.active_series[channel_id]["title"], "Week 1")
                self.assertTrue(hijack.response.messages)

                invalid = FakeInteraction(424243, owner)
                await bot.start_series.callback(invalid, "Bad", "A", "B", 0)
                self.assertNotIn(424243, bot.active_series)

                mod = FakeInteraction(channel_id, other, discord.Permissions(manage_messages=True))
                await bot.reset_series.callback(mod)
                self.assertNotIn(channel_id, bot.active_series)
            finally:
                bot.active_series.pop(channel_id, None)
                bot.active_series.pop(424243, None)
                bot.series_storage.delete(channel_id)
                bot.series_storage.delete(424243)

        asyncio.run(scenario())

    def test_cooldown_can_be_disabled(self):
        previous = os.environ.get("EXTRACT_COOLDOWN_SECONDS")
        try:
            os.environ["EXTRACT_COOLDOWN_SECONDS"] = "30"
            bot._last_extraction[42] = time.monotonic()
            self.assertGreater(bot.extraction_cooldown_remaining(42), 0)
            os.environ["EXTRACT_COOLDOWN_SECONDS"] = "0"
            self.assertEqual(bot.extraction_cooldown_remaining(42), 0)
        finally:
            if previous is None:
                os.environ.pop("EXTRACT_COOLDOWN_SECONDS", None)
            else:
                os.environ["EXTRACT_COOLDOWN_SECONDS"] = previous


if __name__ == "__main__":
    unittest.main()
