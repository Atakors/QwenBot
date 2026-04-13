# Enhanced Qwen Telegram Bot

A feature-rich Telegram bot powered by Qwen AI (DashScope/Alibaba Cloud).

## ✨ Features

- 🤖 **Multi-Model Selection** — Switch between Qwen-Turbo, Plus, Max, Long, and VL-Max via inline keyboard
- 🌊 **Streaming Responses** — See responses as they generate, no waiting
- 🖼️ **Image Support** — Send images for vision analysis (Qwen-VL)
- 🎤 **Voice Messages** — Send voice notes, auto-transcribed and replied to
- 💬 **Reply-to-Message** — Reply to any message to use it as context
- 📝 **Custom System Prompt** — `/prompt` to customize AI personality
- 💾 **Persistent Storage** — Conversations survive bot restarts (SQLite)
- 📊 **Admin Panel** — `/stats` for usage, user count, token tracking
- 📁 **Conversation Export** — `/export` to download chat as `.txt`
- ⏱️ **Rate Limiting** — Per-user cooldown to prevent abuse
- 🔒 **Admin-Only Commands** — `/admin` restricted to configured admins
- 🐳 **Docker Support** — One-command deployment
- 🌐 **Webhook or Polling** — Choose your deployment mode
- 📐 **Message Splitting** — Handles responses beyond 4096 chars

## 🚀 Quick Start

### Option 1: Direct Python

```bash
pip install -r requirements.txt
python bot.py
```

### Option 2: Docker

```bash
docker compose up -d
```

### Option 3: Deploy to Render.com (Free)

1. Go to [render.com](https://render.com) and sign up with GitHub
2. Click **"New +"** → **"Web Service"**
3. Connect your **Atakors/QwenBot** repository
4. Configure:
   - **Name**: `qwen-telegram-bot`
   - **Region**: Choose closest to you
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - **Plan**: **Free**
5. Add **Environment Variables** (see Configuration table below)
6. Click **"Create Web Service"**
7. Wait ~2 minutes for deployment — your bot will start automatically!

> 💡 **Note on Free tier**: Render free instances sleep after 15 minutes of inactivity.
> **To keep the bot running 24/7, use one of the methods below:**
>
> ### 🔄 Method 1: Render Cron Job (Recommended)
> 1. In your Render Dashboard, click **"New +"** → **"Cron Job"**
> 2. Connect the same **Atakors/QwenBot** repo
> 3. Configure:
>    - **Name**: `bot-keep-alive`
>    - **Schedule**: `*/5 * * * *` (every 5 minutes)
>    - **Build Command**: `pip install httpx`
>    - **Start Command**: `python keep_alive.py`
> 4. Add environment variable: `RENDER_URL` = your bot's URL (e.g. `https://qwen-telegram-bot.onrender.com`)
> 5. Deploy! The cron job will ping your bot every 5 minutes, keeping it awake.
>
> ### 🌐 Method 2: UptimeRobot (Free Alternative)
> 1. Go to [uptimerobot.com](https://uptimerobot.com) → Sign up (free)
> 2. Add a new monitor:
>    - **Monitor Type**: `HTTP(s)`
>    - **Friendly Name**: `QwenBot Health`
>    - **URL**: `https://YOUR-RENDER-URL.onrender.com/health`
>    - **Monitoring Interval**: `5 minutes`
> 3. Save — UptimeRobot will ping your bot every 5 min, keeping it awake!

## ⚙️ Configuration

Edit `.env`:

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | ✅ |
| `DASHSCOPE_API_KEY` | DashScope API key (`sk-xxx`) | ✅ |
| `DASHSCOPE_API_BASE` | API endpoint URL | ✅ |
| `QWEN_MODEL` | Default model | ❌ |
| `SYSTEM_PROMPT` | Default AI personality | ❌ |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs | ❌ |
| `RATE_LIMIT_SECONDS` | Seconds between requests | ❌ |
| `MAX_HISTORY` | Conversation history turns | ❌ |
| `WEBHOOK_URL` | Webhook URL (leave empty for polling) | ❌ |

### Getting Your Admin ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Copy the numeric ID
3. Set `ADMIN_IDS=your_id` in `.env`

## 📋 Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Show all commands |
| `/model` | Change AI model (inline keyboard) |
| `/prompt [text]` | Set custom system prompt |
| `/prompt reset` | Reset to default prompt |
| `/clear` | Clear conversation |
| `/export` | Download chat history |
| `/stats` | Your usage stats |
| `/admin` | Admin panel (admins only) |

## 🏗️ Architecture

- **Storage**: SQLite (`bot_data.db`) — conversations, settings, usage stats
- **API**: OpenAI-compatible async client → DashScope
- **Telegram**: `python-telegram-bot` v21 (async)
- **Deployment**: Polling (default) or Webhook (production)

## 📝 License

MIT
