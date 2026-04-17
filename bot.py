#!/usr/bin/env python3
"""
Enhanced Qwen Telegram Bot
Features: Multi-model AI, streaming, images, voice, persistence, admin panel
"""

import asyncio
import base64
import html
import io
import logging
import os
import re
import sqlite3
import tempfile
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from skills import (
    split_message,
    send_chunks,
    escape_html,
)
from tools import (
    search_web_formatted,
    summarize_url,
    get_weather,
    get_crypto_price,
    get_news,
    detect_tool,
    save_file_metadata,
)
from cli_tools import (
    run_cli_command,
    format_cli_result,
    CLI_COMMANDS,
)
from productivity import (
    generate_image,
    github_get_user_info,
    github_list_repos,
    github_get_issue,
    github_search,
    notion_search,
    notion_create_page,
    notion_get_database,
    format_github_user,
    format_github_repos,
    format_notion_results,
    detect_productivity_command,
)

# ─────────────────────────────────────────────
# Load environment
# ─────────────────────────────────────────────
load_dotenv(override=True)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_BASE = os.getenv(
    "DASHSCOPE_API_BASE",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
DEFAULT_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")
DEFAULT_SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful AI assistant powered by Qwen. Respond concisely and helpfully.",
)

# ─────────────────────────────────────────────
# Auto Model Selection
# ─────────────────────────────────────────────
AUTO_MODEL_PATTERNS = [
    # Vision models for images
    (r"(analyze|describe|explain|what.*in|what.*at|see|look|view|show|image|photo|picture|diagram|chart|graph|screenshot)", "qwen-vl-max"),
    
    # Long context for documents/code
    (r"(long|document|paper|article|report|book|chapter|thesis|codebase|multiple files|entire)", "qwen-long"),
    
    # Complex reasoning
    (r"(solve|prove|derive|calculate|equation|formula|theorem|logic|reason|complex|hard|difficult)", "qwen-max"),
    
    # Creative writing
    (r"(write|create|compose|draft|poem|story|article|blog|email|letter|script|content)", "qwen-plus"),
    
    # Code generation
    (r"(code|program|function|class|module|script|debug|fix bug|implement|algorithm|data structure)", "qwen-coder-plus"),
    
    # Math
    (r"(\d+\s*[\+\-\*\/]\s*\d+|equation|integral|derivative|matrix|vector|geometry|algebra|calculus)", "qwen-max"),
    
    # Simple queries - use turbo for speed
    (r"(hi|hello|hey|thanks|ok|yes|no|what|when|where|who|why|how|define|explain|simple|quick)", "qwen-turbo"),
]


def auto_select_model(user_text: str, has_image: bool = False) -> tuple[str, str]:
    """
    Automatically select the best model based on user input.
    Returns (model_name, reason)
    """
    # Image always goes to VL model
    if has_image:
        return "qwen-vl-max", "👁️ Image detected"
    
    user_text = user_text.lower()
    
    # Check patterns in order (first match wins)
    for pattern, model in AUTO_MODEL_PATTERNS:
        if re.search(pattern, user_text, re.IGNORECASE):
            return model, "🤖 Auto-selected"
    
    # Default to turbo for speed
    return "qwen-turbo", "⚡ Default"
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "3"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))

# ─────────────────────────────────────────────
# Available models - fetched from API
# ─────────────────────────────────────────────
AVAILABLE_MODELS = {}


def fetch_available_models() -> dict:
    """Fetch available models from DashScope API."""
    models_map = {
        "auto": "🤖 Auto (Smart Select)",
    }
    
    try:
        import httpx
        api_base = DASHSCOPE_API_BASE.rstrip('/')
        # Try to get models from /models endpoint
        url = f"{api_base}/models" if '/compatible-mode' in api_base else f"{api_base}/v1/models"
        
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                url,
                headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                # Handle different API response formats
                model_list = data.get("data", data.get("models", []))
                for model in model_list:
                    model_id = model.get("id", model.get("model", ""))
                    if model_id and model_id.startswith("qwen"):
                        # Clean model name for display
                        display_name = model_id.replace("qwen-", "").title()
                        models_map[model_id] = f"🤖 {display_name}"
    except Exception as e:
        logger.debug(f"Could not fetch models from API, using defaults: {e}")
        # Fallback to known Qwen models
        fallback_models = {
            "qwen-turbo": "⚡ Turbo (Fast)",
            "qwen-plus": "⚖️ Plus (Balanced)",
            "qwen-max": "🏆 Max (Best Quality)",
            "qwen-long": "📚 Long (Long Context)",
            "qwen-vl-max": "👁️ VL Max (Vision)",
        }
        models_map.update(fallback_models)
    
    return models_map


# Fetch models at startup
AVAILABLE_MODELS = fetch_available_models()

# ─────────────────────────────────────────────
# Auto model selection rules
# ─────────────────────────────────────────────
MODEL_RULES = [
    (lambda text, has_image, text_len: text_len > 1500 or any(k in text.lower() for k in
        ["long document", "summarize this", "analyze this text", "full text", "entire",
         "this article", "this essay", "this paper", "translate this entire"]), "qwen-long"),
    (lambda text, has_image, text_len: any(k in text.lower() for k in
        ["write code", "write a function", "debug this", "fix this bug", "refactor",
         "```python", "```javascript", "```java", "```c++", "```cpp",
         "```typescript", "```rust", "```go ", "```ruby", "```swift"]), "qwen-max"),
    (lambda text, has_image, text_len: any(k in text.lower() for k in
        ["write a story", "write a poem", "write an essay", "creative writing",
         "deep analysis", "compare and contrast", "comprehensive analysis"]), "qwen-max"),
    (lambda text, has_image, text_len: any(k in text.lower() for k in
        ["translate", "translate this", "translate to", "what does this mean in"]), "qwen-turbo"),
    (lambda text, has_image, text_len: any(k in text.lower() for k in
        ["what is", "what are", "who is", "how to", "explain", "tell me about"]), "qwen-turbo"),
    (lambda text, has_image, text_len: any(k in text.lower() for k in
        ["calculate", "solve this equation", "math", "algebra", "calculus"]), "qwen-plus"),
]


