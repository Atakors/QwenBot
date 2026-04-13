#!/usr/bin/env python3
"""
Enhanced Skills Module for Qwen Telegram Bot
Includes: Weather, News, Calculator, Web Search, Image Gen, Reminders, Stocks, Translate, Fun
"""

import asyncio
import html
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

import httpx

# ─────────────────────────────────────────────
# Skill Registry
# ─────────────────────────────────────────────
SKILLS = {}
SKILL_COMMANDS = {}  # command_name → (handler, description)
AUTO_SKILLS = []  # (pattern, handler, description)


def register_command(name: str, description: str):
    """Register a slash command skill."""
    def decorator(func):
        SKILL_COMMANDS[name] = (func, description)
        return func
    return decorator


def register_auto(pattern: str, description: str):
    """Register an auto-detect skill (keyword pattern)."""
    def decorator(func):
        AUTO_SKILLS.append((re.compile(pattern, re.IGNORECASE), func, description))
        return func
    return decorator


# ─────────────────────────────────────────────
# Utility Helpers
# ─────────────────────────────────────────────
def escape_html(text: str) -> str:
    return html.escape(str(text), quote=False)

def format_md(text: str) -> str:
    text = html.escape(str(text), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"```(.+?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text

def split_message(text: str, limit: int = 4096) -> list[str]:
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


async def send_chunks(chat, text: str, parse_mode: str = "HTML"):
    for chunk in split_message(text):
        await chat.send_message(chunk, parse_mode=parse_mode)


# ─────────────────────────────────────────────
# Skill: Weather 🌤️
# ─────────────────────────────────────────────
@register_command("weather", "🌤️ Get live weather for any city")
async def skill_weather(update, context, args: str):
    if not args:
        return "🌤️ Usage: /weather <city>\nExample: /weather Paris"

    city = args.strip()
    url = f"https://wttr.in/{city.replace(' ', '+')}?format=j1"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        current = data["current_condition"][0]
        temp = current["temp_C"]
        feels = current["FeelsLikeC"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind = current["windspeedKmph"]
        vis = current.get("visibility", "N/A")
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", city)
        country = area.get("country", [{}])[0].get("value", "")

        emoji_map = {"Sunny": "☀️", "Clear": "🌙", "Partly cloudy": "⛅",
                     "Cloudy": "☁️", "Overcast": "☁️", "Rain": "🌧️",
                     "Mist": "🌫️", "Fog": "🌫️", "Snow": "❄️", "Thunder": "⛈️"}
        emoji = next((v for k, v in emoji_map.items() if k.lower() in desc.lower()), "🌤️")

        return (
            f"{emoji} <b>Weather in {escape_html(area_name)}, {escape_html(country)}</b>\n\n"
            f"🌡️ Temp: <code>{temp}°C</code> (feels like {feels}°C)\n"
            f"📝 {escape_html(desc)}\n"
            f"💧 Humidity: <code>{humidity}%</code>\n"
            f"💨 Wind: <code>{wind} km/h</code>\n"
            f"👁️ Visibility: <code>{vis} km</code>"
        )
    except Exception as e:
        return f"❌ Could not fetch weather: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: News 📰
# ─────────────────────────────────────────────
@register_command("news", "📰 Get top headlines")
async def skill_news(update, context, args: str):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Use free news RSS or API
            resp = await client.get(
                "https://newsapi.org/v2/top-headlines",
                params={"language": "en", "pageSize": 10,
                        "apiKey": os.getenv("NEWS_API_KEY", "demo")},
            )
            data = resp.json()

        if data.get("status") != "ok" or not data.get("articles"):
            # Fallback: use BBC RSS feed
            return await _fetch_rss_news()

        articles = data["articles"][:8]
        text = "📰 <b>Top Headlines</b>\n\n"
        for i, a in enumerate(articles, 1):
            title = a.get("title", "No title")
            source = a.get("source", {}).get("name", "Unknown")
            text += f"<b>{i}.</b> {escape_html(title)}\n"
            text += f"   <i>— {escape_html(source)}</i>\n\n"
        text += "<i>💡 Set NEWS_API_KEY in .env for full access</i>"
        return text.strip()
    except Exception:
        return await _fetch_rss_news()


async def _fetch_rss_news():
    try:
        import feedparser
    except ImportError:
        return "📰 Could not fetch news. Install feedparser: pip install feedparser"
    try:
        import feedparser as fp
        feed = fp.parse("https://feeds.bbci.co.uk/news/rss.xml")
        text = "📰 <b>BBC Top Headlines</b>\n\n"
        for i, entry in enumerate(feed.entries[:10], 1):
            text += f"<b>{i}.</b> {escape_html(entry.title)}\n"
            if entry.get("summary"):
                summary = re.sub(r"<[^>]+>", "", entry.summary)[:120]
                text += f"   <i>{escape_html(summary)}...</i>\n"
            text += "\n"
        return text.strip()
    except Exception as e:
        return f"❌ Could not fetch news: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Calculator 🔢
# ─────────────────────────────────────────────
@register_command("calc", "🔢 Evaluate math expressions")
@register_command("calculate", "🔢 Evaluate math expressions")
async def skill_calc(update, context, args: str):
    if not args:
        return "🔢 Usage: /calc <expression>\nExample: /calc 2 + 2 * 3"

    expr = args.strip()
    # Allow only safe characters
    safe = re.sub(r"[0-9+\-*/().%^×÷√πe\s]", "", expr)
    if safe:
        return "❌ Invalid expression. Only numbers, +, -, *, /, ^, %, ( ) allowed."

    try:
        safe_expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
        safe_expr = safe_expr.replace("π", "3.14159265").replace("e", "2.71828182")
        result = eval(safe_expr, {"__builtins__": {}}, {"abs": abs, "pow": pow})
        return f"🔢 <code>{escape_html(expr)}</code>\n\n= <b>{result}</b>"
    except Exception as e:
        return f"❌ Error: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Web Search 🌐
# ─────────────────────────────────────────────
@register_command("search", "🌐 Search the web for real-time info")
async def skill_search(update, context, args: str):
    if not args:
        return "🌐 Usage: /search <query>\nExample: /search latest AI news"

    query = args.strip()
    # Try web_search tool if available, else use public search
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # Use DuckDuckGo instant answers (no API key needed)
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select(".result__a")
            snippets = soup.select(".result__snippet")

            text = f"🔍 <b>Search: {escape_html(query)}</b>\n\n"
            for i, (a, s) in enumerate(zip(results[:6], snippets[:6]), 1):
                title = a.get_text(strip=True)
                url = a.get("href", "")
                snippet = s.get_text(strip=True)[:150] if s else ""
                if title:
                    text += f"<b>{i}.</b> {escape_html(title)}\n"
                    if snippet:
                        text += f"   <i>{escape_html(snippet)}...</i>\n"
                    text += "\n"

            if len(results) == 0:
                text += "No results found. Try a different query."
            return text.strip()
    except ImportError:
        return "🌐 Install beautifulsoup4: pip install beautifulsoup4"
    except Exception as e:
        return f"❌ Search failed: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Image Generation 🖼️
# ─────────────────────────────────────────────
@register_command("imagine", "🖼️ Generate an image from text")
@register_command("img", "🖼️ Generate an image from text")
async def skill_imagine(update, context, args: str):
    if not args:
        return "🖼️ Usage: /imagine <description>\nExample: /imagine a sunset over mountains"

    prompt = args.strip()
    # Use Gemini image generation (if available) or notify
    try:
        from openai import OpenAI
        # Try Gemini via OpenAI-compatible endpoint
        gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_api_key:
            client = OpenAI(api_key=gemini_api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            # Gemini doesn't support image gen via OpenAI compat, fallback
            return "🖼️ Image generation requires a dedicated API key.\nSet GEMINI_API_KEY or use a supported provider."

        return (
            f"🖼️ <b>Image Request:</b> <i>{escape_html(prompt)}</i>\n\n"
            "Image generation needs an external API. "
            "Set <code>GEMINI_API_KEY</code> in .env to enable.\n"
            "Alternatively, I can describe your image idea instead! 🎨"
        )
    except Exception as e:
        return f"❌ Image generation failed: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Reminder ⏰
# ─────────────────────────────────────────────
ACTIVE_REMINDERS = {}

@register_command("remind", "⏰ Set a reminder (e.g. /remind 5m drink water)")
async def skill_remind(update, context, args: str):
    if not args:
        return (
            "⏰ Usage: /remind <time> <message>\n"
            "Time formats: 5m, 1h, 2d, 30s\n"
            "Example: /remind 10m take a break"
        )

    match = re.match(r"(\d+)([smhd])\s+(.+)", args.strip())
    if not match:
        return "❌ Invalid format. Use: /remind 5m message"

    value, unit, message = match.groups()
    value = int(value)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = value * multipliers[unit]

    if seconds > 86400 * 7:  # Max 7 days
        return "❌ Maximum reminder time is 7 days."

    user_id = update.effective_user.id
    reminder_id = f"{user_id}_{int(time.time())}"

    # Schedule reminder
    async def trigger_reminder():
        try:
            await update.effective_user.send_message(
                f"⏰ <b>Reminder!</b>\n\n{escape_html(message)}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.error(f"Reminder failed: {e}")
        ACTIVE_REMINDERS.pop(reminder_id, None)

    # Store reminder
    ACTIVE_REMINDERS[reminder_id] = {
        "message": message,
        "time": datetime.now().strftime("%H:%M"),
        "task": asyncio.create_task(_delay(seconds, trigger_reminder)),
    }

    unit_names = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return f"⏰ Reminder set for {value} {unit_names[unit]}:\n<i>{escape_html(message)}</i>"


async def _delay(seconds: int, callback):
    await asyncio.sleep(seconds)
    await callback()


# ─────────────────────────────────────────────
# Skill: Stock/Crypto 📈
# ─────────────────────────────────────────────
@register_command("stock", "📈 Get live stock or crypto prices")
async def skill_stock(update, context, args: str):
    if not args:
        return "📈 Usage: /stock <symbol>\nExamples: /stock AAPL, /stock BTC, /stock ETH"

    symbol = args.strip().upper()
    try:
        # Use CoinGecko for crypto (free, no API key)
        crypto_map = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
                       "ADA": "cardano", "XRP": "ripple", "DOGE": "dogecoin",
                       "BNB": "binancecoin", "DOT": "polkadot", "MATIC": "matic-network",
                       "LINK": "chainlink", "AVAX": "avalanche-2", "SHIB": "shiba-inu"}

        if symbol in crypto_map:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": crypto_map[symbol], "vs_currencies": "usd",
                            "include_24hr_change": "true"},
                )
                data = resp.json()
                coin = data.get(crypto_map[symbol], {})
                price = coin.get("usd", 0)
                change = coin.get("usd_24h_change", 0)
                emoji = "🟢" if change >= 0 else "🔴"
                return (
                    f"📈 <b>{symbol}/USD</b>\n\n"
                    f"💰 Price: <b>${price:,.2f}</b>\n"
                    f"{emoji} 24h: <code>{change:+.2f}%</code>"
                )

        # For stocks, use Yahoo Finance (scraping-based, free)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]
            prev = meta["chartPreviousClose"]
            change = ((price - prev) / prev) * 100
            emoji = "🟢" if change >= 0 else "🔴"
            return (
                f"📈 <b>{symbol}</b>\n\n"
                f"💰 Price: <b>${price:,.2f}</b>\n"
                f"{emoji} Change: <code>{change:+.2f}%</code>"
            )
    except Exception as e:
        return f"❌ Could not fetch {symbol}: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Translate 🌍
# ─────────────────────────────────────────────
@register_command("translate", "🌍 Translate text (e.g. /translate en fr Hello)")
@register_command("tr", "🌍 Quick translate text")
async def skill_translate(update, context, args: str):
    if not args or len(args.strip().split()) < 3:
        return "🌍 Usage: /translate <from> <to> <text>\nExample: /translate en fr Hello world"

    parts = args.strip().split(None, 2)
    if len(parts) < 3:
        return "❌ Need source lang, target lang, and text."

    src, tgt, text = parts
    try:
        # Use MyMemory free translation API
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": f"{src}|{tgt}"},
            )
            data = resp.json()

        if data.get("responseStatus") == 200:
            translated = data["responseData"]["translatedText"]
            return (
                f"🌍 <b>Translation</b> ({src} → {tgt})\n\n"
                f"<i>{escape_html(text)}</i>\n\n"
                f"➡️ <b>{escape_html(translated)}</b>"
            )
        else:
            return f"❌ Translation failed: {escape_html(data.get('responseDetails', 'Unknown error'))}"
    except Exception as e:
        return f"❌ Translation failed: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Skill: Fun 🎲
