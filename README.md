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