def auto_select_model(text: str, has_image: bool = False) -> tuple[str, str]:
    """Automatically select the best model based on input."""
    if has_image:
        return "qwen-vl-max", "Image detected"

    text_len = len(text)
    matched_model = None
    for rule_fn, model in MODEL_RULES:
        if rule_fn(text.lower(), has_image, text_len):
            matched_model = model

    if matched_model:
        reasons = {
            "qwen-turbo": "Simple Q&A",
            "qwen-plus": "Reasoning task",
            "qwen-max": "Complex task",
            "qwen-long": "Long content",
            "qwen-vl-max": "Image detected",
        }
        return matched_model, reasons.get(matched_model, "Auto-selected")

    if text_len > 500 or text.count("\n") > 5:
        return "qwen-plus", f"Long input ({text_len} chars)"
    return "qwen-turbo", "Quick reply"


# ─────────────────────────────────────────────
# Async OpenAI client
# ─────────────────────────────────────────────
aclient = AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_API_BASE,
)

# ─────────────────────────────────────────────
# SQLite Database
# ─────────────────────────────────────────────
DB_PATH = Path("bot_data.db")
db_lock = Lock()


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp REAL,
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            model TEXT,
            system_prompt TEXT,
            username TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS usage_stats (
            user_id INTEGER,
            tokens_in INTEGER,
            tokens_out INTEGER,
            model TEXT,
            timestamp REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id INTEGER PRIMARY KEY,
            last_request REAL
        )
    """)

    conn.commit()
    conn.close()


init_db()

# ─────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────
def split_message(text: str, limit: int = 4096) -> list[str]:
    """Split long messages into chunks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


def format_md(md_text: str) -> str:
    """Convert markdown to Telegram HTML safely."""
    md_text = html.escape(md_text, quote=False)
    md_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", md_text)
    md_text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", md_text)
    md_text = re.sub(r"```(.+?)```", r"<pre>\1</pre>", md_text, flags=re.DOTALL)
    md_text = re.sub(r"`(.+?)`", r"<code>\1</code>", md_text)
    return md_text


async def send_long_message(chat, text: str, parse_mode: str = "HTML", **kwargs):
    """Send a potentially long message by splitting it."""
    for chunk in split_message(text):
        await chat.send_message(chunk, parse_mode=parse_mode, **kwargs)


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────
def check_rate_limit(user_id: int) -> tuple[bool, float]:
    """Check if user is rate limited. Returns (allowed, wait_seconds)."""
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT last_request FROM rate_limits WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        now = time.time()
        if row and (now - row["last_request"]) < RATE_LIMIT_SECONDS:
            wait = RATE_LIMIT_SECONDS - (now - row["last_request"])
            conn.close()
            return False, round(wait, 1)
        c.execute(
            "INSERT OR REPLACE INTO rate_limits (user_id, last_request) VALUES (?, ?)",
            (user_id, now),
        )
        conn.commit()
        conn.close()
        return True, 0


def record_usage(user_id: int, tokens_in: int, tokens_out: int, model: str):
    """Record API usage for stats."""
    with db_lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO usage_stats (user_id, tokens_in, tokens_out, model, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, tokens_in, tokens_out, model, time.time()),
        )
        conn.commit()
        conn.close()


def get_user_model(user_id: int) -> str:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT model FROM user_settings WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        return row["model"] if row and row["model"] else DEFAULT_MODEL


def set_user_model(user_id: int, model: str):
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM user_settings WHERE user_id = ?", (user_id,))
        exists = c.fetchone()
        if exists:
            conn.execute("UPDATE user_settings SET model = ? WHERE user_id = ?", (model, user_id))
        else:
            conn.execute(
                "INSERT INTO user_settings (user_id, model, system_prompt, username) VALUES (?, ?, ?, ?)",
                (user_id, model, DEFAULT_SYSTEM_PROMPT, None),
            )
        conn.commit()
        conn.close()


def get_user_system_prompt(user_id: int) -> str:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT system_prompt FROM user_settings WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        return row["system_prompt"] if row and row["system_prompt"] else DEFAULT_SYSTEM_PROMPT


def set_user_system_prompt(user_id: int, prompt: str):
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM user_settings WHERE user_id = ?", (user_id,))
        exists = c.fetchone()
        if exists:
            conn.execute("UPDATE user_settings SET system_prompt = ? WHERE user_id = ?", (prompt, user_id))
        else:
            conn.execute(
                "INSERT INTO user_settings (user_id, model, system_prompt, username) VALUES (?, ?, ?, ?)",
                (user_id, DEFAULT_MODEL, prompt, None),
            )
        conn.commit()
        conn.close()


def save_message(user_id: int, role: str, content: str):
    with db_lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, time.time()),
        )
        conn.commit()
        conn.close()


def get_conversation(user_id: int, max_turns: int = 10) -> list[dict]:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, max_turns * 2),
        )
        rows = c.fetchall()[::-1]
        conn.close()
        return [{"role": r["role"], "content": r["content"]} for r in rows]