# ─────────────────────────────────────────────
@register_command("roll", "🎲 Roll a dice (optionally /roll 20)")
async def skill_roll(update, context, args: str):
    sides = 6
    if args and args.strip().isdigit():
        sides = min(int(args.strip()), 10000)
    result = random.randint(1, sides)
    dice_emoji = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    emoji = dice_emoji[result - 1] if result <= 6 else "🎲"
    return f"{emoji} Rolled a <b>{sides}-sided dice</b>: <b>{result}</b>"


@register_command("flip", "🪙 Flip a coin")
async def skill_flip(update, context, args: str):
    result = random.choice(["Heads", "Tails"])
    emoji = "👑" if result == "Heads" else "🌿"
    return f"🪙 Coin flip: <b>{emoji} {result}</b>"


@register_command("joke", "😂 Get a random joke")
async def skill_joke(update, context, args: str):
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
        "I told my computer I needed a break. Now it won't stop sending me Kit-Kat ads. 🍫",
        "Why was the JavaScript developer sad? Because he didn't Node how to Express himself. 😢",
        "There are only 10 types of people: those who understand binary and those who don't. 🤓",
        "A SQL query walks into a bar, sees two tables, and asks... 'Can I JOIN you?' 🍻",
        "Why do Java developers wear glasses? Because they can't C#! 👓",
        "What's a programmer's favorite hangout place? Foo Bar! 🍺",
        "My code doesn't work. I have no idea why.\nMy code works. I have no idea why. 🤷",
        "I changed my password to 'incorrect'. Now when I forget it, the system says: 'Your password is incorrect.' 🔑",
        "6 out of 7 dwarfs aren't Happy. 😐",
    ]
    return f"😂 {random.choice(jokes)}"


