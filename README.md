# Call of Duty League Stats Discord Bot

Upload an end-game scoreboard screenshot. The bot reads player names, kills, deaths, assists, damage, and score, keeps them across a Best-of series, and posts a summary image plus a CSV.

It is a Discord slash-command bot. A small command-line tool can process screenshots without Discord.

## What it does

- `/start_series` opens a match in the current channel (two teams, best of 1–9).
- `/upload_map` reads one scoreboard and adds or replaces that map.
- `/series_summary` totals the series, picks an MVP, and attaches a PNG card and a CSV file.
- `/quick_scan` does the same read for a single screenshot, without a series.
- `/series_status` lists the maps already stored.
- `/edit_stat`, `/remove_map`, and `/reset_series` correct mistakes. The person who started the series, or someone with Manage Messages, can use these. Series saved before that rule existed stay editable by anyone in the channel.
- `/set_engine` picks Gemini or local OCR for that channel until the bot restarts.
- `/cod_help` shows the short version of this list.

Active series are stored in SQLite and restored after a restart. The scoreboard reader is Gemini by default. Local OCR is a fallback: it needs Tesseract, cannot tell the teams apart, and often misreads digits.

## Requirements

- Python 3.11 or newer
- A Discord application token
- A Gemini API key, unless you only want the OCR fallback
- Tesseract OCR (`tesseract-ocr`) only if you use local OCR

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\activate` and copy the example with `copy .env.example .env`.

Put the real values in `.env`, next to `bot.py`. The file is gitignored. `.env.example` only contains placeholders.

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | Bot token. `DISCORD_TOKEN` is accepted as a fallback name. |
| `GEMINI_API_KEY` | Yes for the default engine | Google AI Studio key used to read screenshots. |
| `DEFAULT_ENGINE` | No | `gemini` (default) or `ocr`. |
| `GEMINI_MODELS` | No | Comma-separated model fallback order. |
| `SERIES_DB_PATH` | No | SQLite path. Relative paths are resolved next to `bot.py`. |
| `EXTRACT_COOLDOWN_SECONDS` | No | Per-user pause between screenshot reads. Default `5`. |
| `SYNC_COMMANDS` | No | Sync slash commands on login. Default `true`. |
| `DISCORD_GUILD_ID` | No | Sync commands to one server immediately while testing. |

## Discord Developer Portal

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and create an application.
2. Open **Bot**, click **Reset Token**, and paste that token into `DISCORD_BOT_TOKEN`. Reset it again if it is ever pasted into a chat, a screenshot, or a log.
3. Leave **Privileged Gateway Intents** off. This bot does not read message text, member lists, or presences. It only receives slash-command arguments, including the uploaded screenshot. Requesting the Message Content intent makes Discord refuse the login when that toggle is off, and this bot does not need it.
4. Open **OAuth2 → URL Generator**. Select the scopes `bot` and `applications.commands`.
5. Select these bot permissions:
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
6. Open the generated URL and invite the bot to your server.

Global slash commands can take up to an hour to appear. For a faster loop while testing, set `DISCORD_GUILD_ID` to that server's ID and restart the bot. Clear it before you rely on the bot in more than one server, or the commands will only be registered there.

## Run

```bash
python bot.py
```

`python main.py` does the same thing, for hosts that look for `main.py`. The process exits immediately if `DISCORD_BOT_TOKEN` is missing. When the token is valid it logs in and syncs commands.

A `Procfile` runs `python bot.py` for worker-style hosts.

### Docker

The image runs as uid `10001`, includes DejaVu fonts and Tesseract, and stores series in `/data/cod_bot.db`.

```bash
docker build -t cod-bot .
docker run --env-file .env -v cod-data:/data cod-bot
```

A named volume picks up the directory owner from the image. For a bind mount, the host directory has to be writable by uid `10001`.

### Screenshots from the terminal

```bash
python cli_test.py map1.png map2.png map3.png
```

This writes `cli_series_summary.png` and `cli_series_summary.csv` in the current directory.

## Tests

```bash
python -m unittest discover -s . -p 'test_*.py'
```

The tests cover stat math, the summary image, CSV export, SQLite restore, image limits, and command registration. They do not call Discord or Gemini. `python bot.py` with no token should exit with status 1 and mention `DISCORD_BOT_TOKEN`.

## Notes

- Screenshot uploads are limited to PNG, JPG, WEBP, and GIF files under 8 MB. The bot re-encodes them to a bounded PNG before Gemini or OCR sees them.
- Player names from screenshots are untrusted. The bot does not ping `@everyone`, users, or roles, and CSV text cells that start with `=`, `+`, `-`, or `@` are prefixed so a spreadsheet does not treat them as formulas.
- No live Discord token or Gemini key is stored in this repository. Keep `.env` untracked. If a real token was ever shared outside this repo, reset it in the Developer Portal or Google AI Studio.