def clear_conversation(user_id: int):
    with db_lock:
        conn = get_db()
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()


def export_conversation(user_id: int) -> str:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role, content, timestamp FROM conversations WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        rows = c.fetchall()
        conn.close()

    lines = [f"# Conversation Export - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for r in rows:
        ts = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
        role_name = "You" if r["role"] == "user" else "AI"
        lines.append(f"\n--- [{ts}] {role_name}:\n{r['content']}")
    return "\n".join(lines)


def get_stats() -> dict:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(DISTINCT user_id) FROM conversations")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM conversations")
        total_messages = c.fetchone()[0]
        c.execute("SELECT SUM(tokens_in), SUM(tokens_out) FROM usage_stats")
        row = c.fetchone()
        tokens_in = row[0] or 0
        tokens_out = row[1] or 0
        c.execute("SELECT model, COUNT(*) FROM usage_stats GROUP BY model ORDER BY COUNT(*) DESC LIMIT 5")
        model_usage = dict(c.fetchall())
        conn.close()
    return {
        "total_users": total_users,
        "total_messages": total_messages,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model_usage": model_usage,
    }


def get_user_stats(user_id: int) -> dict:
    with db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,))
        messages = c.fetchone()[0]
        c.execute("SELECT SUM(tokens_in), SUM(tokens_out) FROM usage_stats WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
    return {"messages": messages, "tokens_in": row[0] or 0, "tokens_out": row[1] or 0}


# ─────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 <b>Hello, {html.escape(user)}!</b>\n\n"
        f"🤖 I'm your <b>Qwen AI</b> assistant — ready to help!\n\n"
        f"✨ <b>Features:</b>\n"
        f"🧠 <b>Smart Model Selection</b> — I pick the best AI for your task\n"
        f"🖼️ <b>Image Analysis</b> — Send photos for vision insights\n"
        f"🎤 <b>Voice Support</b> — Send voice notes for AI replies\n\n"
        f"📌 <b>Quick Start:</b>\n"
        f"• Just type your message\n"
        f"• /model — Choose AI model\n"
        f"• /prompt — Customize my personality\n"
        f"• /help — See all commands\n\n"
        f"🧠 <b>Memory:</b> Your conversation history is saved automatically!",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Available Commands</b>\n\n"
        "🚀 <b>Core:</b>\n"
        "  /start — Start the bot\n"
        "  /help — Show this message\n"
        "  /clear — Clear conversation\n"
        "  /context — View conversation history\n\n"
        "🤖 <b>AI Settings:</b>\n"
        "  /model — Change AI model\n"
        "  /prompt [text] — Set custom personality\n"
        "  /prompt reset — Reset to default\n"
        "  🤖 <b>Auto Mode:</b> Select 'Auto' in /model to let AI pick the best model!\n\n"
        "🌐 <b>Internet Tools:</b>\n"
        "  /search [query] — Search the web\n"
        "  /fetch [url] — Fetch webpage content\n"
        "  /weather [city] — Get live weather\n"
        "  /stock [symbol] — Crypto prices (BTC, ETH...)\n"
        "  /news — Top news headlines\n\n"
        "🖥️ <b>Admin CLI:</b>\n"
        "  /cli — Bot control (admins only)\n"
        "  /cli status — Check bot status\n"
        "  /cli models — List AI models\n"
        "  /cli stats — Usage statistics\n\n"
        "🎨 <b>Productivity:</b>\n"
        "  /image [prompt] — Generate AI image\n"
        "  /github [user] — GitHub profile\n"
        "  /repo [user] — GitHub repositories\n"
        "  /issue [repo] [num] — GitHub issue/PR\n"
        "  /gitsearch [query] — Search GitHub\n"
        "  /notion [query] — Search Notion pages\n"
        "  /notionpage [title] [content] — Create Notion page\n\n"
        "📊 <b>Tools:</b>\n"
        "  /export — Export chat as .txt\n"
        "  /stats — Your usage statistics\n"
        "  /admin — Admin panel\n\n"
        "💡 <b>Tips:</b>\n"
        "  💬 Reply to any message to use as context\n"
        "  🖼️ Send images for vision analysis\n"
        "  🎤 Send voice notes for transcription\n"
        "  📎 Send documents for AI analysis\n"
        "  🔗 Send URLs to fetch page content\n"
        "  🧠 <b>Memory:</b> Your conversation is saved automatically!",
        parse_mode="HTML",
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_conversation(user_id)
    await update.message.reply_text("🗑️ <b>Conversation cleared!</b>\n\nYour chat history has been wiped. Start fresh! ✨", parse_mode="HTML")


async def show_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current conversation history."""
    user_id = update.effective_user.id
    history = get_conversation(user_id, MAX_HISTORY)
    
    if not history:
        await update.message.reply_text(
            "🧠 <b>Conversation Context</b>\n\n"
            "No conversation history yet.\n\n"
            "Start chatting and I'll remember everything we discuss! 💬",
            parse_mode="HTML",
        )
        return
    
    text = f"🧠 <b>Conversation Context</b>\n\n"
    text += f"<i>Showing last {len(history)//2} exchanges ({len(history)} messages in memory)</i>\n\n"
    
    for i, msg in enumerate(history[-10:], 1):  # Show last 10 messages
        role_icon = "👤 You" if msg["role"] == "user" else "🤖 AI"
        preview = msg["content"][:150].replace("\n", " ")
        if len(msg["content"]) > 150:
            preview += "..."
        text += f"<b>{i}.</b> {role_icon}: <i>{html.escape(preview)}</i>\n\n"
    
    text += f"<i>Total messages: {len(history)} | Max history: {MAX_HISTORY * 2}</i>"
    
    await update.message.reply_text(text, parse_mode="HTML")


async def show_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_model = get_user_model(user_id)

    keyboard = []
    for model_id, model_name in AVAILABLE_MODELS.items():
        checkmark = "✅ " if model_id == current_model else ""
        keyboard.append([InlineKeyboardButton(f"{checkmark}{model_name}", callback_data=f"setmodel_{model_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Count conversation history
    history_count = len(get_conversation(user_id, MAX_HISTORY))
    history_note = f"\n\n🧠 <b>Memory:</b> {history_count} messages in context (preserved when switching models)" if history_count > 0 else ""
    
    await update.message.reply_text(
        f"🤖 <b>AI Model Selection</b>\n\n"
        f"Current: <b>{html.escape(current_model)}</b>{history_note}\n\n"
        f"Choose a model below:\n"
        f"<i>Your conversation history is automatically preserved when switching models</i>",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    selected_model = query.data.replace("setmodel_", "")

    if selected_model in AVAILABLE_MODELS:
        set_user_model(user_id, selected_model)
        # Check if there's conversation history
        history_count = len(get_conversation(user_id, MAX_HISTORY))
        memory_note = f"\n\n🧠 <b>Memory:</b> Your {history_count} previous messages are preserved and will be used as context." if history_count > 0 else ""
        
        await query.edit_message_text(
            f"✅ <b>Model Updated!</b>\n\n"
            f"Switched to: <b>{html.escape(selected_model)}</b>"
            f"{memory_note}",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Invalid model selected.")


async def set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        current = get_user_system_prompt(user_id)
        await update.message.reply_text(
            f"📝 <b>Current System Prompt</b>\n\n"
            f"<code>{html.escape(current)}</code>\n\n"
            f"💬 Usage: <code>/prompt [text]</code>\n"
            f"🔄 Reset: <code>/prompt reset</code>",
            parse_mode="HTML",
        )
        return

    if text.lower() == "reset":
        set_user_system_prompt(user_id, DEFAULT_SYSTEM_PROMPT)
        await update.message.reply_text("🔄 <b>System prompt reset to default!</b>", parse_mode="HTML")
        return

    set_user_system_prompt(user_id, text)
    await update.message.reply_text(
        f"✅ <b>System Prompt Updated!</b>\n\n{html.escape(text)}",
        parse_mode="HTML",
    )


async def export_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    content = export_conversation(user_id)

    if not content or content.count("\n---") <= 1:
        await update.message.reply_text("📭 <b>No conversation to export yet!</b>\n\nStart chatting first, then try again.")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(content)
        f_path = f.name

    with open(f_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            caption="📄 <b>Conversation Exported!</b>",
        )
    os.unlink(f_path)


async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_stats(user_id)
    model = get_user_model(user_id)
    prompt = get_user_system_prompt(user_id)

    await update.message.reply_text(
        f"📊 <b>Your Statistics</b>\n\n"
        f"🤖 Model: <b>{html.escape(model)}</b>\n"
        f"💬 Messages: <b>{stats['messages']}</b>\n"
        f"📥 Tokens In: <b>{stats['tokens_in']:,}</b>\n"
        f"📤 Tokens Out: <b>{stats['tokens_out']:,}</b>\n\n"
        f"📝 System: <i>{html.escape(prompt[:50])}{'...' if len(prompt) > 50 else ''}</i>",
        parse_mode="HTML",
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🔒 <b>Admin access required.</b>")
        return

    stats = get_stats()
    text = (
        f"🛡️ <b>Admin Panel</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"💬 Total Messages: <b>{stats['total_messages']}</b>\n"
        f"📥 Total Tokens In: <b>{stats['tokens_in']:,}</b>\n"
        f"📤 Total Tokens Out: <b>{stats['tokens_out']:,}</b>\n"
    )
    if stats["model_usage"]:
        text += "\n📊 <b>Model Usage:</b>\n"
        for m, c in stats["model_usage"].items():
            text += f"  • {html.escape(m)}: <b>{c}</b> requests\n"

    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")]]
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Refreshing...")
    stats = get_stats()
    text = (
        f"🛡️ <b>Admin Panel (Refreshed)</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"💬 Total Messages: <b>{stats['total_messages']}</b>\n"
        f"📥 Total Tokens In: <b>{stats['tokens_in']:,}</b>\n"
        f"📤 Total Tokens Out: <b>{stats['tokens_out']:,}</b>\n"
    )
    if stats["model_usage"]:
        text += "\n📊 <b>Model Usage:</b>\n"
        for m, c in stats["model_usage"].items():
            text += f"  • {html.escape(m)}: <b>{c}</b> requests\n"
    await query.edit_message_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────
# Core message handler
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text, image, and voice messages."""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        logger.info(f"Message from user {user_id}: {update.message.text[:80] if update.message.text else '[media]'}")

        # Register username
        if username:
            with db_lock:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT user_id FROM user_settings WHERE user_id = ?", (user_id,))
                if c.fetchone():
                    conn.execute("UPDATE user_settings SET username = ? WHERE user_id = ?", (username, user_id))
                conn.commit()
                conn.close()

        # Determine model and settings
        user_model = get_user_model(user_id)
        
        # Auto-select model if user has "auto" selected or based on input
        has_image = bool(update.message.photo)
        if user_model == "auto":
            model, model_reason = auto_select_model(user_text, has_image)
        else:
            model = user_model
            model_reason = "👤 User selected"
        
        system_prompt = get_user_system_prompt(user_id)
        temperature = 0.7
        max_tokens = 4096

        # Build user text
        user_text = ""

        # Text message
        if update.message.text:
            user_text = update.message.text

        # Reply-to-message context
        if update.message.reply_to_message and update.message.reply_to_message.text:
            user_text = (
                f"Referencing this message:\n> {update.message.reply_to_message.text}\n\n{user_text or 'Respond to this:'}"
            )

        # Image handling
        photo = update.message.photo[-1] if update.message.photo else None
        has_image = bool(photo)
        image_data = None

        if has_image:
            tg_file = await context.bot.get_file(photo.file_id)
            image_bytes = io.BytesIO()
            await tg_file.download_to_memory(image_bytes)
            image_bytes.seek(0)
            image_data = base64.b64encode(image_bytes.getvalue()).decode("utf-8")

        # Voice transcription
        if update.message.voice:
            try:
                voice_file = await update.message.voice.get_file()
                with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                    await voice_file.download_to_drive(tmp.name)
                    tmp_path = tmp.name
                try:
                    with open(tmp_path, "rb") as f:
                        whisper_resp = await aclient.audio.transcriptions.create(
                            model="whisper-1",
                            file=f,
                        )
                    user_text = f"[Voice message]: {whisper_resp.text}"
                finally:
                    os.unlink(tmp_path)
            except Exception as e:
                logger.warning(f"Voice transcription failed: {e}")
                user_text = "[Voice message - transcription unavailable]"

        if not user_text and not has_image:
            return

        # ─────────────────────────────────────────
        # Tool Detection - Handle internet requests
        # ─────────────────────────────────────────
        if update.message.text:
            tool_name, tool_arg = detect_tool(update.message.text)
            
            if tool_name == "web_search":
                await update.message.reply_text("🔍 <i>Searching the web...</i>", parse_mode="HTML")
                result = await search_web_formatted(tool_arg)
                await send_chunks(update.message.chat, result, parse_mode="HTML")
                return
            
            elif tool_name == "url_fetch":
                await update.message.reply_text("🌐 <i>Fetching page content...</i>", parse_mode="HTML")
                result = await summarize_url(tool_arg)
                await send_chunks(update.message.chat, result, parse_mode="HTML")
                return
            
            elif tool_name == "weather":
                await update.message.reply_text("🌤️ <i>Getting weather data...</i>", parse_mode="HTML")
                result = await get_weather(tool_arg)
                await update.message.reply_text(result, parse_mode="HTML")
                return
            
            elif tool_name == "crypto":
                result = await get_crypto_price(tool_arg)
                await update.message.reply_text(result, parse_mode="HTML")
                return
            
            elif tool_name == "news":
                await update.message.reply_text("📰 <i>Fetching news...</i>", parse_mode="HTML")
                result = await get_news()
                await send_chunks(update.message.chat, result, parse_mode="HTML")
                return
            
            elif tool_name == "url_in_message":
                # If message contains a URL but no /fetch command, ask if user wants to fetch it
                urls = re.findall(r"https?://\S+", update.message.text)
                if urls and len(urls) == 1 and not update.message.reply_to_message:
                    # Single URL in message - offer to fetch
                    keyboard = [[InlineKeyboardButton("🌐 Fetch Page", callback_data=f"fetchurl_{urls[0]}")]]
                    await update.message.reply_text(
                        f"🔗 <b>Link detected!</b>\n\n"
                        f"<i>{escape_html(urls[0][:80])}</i>\n\n"
                        f"Would you like me to fetch and analyze this page?",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                    return

        # Rate limit check
        allowed, wait_time = check_rate_limit(user_id)
        if not allowed:
            await update.message.reply_text(
                f"⏳ <b>Slow down!</b>\n\nPlease wait <b>{wait_time}s</b> before sending another message.",
                parse_mode="HTML",
            )
            return

        # Build conversation context
        history = get_conversation(user_id, MAX_HISTORY)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        # Build user message
        if image_data and model == "qwen-vl-max":
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                    {"type": "text", "text": user_text or "Describe this image in detail."},
                ],
            })
        else:
            if image_data:
                user_text = (user_text or "Describe this image:") + " [image attached]"
            messages.append({"role": "user", "content": user_text})

        # Save user message
        save_message(user_id, "user", user_text or "[image]")

        # Send typing indicator
        await update.message.chat.send_action(action="typing")

        # Call AI API with streaming
        response = await aclient.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        # Stream response
        full_reply = ""
        sent_msg = await update.message.reply_text("...")
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                full_reply += chunk.choices[0].delta.content
                # Update message periodically
                if len(full_reply) % 80 < 5:
                    try:
                        display_text = format_md(full_reply)
                        # Truncate if too long for single message
                        if len(display_text) > 3500:
                            display_text = display_text[:3500] + "\n\n<i>...</i>"
                        await sent_msg.edit_text(display_text, parse_mode="HTML")
                    except Exception:
                        pass

        # Final message with footer - use send_chunks for long responses
        footer = f"\n\n━━━━━━━━━━\n<i>{model_reason} · 🤖 {html.escape(model)}</i>"
        final_text = format_md(full_reply) + footer
        
        try:
            await sent_msg.delete()
        except Exception:
            pass
        
        await send_chunks(update.message.chat, final_text, parse_mode="HTML")

        # Save assistant response
        save_message(user_id, "assistant", full_reply.strip())

        # Record usage
        tokens_out = int(len(full_reply.split()) * 1.3)
        tokens_in = 0
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                tokens_in += int(len(content.split()) * 1.3)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("text"):
                        tokens_in += int(len(part["text"].split()) * 1.3)
        record_usage(user_id, tokens_in, tokens_out, model)

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        error_msg = str(e).lower()
        if "rate" in error_msg or "429" in error_msg:
            error_text = "🚦 <b>Rate Limited</b>\n\nPlease wait a moment and try again."
        elif "connection" in error_msg:
            error_text = "🌐 <b>Connection Error</b>\n\nPlease check your internet and try again."
        elif "timeout" in error_msg:
            error_text = "⏱️ <b>Timeout</b>\n\nThe AI is busy. Please try again in a moment."
        elif "401" in error_msg or "api key" in error_msg:
            error_text = "🔑 <b>API Key Error</b>\n\nPlease contact the bot administrator."
        else:
            error_text = f"❌ <b>Error</b>\n\n{html.escape(str(e)[:200])}"

        try:
            await update.message.reply_text(error_text, parse_mode="HTML")
        except Exception:
            logger.error(f"Failed to send error message: {e}")


