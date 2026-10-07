# 🎮 Call of Duty League Stats Discord Bot

Automate your Call of Duty League match night stats! Instead of manually typing in kills, deaths, assists, and damage after every map and averaging them by hand, simply **upload your end-game scoreboard screenshots**. 

The bot automatically parses each scoreboard, tracks player performance across a Best-of-3 (or Best-of-5) series, calculates all player totals & averages, and produces **broadcast-grade esports infographic cards** and **CSV spreadsheets** ready for Google Sheets or Excel.

---

## 🌟 Key Features

- **📸 Instant Screenshot Parsing**: Uses Gemini AI Vision (`gemini-3.8-flash`) to accurately extract player gamertags (handling clan tags like `[FaZe]`), eliminations/kills, deaths, assists, damage, score, and objective time. Also includes a local OCR fallback.
- **📈 Automatic Series Averages**: Tracks stats across Map 1, Map 2, Map 3, etc., and computes:
  - Total Kills, Deaths, Assists, Damage, Score
  - Overall K/D ratio ($Kills / Deaths$) and $+/-$ Kill Differential
  - Per-map averages (Avg Kills, Avg Deaths, Avg Damage, Avg Score)
  - Map-by-map performance records per player
- **🏆 Series MVP & Leaderboards**: Automatically calculates the Series MVP and highlights the top three players by MVP rating, alongside Most Kills, Most Damage, and Top K/D.
- **🎨 Broadcast-Quality Infographic Card**: Dynamically generates a sleek, dark-mode CDL-style match summary image (`.png`) with team scores, MVP badge, and color-coded K/D table.
- **📊 One-Click CSV Export**: Attaches a clean `.csv` spreadsheet to easily import match data directly into Google Sheets or league tracking spreadsheets.
- **✏️ Quick Corrections**: Typo or weird character? Easily adjust any number with `/edit_stat [player] [stat] [value]` in seconds.
- **💾 Persistent Active Series**: Active matches and uploaded map stats are stored in SQLite and restored after the bot restarts.

---

## 🚀 Quick Setup Guide (5 Minutes)

### Step 1: Install Dependencies
Open PowerShell or Command Prompt in this folder and run:
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment (`.env`)
Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
Open `.env` and fill in your keys:
1. **`DISCORD_BOT_TOKEN`**:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications).
   - Click **New Application** (e.g. name it "CoD League Stats").
   - Click on the **Bot** tab on the left.
   - Click **Reset Token** and copy your token into `.env`.
   - Scroll down to **Privileged Gateway Intents** and enable **Message Content Intent**.
   - Under **OAuth2** -> **URL Generator**, select `bot` and `applications.commands`.
   - Under **Bot Permissions**, check:
     - `Send Messages`
     - `Attach Files`
     - `Embed Links`
     - `Read Message History`
   - Copy the generated URL into your browser to invite the bot to your Discord server!

2. **`GEMINI_API_KEY`**:
   - Get a free key at [Google AI Studio](https://aistudio.google.com/app/apikey).
   - Paste the key into `GEMINI_API_KEY=` in your `.env` file.

3. **`SERIES_DB_PATH`** (optional):
   - Defaults to `cod_bot.db` in the bot's working directory.
   - For hosted deployments, point this to a persistent disk/volume so active series remain available across restarts or redeploys. The database file is created automatically.

### Step 3: Run the Bot
```bash
python bot.py
```
When you see `Bot logged in as CoD League Stats... Synced application commands`, you're ready!

---

## 🕹️ Discord Bot Commands

| Command | Description |
|---|---|
| `/start_series` | Initializes a new match session (e.g. `/start_series name:"Week 2" team1:"OpTic" team2:"FaZe" best_of:3`) |
| `/upload_map` | Upload the scoreboard screenshot image after each map. Instantly confirms extracted stats. |
| `/series_summary` | Calculates final series averages, generates the **infographic card**, and attaches the **CSV spreadsheet**! |
| `/quick_scan` | Scan a single scoreboard screenshot without starting a series. |
| `/series_status` | View all maps recorded so far in the current session. |
| `/edit_stat` | Manually fix any stat if needed (e.g. `/edit_stat player:"Shotzzy" stat:"kills" new_value:32`). |
| `/remove_map` | Remove an incorrectly uploaded map from the active series. |
| `/reset_series` | Clear the active series in the channel to start fresh. |
| `/set_engine` | Switch between Gemini AI Vision (recommended) and Local OCR. |
| `/cod_help` | Displays the help menu with all commands and instructions. |

---

## 💻 Standalone Offline / CLI Tool

You can also test or process match screenshots directly from your terminal without opening Discord:
```bash
python cli_test.py map1_screenshot.png map2_screenshot.png map3_screenshot.png
```
This will extract all stats, calculate the series averages, and output:
- `cli_series_summary.png` (infographic image)
- `cli_series_summary.csv` (spreadsheet)

---

## 🧪 Testing

To run the automated test suite and preview sample generated graphics:
```bash
python test_suite.py
```
This tests math formulas, averages, K/D calculations, and verifies that `sample_match_summary.png` and `sample_export.csv` generate properly.