# ─────────────────────────────────────────────
# Skill: /skills - List all skills
# ─────────────────────────────────────────────
@register_command("skills", "📋 List all available skills")
async def skill_list(update, context, args: str):
    text = "🛠️ <b>Available Skills</b>\n\n"
    text += "<b>Slash Commands:</b>\n"
    for cmd, (_, desc) in sorted(SKILL_COMMANDS.items()):
        text += f"  /{cmd} — {desc}\n"
    text += "\n<b>Auto-detect:</b>\n"
    text += "  🤖 Smart replies when you say 'calculate', 'translate', etc.\n"
    return text.strip()


# ─────────────────────────────────────────────
# Auto-detect: intercept messages that look like skills
# ─────────────────────────────────────────────
@register_auto(r"^(?:calculate|calc|what is|solve)\s+.+", "Auto-calculate math expressions")
async def auto_calc(text: str):
    expr = re.sub(r"^(?:calculate|calc|what is|solve)\s+", "", text, flags=re.IGNORECASE)
    return await skill_calc(None, None, expr)


@register_auto(r"^translate\s+(?:to\s+)?(\w+)\s+(.+)", "Auto-translate text")
async def auto_translate(text: str):
    match = re.match(r"^translate\s+(?:to\s+)?(\w+)\s+(.+)", text, re.IGNORECASE)
    if match:
        tgt, msg = match.groups()
        return await skill_translate(None, None, f"en {tgt} {msg}")
    return None


# ─────────────────────────────────────────────
# Main Router
# ─────────────────────────────────────────────
async def handle_skill_command(command: str, update, context, args: str) -> str | None:
    """Handle a skill command. Returns response text or None if not a skill."""
    if command in SKILL_COMMANDS:
        handler, _ = SKILL_COMMANDS[command]
        try:
            result = handler(update, context, args)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as e:
            return f"❌ Skill error: {escape_html(str(e)[:100])}"
    return None


def check_auto_skill(text: str) -> str | None:
    """Check if text matches an auto skill pattern. Returns response or None."""
    for pattern, handler, _ in AUTO_SKILLS:
        if pattern.match(text):
            try:
                result = handler(text)
                if asyncio.iscoroutine(result):
                    return asyncio.get_event_loop().run_until_complete(result)
                return result
            except Exception:
                return None
    return None


def get_skill_commands() -> list:
    """Get all skill commands for registration."""
    from telegram import BotCommand
    return [BotCommand(cmd, desc) for cmd, (_, desc) in SKILL_COMMANDS.items() if cmd != "skills"]