# ─────────────────────────────────────────────
# URL Fetch Callback Handler
# ─────────────────────────────────────────────
async def url_fetch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle URL fetch button click."""
    query = update.callback_query
    await query.answer("🌐 Fetching page...")
    
    url = query.data.replace("fetchurl_", "")
    user_id = query.from_user.id
    
    logger.info(f"User {user_id} requested URL fetch: {url[:80]}")
    
    # Fetch and summarize the URL
    result = await summarize_url(url)
    await send_chunks(query.message.chat, result, parse_mode="HTML")


# ─────────────────────────────────────────────
# Internet Tool Command Handlers
# ─────────────────────────────────────────────
async def web_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search command."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "🔍 <b>Web Search</b>\n\n"
            "Usage: /search [your query]\n"
            "Example: /search latest AI news",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text("🔍 <i>Searching the web...</i>", parse_mode="HTML")
    result = await search_web_formatted(query)
    await send_chunks(update.message.chat, result, parse_mode="HTML")


async def url_fetch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fetch command."""
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "🌐 <b>URL Fetch</b>\n\n"
            "Usage: /fetch [URL]\n"
            "Example: /fetch https://example.com",
            parse_mode="HTML",
        )
        return
    
    url = context.args[0]
    await update.message.reply_text("🌐 <i>Fetching page content...</i>", parse_mode="HTML")
    result = await summarize_url(url)
    await send_chunks(update.message.chat, result, parse_mode="HTML")


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weather command."""
    city = " ".join(context.args)
    if not city:
        await update.message.reply_text(
            "🌤️ <b>Weather</b>\n\n"
            "Usage: /weather [city]\n"
            "Example: /weather London",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text("🌤️ <i>Getting weather data...</i>", parse_mode="HTML")
    result = await get_weather(city)
    await update.message.reply_text(result, parse_mode="HTML")


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stock command."""
    symbol = " ".join(context.args)
    if not symbol:
        await update.message.reply_text(
            "📈 <b>Crypto Prices</b>\n\n"
            "Usage: /stock [symbol]\n"
            "Examples: /stock BTC, /stock ETH, /stock SOL",
            parse_mode="HTML",
        )
        return
    
    result = await get_crypto_price(symbol)
    await update.message.reply_text(result, parse_mode="HTML")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /news command."""
    await update.message.reply_text("📰 <i>Fetching news...</i>", parse_mode="HTML")
    result = await get_news()
    await send_chunks(update.message.chat, result, parse_mode="HTML")


# ─────────────────────────────────────────────
# Productivity Command Handlers
# ─────────────────────────────────────────────
async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /image command for image generation."""
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(
            "🎨 <b>Image Generation</b>\n\n"
            "Usage: /image [description]\n"
            "Example: /image a sunset over mountains\n\n"
            "Configure OPENAI_API_KEY or GEMINI_API_KEY in .env",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text(
        "🎨 <i>Generating image... (this may take 30-60 seconds)</i>",
        parse_mode="HTML",
    )
    
    result = await generate_image(prompt)
    
    if result["success"] and result.get("url"):
        await update.message.reply_photo(
            photo=result["url"],
            caption=f"🎨 <b>Prompt:</b> {escape_html(prompt)}\n\n<i>Generated with AI</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ <b>Image generation failed</b>\n\n{escape_html(result.get('error', 'Unknown error'))}",
            parse_mode="HTML",
        )


async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /github command."""
    username = " ".join(context.args)
    if not username:
        await update.message.reply_text(
            "🐙 <b>GitHub</b>\n\n"
            "Usage: /github [username]\n"
            "Example: /github torvalds\n\n"
            "Set GITHUB_TOKEN in .env for higher rate limits",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text("🐙 <i>Fetching GitHub profile...</i>", parse_mode="HTML")
    result = await github_get_user_info(username.strip())
    await update.message.reply_text(format_github_user(result), parse_mode="HTML")


async def github_repos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /repo command."""
    username = " ".join(context.args)
    if not username:
        await update.message.reply_text(
            "🐙 <b>GitHub Repositories</b>\n\n"
            "Usage: /repo [username]\n"
            "Example: /repo microsoft",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text("🐙 <i>Fetching repositories...</i>", parse_mode="HTML")
    result = await github_list_repos(username.strip())
    await send_chunks(update.message.chat, format_github_repos(result), parse_mode="HTML")


async def github_issue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /issue command."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "🐙 <b>GitHub Issue</b>\n\n"
            "Usage: /issue [repo] [number]\n"
            "Example: /issue microsoft/vscode 12345",
            parse_mode="HTML",
        )
        return
    
    repo, number = args[0], args[1]
    await update.message.reply_text("🐙 <i>Fetching issue...</i>", parse_mode="HTML")
    result = await github_get_issue(repo, number)
    
    if result.get("success"):
        type_emoji = "🔀" if result.get("is_pr") else "📋"
        state_emoji = "🟢" if result.get("state") == "open" else "🔴"
        text = (
            f"{type_emoji} <b>#{result['number']} - {escape_html(result['title'])}</b>\n\n"
            f"{state_emoji} <b>State:</b> {result['state']}\n"
            f"👤 <b>Author:</b> {escape_html(result['user'])}\n"
            f"💬 <b>Comments:</b> {result['comments']}\n\n"
            f"<i>{escape_html(result['body'][:500] or 'No description')}</i>"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ {escape_html(result.get('error'))}", parse_mode="HTML")


async def github_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /gitsearch command."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "🐙 <b>GitHub Search</b>\n\n"
            "Usage: /gitsearch [query]\n"
            "Example: /gitsearch python machine learning",
            parse_mode="HTML",
        )
        return
    
    await update.message.reply_text("🐙 <i>Searching GitHub...</i>", parse_mode="HTML")
    result = await github_search(query)
    
    if result.get("success"):
        text = f"🐙 <b>Search Results ({result['total']} found)</b>\n\n"
        for i, repo in enumerate(result["repos"], 1):
            text += f"<b>{i}.</b> <a href='{escape_html(repo['url'])}'>{escape_html(repo['name'])}</a>\n"
            text += f"   <i>{escape_html(repo['description'][:100])}</i>\n"
            text += f"   ⭐ {repo['stars']} · {repo.get('language', 'N/A')}\n\n"
        await send_chunks(update.message.chat, text, parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ {escape_html(result.get('error'))}", parse_mode="HTML")


async def notion_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /notion command."""
    query = " ".join(context.args)
    
    await update.message.reply_text("📝 <i>Searching Notion...</i>", parse_mode="HTML")
    result = await notion_search(query)
    await update.message.reply_text(format_notion_results(result), parse_mode="HTML")


async def notion_create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /notionpage command."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 <b>Create Notion Page</b>\n\n"
            "Usage: /notionpage [title] [content]\n"
            "Example: /notionpage Meeting Notes Discussed project roadmap",
            parse_mode="HTML",
        )
        return
    
    title = args[0]
    content = " ".join(args[1:])
    
    result = await notion_create_page(title, content)
    
    if result.get("success"):
        await update.message.reply_text(
            f"✅ <b>Page created!</b>\n\n"
            f"<b>Title:</b> {escape_html(title)}\n"
            f"🔗 <a href='{escape_html(result['url'])}'>Open in Notion</a>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ <b>Failed to create page</b>\n\n{escape_html(result.get('error'))}",
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────
# CLI Command Handler
# ─────────────────────────────────────────────
async def cli_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cli command for bot control."""
    user_id = update.effective_user.id
    
    # Check admin access
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "🔒 <b>Admin Access Required</b>\n\n"
            "CLI commands are restricted to administrators only.",
            parse_mode="HTML",
        )
        return
    
    # Parse command
    args = context.args
    if not args:
        # Show available commands
        cmds_text = "🖥️ <b>CLI Commands</b>\n\n"
        for name, data in sorted(CLI_COMMANDS.items()):
            admin_badge = "🔒" if data["admin_only"] else "🟢"
            cmds_text += f"{admin_badge} <code>/cli {name}</code> — {data['description']}\n"
        
        cmds_text += "\n<i>🔒 = Admin only | 🟢 = All admins</i>"
        await update.message.reply_text(cmds_text, parse_mode="HTML")
        return
    
    # Run command
    cmd_name = args[0].lower()
    cmd_args = " ".join(args[1:]) if len(args) > 1 else ""
    
    logger.info(f"CLI command from admin {user_id}: {cmd_name} {cmd_args}")
    
    # Check if command requires admin
    if cmd_name in CLI_COMMANDS and CLI_COMMANDS[cmd_name]["admin_only"] and user_id not in ADMIN_IDS:
        await update.message.reply_text("🔒 This command requires admin access.")
        return
    
    await update.message.reply_text("⚙️ <i>Running command...</i>", parse_mode="HTML")
    
    # Execute CLI command
    result = await run_cli_command(cmd_name, cmd_args)
    
    # Format and send result
    formatted = format_cli_result(cmd_name, result)
    await send_chunks(update.message.chat, formatted, parse_mode="HTML")


# ─────────────────────────────────────────────
# Document/File Handler
# ─────────────────────────────────────────────
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document/file uploads from user."""
    try:
        user_id = update.effective_user.id
        document = update.message.document
        
        # Get file info
        file_name = document.file_name or "unknown_file"
        file_size = document.file_size
        mime_type = document.mime_type or "unknown"
        
        logger.info(f"Document from user {user_id}: {file_name} ({file_size} bytes)")
        
        # Check file size (Telegram limit is 20MB for bots)
        if file_size > 20 * 1024 * 1024:
            await update.message.reply_text(
                "❌ <b>File too large!</b>\n\n"
                "Maximum file size is 20MB. Please send a smaller file.",
                parse_mode="HTML",
            )
            return
        
        # Download the file
        await update.message.reply_text(
            f"📎 <b>File received!</b>\n\n"
            f"<b>Name:</b> {escape_html(file_name)}\n"
            f"<b>Size:</b> {file_size / 1024:.1f} KB\n"
            f"<b>Type:</b> {escape_html(mime_type)}\n\n"
            f"<i>Sending to AI for analysis...</i>",
            parse_mode="HTML",
        )
        
        # Get file from Telegram
        tg_file = await context.bot.get_file(document.file_id)
        
        # Save file metadata
        save_file_metadata(user_id, document.file_id, file_name, mime_type)
        
        # For text files, read content and send to AI
        text_extensions = [".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".xml", ".rst"]
        is_text_file = any(file_name.lower().endswith(ext) for ext in text_extensions)
        
        if is_text_file:
            try:
                # Download file content
                file_bytes = io.BytesIO()
                await tg_file.download_to_memory(file_bytes)
                file_bytes.seek(0)
                
                # Try to decode as text
                try:
                    content = file_bytes.read().decode("utf-8")[:8000]  # Limit content
                except UnicodeDecodeError:
                    content = "[Binary file - cannot read content]"
                
                # Send to AI for analysis
                model = get_user_model(user_id)
                system_prompt = get_user_system_prompt(user_id)
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Analyze this file ({file_name}):\n\n{content}"},
                ]
                
                response = await aclient.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                )
                
                analysis = response.choices[0].message.content
                await send_chunks(update.message.chat, analysis, parse_mode="HTML")
                
            except Exception as e:
                logger.error(f"Error analyzing file: {e}")
                await update.message.reply_text(
                    f"❌ <b>Analysis failed</b>\n\n"
                    f"Could not analyze file content: {escape_html(str(e)[:100])}",
                    parse_mode="HTML",
                )
        else:
            # Non-text file - AI can still analyze with vision if it's an image
            if mime_type.startswith("image/"):
                await update.message.reply_text(
                    "🖼️ <b>Image file received!</b>\n\n"
                    "Send me a message and I'll analyze this image for you.",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"📎 <b>File stored successfully!</b>\n\n"
                    f"File type: {escape_html(mime_type)}\n\n"
                    f"<i>I've saved this file. Ask me to analyze or process it!</i>",
                    parse_mode="HTML",
                )
        
    except Exception as e:
        logger.error(f"Error handling document: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ <b>Error processing file</b>\n\n{escape_html(str(e)[:200])}",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ─────────────────────────────────────────────
# Error handler
# ─────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    if update and update.effective_message:
        error_text = html.escape(str(context.error)[:300])
        try:
            await update.effective_message.reply_text(
                f"Error: {error_text}",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ─────────────────────────────────────────────
# Health Check Server (for Render.com uptime)
# ─────────────────────────────────────────────
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("OK".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging


def start_health_server(port: int = 8080):
    """Start a background HTTP server for health checks."""
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"🏥 Health check server running on port {port}")
    return server


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env file!")
        return
    if not DASHSCOPE_API_KEY:
        logger.error("DASHSCOPE_API_KEY not set in .env file!")
        return

    # Build application
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_history))
    application.add_handler(CommandHandler("context", show_context))
    application.add_handler(CommandHandler("model", show_model))
    application.add_handler(CommandHandler("prompt", set_prompt))
    application.add_handler(CommandHandler("export", export_chat))
    application.add_handler(CommandHandler("stats", user_stats))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Internet tool command handlers
    application.add_handler(CommandHandler("search", web_search_command))
    application.add_handler(CommandHandler("fetch", url_fetch_command))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("stock", stock_command))
    application.add_handler(CommandHandler("news", news_command))
    
    # CLI command handler (admin only)
    application.add_handler(CommandHandler("cli", cli_command))
    
    # Productivity command handlers
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(CommandHandler("imagine", image_command))
    application.add_handler(CommandHandler("github", github_command))
    application.add_handler(CommandHandler("gh", github_command))
    application.add_handler(CommandHandler("repo", github_repos_command))
    application.add_handler(CommandHandler("issue", github_issue_command))
    application.add_handler(CommandHandler("gitsearch", github_search_command))
    application.add_handler(CommandHandler("notion", notion_command))
    application.add_handler(CommandHandler("notionpage", notion_create_command))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^setmodel_"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(url_fetch_callback, pattern="^fetchurl_"))

    # Message handlers - MUST be registered LAST to avoid intercepting commands
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Error handler
    application.add_error_handler(error_handler)

    # Set bot commands
    async def set_commands():
        from telegram import BotCommand
        base_cmds = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show all commands"),
            BotCommand("model", "Change AI model"),
            BotCommand("prompt", "Set custom AI personality"),
            BotCommand("clear", "Clear conversation"),
            BotCommand("context", "View conversation history"),
            BotCommand("search", "Search the web"),
            BotCommand("fetch", "Fetch webpage content"),
            BotCommand("weather", "Get live weather"),
            BotCommand("stock", "Get crypto prices"),
            BotCommand("news", "Top news headlines"),
            BotCommand("cli", "Bot CLI control (admins only)"),
            BotCommand("image", "Generate AI image"),
            BotCommand("github", "View GitHub profile"),
            BotCommand("repo", "List GitHub repositories"),
            BotCommand("issue", "Get GitHub issue/PR"),
            BotCommand("gitsearch", "Search GitHub repos"),
            BotCommand("notion", "Search Notion pages"),
            BotCommand("notionpage", "Create Notion page"),
            BotCommand("export", "Download chat history"),
            BotCommand("stats", "Show usage stats"),
            BotCommand("admin", "Admin panel"),
        ]
        await application.bot.set_my_commands(base_cmds)

    asyncio.get_event_loop().run_until_complete(set_commands())

    # Start health check server (for Render.com uptime)
    start_health_server(port=8080)

    # Start polling
    logger.info("Bot is starting...")
    logger.info(f"Default model: {DEFAULT_MODEL}")
    logger.info(f"Admin IDs: {ADMIN_IDS}")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
