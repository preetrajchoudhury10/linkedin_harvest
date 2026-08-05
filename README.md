# LinkedIn Post Email Harvester

Telegram bot that searches LinkedIn hiring posts for email addresses and sends them as `.txt` files grouped by role (AI/ML and Java Backend).

## Features

- Scrapes LinkedIn posts across 27 hiring keywords
- Extracts email addresses using regex
- Separates results into `ai_{date}.txt` and `backend_{date}.txt`
- Sends to your Telegram via bot
- Daily scheduled harvest at 09:00
- Manual `/hunt` command anytime

## Quick Start

### 1. Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

Or manually:
- Push this repo to GitHub
- Go to [Railway](https://railway.app) → New Project → Deploy from GitHub

### 2. Set Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID (get from @userinfobot) |
| `LINKEDIN_COOKIES` | Base64-encoded LinkedIn cookies (see below) |

### 3. Generate LinkedIn Cookies (One-Time Setup)

LinkedIn requires an authenticated session. Since Railway runs headlessly, you generate cookies on your local machine once, then upload them.

**On your local computer:**

```bash
pip install playwright requests
playwright install chromium
python generate_cookies.py
```

A browser window opens → log into LinkedIn → press Enter in terminal → copy the base64 output.

**In Railway dashboard:**

Set `LINKEDIN_COOKIES` = the base64 string you copied.

### 4. Start the Bot

Once deployed and env vars are set, Railway starts the bot automatically.

Talk to your bot on Telegram:

- `/start` — Welcome message
- `/hunt` — Run harvest immediately
- `/search <keywords>` — Custom keyword search (separate with `|`, optional leading number = pages)
- `/status` — Last harvest stats
- `/setcookies` — Update cookies without redeploying

### Alternatively: Run Locally

```bash
pip install -r requirements.txt
playwright install chromium
# Set env vars or copy .env.example to .env
python main.py
```

## Architecture

```
main.py          # Entry point, scheduler, Telegram polling
bot.py           # Command handlers (/hunt, /status, etc.)
harvester.py     # Playwright-based LinkedIn scraper
extractor.py     # Email regex extraction & file output
generate_cookies.py  # Local cookie generator for Railway auth
config.json      # 27 keywords (14 AI/ML + 13 Backend)
```

## Output Files

- `output/ai_YYYYMMDD.txt` — One email per line from AI/ML keyword posts
- `output/backend_YYYYMMDD.txt` — One email per line from Backend keyword posts

## Keywords

**AI/ML:** generative AI engineer, ML engineer, NLP engineer, LLM engineer, RAG pipeline, prompt engineer, data scientist, MLOps, etc.

**Java Backend:** Java developer, Spring Boot, backend engineer, microservices, REST API, core Java, etc.

Customize keywords by editing `config.json` directly on GitHub.
