#!/usr/bin/env python3
"""
Enhanced Qwen Telegram Bot - Rebuilt from scratch
Features: Multi-model AI, streaming, images, voice, skills, persistence, admin panel
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
from datetime import datetime
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
    SKILL_COMMANDS,
    AUTO_SKILLS,
    handle_skill_command,
    check_auto_skill,
    get_skill_commands,
    send_chunks,
)
from ai_skills import AI_SKILLS, auto_detect_skill

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
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "3"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "10"))

# ─────────────────────────────────────────────
# Available models
# ─────────────────────────────────────────────
AVAILABLE_MODELS = {
    "auto": "🤖 Auto (Smart Select)",
    "qwen-turbo": "⚡ Turbo (Fast)",
    "qwen-plus": "⚖️ Plus (Balanced)",
    "qwen-max": "🏆 Max (Best Quality)",
    "qwen-long": "📚 Long (Long Context)",
    "qwen-vl-max": "👁️ VL Max (Vision)",
}

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

    # Ensure optional columns exist
    for col, col_type in [("active_skill", "TEXT"), ("temperature", "REAL"), ("max_tokens", "INTEGER")]:
        try:
            c.execute(f"ALTER TABLE user_settings ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists

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


def get_user_skill(user_id: int) -> str | None:
    """Get user's active AI skill."""
    with db_lock:
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("SELECT active_skill FROM user_settings WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            if row:
                result = dict(row).get("active_skill")
                conn.close()
                return result or None
        except sqlite3.OperationalError:
            pass  # Column doesn't exist yet
        conn.close()
    return None


def set_user_skill(user_id: int, skill_id: str):
    """Set user's active AI skill."""
    with db_lock:
        conn = get_db()
        # Ensure optional columns exist
        for col, col_type in [("active_skill", "TEXT"), ("temperature", "REAL"), ("max_tokens", "INTEGER")]:
            try:
                conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        c = conn.cursor()
        c.execute("SELECT user_id FROM user_settings WHERE user_id = ?", (user_id,))
        if c.fetchone():
            conn.execute("UPDATE user_settings SET active_skill = ? WHERE user_id = ?", (skill_id, user_id))
        else:
            conn.execute(
                "INSERT INTO user_settings (user_id, model, system_prompt, username, active_skill) VALUES (?, ?, ?, ?, ?)",
                (user_id, DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT, None, skill_id),
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
        f"💬 <b>Multi-Persona AI</b> — Code Expert, Writer, Tutor & more\n"
        f"🖼️ <b>Image Analysis</b> — Send photos for vision insights\n"
        f"🎤 <b>Voice Support</b> — Send voice notes for AI replies\n\n"
        f"📌 <b>Quick Start:</b>\n"
        f"• Just type your message\n"
        f"• /model — Choose AI model\n"
        f"• /skill — Pick an AI persona\n"
        f"• /prompt — Customize my personality\n"
        f"• /help — See all commands",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Available Commands</b>\n\n"
        "🚀 <b>Core:</b>\n"
        "  /start — Start the bot\n"
        "  /help — Show this message\n"
        "  /clear — Clear conversation\n\n"
        "🤖 <b>AI Settings:</b>\n"
        "  /model — Change AI model\n"
        "  /skill — Choose AI persona\n"
        "  /prompt [text] — Set custom personality\n"
        "  /prompt reset — Reset to default\n\n"
        "📊 <b>Tools:</b>\n"
        "  /export — Export chat as .txt\n"
        "  /stats — Your usage statistics\n"
        "  /admin — Admin panel\n\n"
        "💡 <b>Tips:</b>\n"
        "  💬 Reply to any message to use as context\n"
        "  🖼️ Send an image for vision analysis\n"
        "  🎤 Send a voice note for transcription + AI reply",
        parse_mode="HTML",
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_conversation(user_id)
    await update.message.reply_text("🗑️ <b>Conversation cleared!</b>\n\nYour chat history has been wiped. Start fresh! ✨", parse_mode="HTML")


async def show_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_model = get_user_model(user_id)

    keyboard = []
    for model_id, model_name in AVAILABLE_MODELS.items():
        checkmark = "✅ " if model_id == current_model else ""
        keyboard.append([InlineKeyboardButton(f"{checkmark}{model_name}", callback_data=f"setmodel_{model_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🤖 <b>AI Model Selection</b>\n\n"
        f"Current: <b>{html.escape(current_model)}</b>\n\n"
        f"Choose a model below:",
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
        await query.edit_message_text(
            f"✅ <b>Model Updated!</b>\n\n"
            f"Switched to: <b>{html.escape(selected_model)}</b>",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Invalid model selected.")


async def skill_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    active_skill = get_user_skill(user_id)

    keyboard = []
    row = []
    for skill_id, skill_data in AI_SKILLS.items():
        checkmark = "✅ " if skill_id == active_skill else ""
        row.append(InlineKeyboardButton(f"{checkmark}{skill_data['name']}", callback_data=f"setskill_{skill_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔄 Reset to Default", callback_data="setskill_none")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    current = AI_SKILLS[active_skill]["name"] if active_skill else "None (Default AI)"
    await update.message.reply_text(
        f"🛠️ <b>AI Skills & Personas</b>\n\n"
        f"Active: <b>{html.escape(current)}</b>\n\n"
        f"Each skill changes the AI's <b>personality</b>, <b>model</b>, and <b>temperature</b>.\n"
        f"Choose one below 👇",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def skill_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    selected = query.data.replace("setskill_", "")

    if selected == "none":
        set_user_skill(user_id, "")
        await query.edit_message_text(
            "✅ <b>AI Skill Reset!</b>\n\nBack to the default AI assistant.",
            parse_mode="HTML",
        )
        return

    if selected in AI_SKILLS:
        skill = AI_SKILLS[selected]
        set_user_skill(user_id, selected)
        await query.edit_message_text(
            f"✅ <b>Activated: {skill['name']}</b>\n\n"
            f"<i>{skill['description']}</i>\n\n"
            f"🤖 Model: <code>{skill['model']}</code>\n"
            f"🎲 Temperature: <code>{skill['temperature']}</code>",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Invalid skill.")


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

        # Determine which skill/model to use
        detected_skill_id, detected_reason = auto_detect_skill(update.message.text or "")
        manual_skill_id = get_user_skill(user_id)

        skill_config = {}
        active_skill_name = "Default AI"

        if manual_skill_id and manual_skill_id in AI_SKILLS:
            skill = AI_SKILLS[manual_skill_id]
            model = skill.get("model", DEFAULT_MODEL)
            skill_config["system_prompt"] = skill["system_prompt"]
            skill_config["temperature"] = skill.get("temperature", 0.7)
            skill_config["max_tokens"] = skill.get("max_tokens", 4096)
            active_skill_name = skill["name"]
        elif detected_skill_id and detected_skill_id in AI_SKILLS:
            skill = AI_SKILLS[detected_skill_id]
            model = skill.get("model", DEFAULT_MODEL)
            skill_config["system_prompt"] = skill["system_prompt"]
            skill_config["temperature"] = skill.get("temperature", 0.7)
            skill_config["max_tokens"] = skill.get("max_tokens", 4096)
            active_skill_name = f"{skill['name']} (auto)"
        else:
            model = get_user_model(user_id)
            skill_config["system_prompt"] = get_user_system_prompt(user_id)
            skill_config["temperature"] = 0.7
            skill_config["max_tokens"] = 4096

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

        # Auto model selection
        if model == "auto":
            model, _ = auto_select_model(user_text, has_image)
            logger.info(f"Auto-selected model: {model}")

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
        system_prompt = skill_config["system_prompt"]

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
            temperature=skill_config["temperature"],
            max_tokens=skill_config["max_tokens"],
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
                        await sent_msg.edit_text(display_text, parse_mode="HTML")
                    except Exception:
                        pass

        # Final message with footer
        footer = f"\n\n━━━━━━━━━━\n<i>🛠️ {html.escape(active_skill_name)}  •  🤖 {html.escape(model)}</i>"
        final_text = format_md(full_reply) + footer
        await sent_msg.edit_text(final_text, parse_mode="HTML")

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
# Skill command handler
# ─────────────────────────────────────────────
async def skill_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic handler for all skill commands."""
    command = update.message.text.lstrip("/").split()[0].lower()
    args = " ".join(update.message.text.split()[1:]) if len(update.message.text.split()) > 1 else ""

    response = await handle_skill_command(command, update, context, args)
    if response:
        await send_chunks(update.message.chat, response, parse_mode="HTML")


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
    application.add_handler(CommandHandler("model", show_model))
    application.add_handler(CommandHandler("prompt", set_prompt))
    application.add_handler(CommandHandler("export", export_chat))
    application.add_handler(CommandHandler("stats", user_stats))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("skill", skill_menu))

    # Register ALL skill commands dynamically
    for cmd_name in SKILL_COMMANDS:
        application.add_handler(CommandHandler(cmd_name, skill_command_handler))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^setmodel_"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(skill_callback, pattern="^setskill_"))

    # Message handler - MUST be registered LAST to avoid intercepting commands
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_message))

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
            BotCommand("export", "Download chat history"),
            BotCommand("stats", "Show usage stats"),
            BotCommand("admin", "Admin panel"),
            BotCommand("skill", "Choose AI persona"),
            BotCommand("skills", "List all available skills"),
        ]
        skill_cmds = get_skill_commands()
        all_cmds = base_cmds + skill_cmds
        await application.bot.set_my_commands(all_cmds)

    asyncio.get_event_loop().run_until_complete(set_commands())

    # Start polling
    logger.info("Bot is starting...")
    logger.info(f"Default model: {DEFAULT_MODEL}")
    logger.info(f"Admin IDs: {ADMIN_IDS}")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
