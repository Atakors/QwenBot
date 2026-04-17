#!/usr/bin/env python3
"""
Internet & File Tools for Qwen Telegram Bot
Provides: Web search, URL fetching, API integrations, file handling
"""

import html
import json
import re
import os
from pathlib import Path

import httpx
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
# Utility Helpers
# ─────────────────────────────────────────────
def escape_html(text: str) -> str:
    return html.escape(str(text), quote=False)


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


# ─────────────────────────────────────────────
# Web Search 🔍
# ─────────────────────────────────────────────
async def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web using You.com API (preferred) or DuckDuckGo fallback."""
    results = []
    
    # Try You.com API first
    you_api_key = os.getenv("YOU_API_KEY", "")
    if you_api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.ydc-index.io/search",
                    params={"query": query, "num_webpages": num_results},
                    headers={"X-API-Key": you_api_key}
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    hits = data.get("hits", [])
                    for hit in hits[:num_results]:
                        results.append({
                            "title": hit.get("title", "No title"),
                            "url": hit.get("url", ""),
                            "snippet": hit.get("snippet", "")[:200],
                        })
                    return results
        except Exception as e:
            print(f"You.com API error: {e}, falling back to DuckDuckGo")
    
    # Fallback to DuckDuckGo
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                for result in soup.select(".result")[:num_results]:
                    title_elem = result.select_one(".result__a")
                    snippet_elem = result.select_one(".result__snippet")
                    url_elem = result.select_one(".result__url")
                    
                    if title_elem:
                        results.append({
                            "title": title_elem.get_text(strip=True),
                            "url": url_elem.get("href", "") if url_elem else "",
                            "snippet": snippet_elem.get_text(strip=True)[:200] if snippet_elem else "",
                        })
    except Exception as e:
        print(f"Web search error: {e}")
    
    return results


async def search_web_formatted(query: str) -> str:
    """Search and return formatted results."""
    results = await web_search(query, num_results=6)
    
    if not results:
        return "🔍 <b>Search Results</b>\n\nNo results found. Try a different query."
    
    text = f"🔍 <b>Search: {escape_html(query)}</b>\n\n"
    for i, r in enumerate(results, 1):
        text += f"<b>{i}.</b> {escape_html(r['title'])}\n"
        if r['snippet']:
            text += f"   <i>{escape_html(r['snippet'])}...</i>\n"
        if r['url']:
            text += f"   <u>{escape_html(r['url'][:50])}</u>\n"
        text += "\n"
    
    return text.strip()


# ─────────────────────────────────────────────
# URL Fetching 🌐
# ─────────────────────────────────────────────
async def fetch_url_content(url: str, max_length: int = 5000) -> dict:
    """Fetch and extract main content from a URL."""
    result = {
        "success": False,
        "title": "",
        "content": "",
        "error": "",
    }
    
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
            
            if resp.status_code != 200:
                result["error"] = f"HTTP {resp.status_code}"
                return result
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Extract title
            title_tag = soup.find("title")
            result["title"] = title_tag.get_text(strip=True)[:200] if title_tag else "No title"
            
            # Remove script, style, nav, header, footer
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                tag.decompose()
            
            # Get main content
            main = soup.find("main") or soup.find("article") or soup.body
            if main:
                text = main.get_text(separator="\n", strip=True)
                # Clean up whitespace
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                result["content"] = "\n".join(lines)[:max_length]
            else:
                result["content"] = soup.get_text(separator=" ", strip=True)[:max_length]
            
            result["success"] = True
            
    except httpx.TimeoutException:
        result["error"] = "Request timed out"
    except Exception as e:
        result["error"] = str(e)[:100]
    
    return result


async def summarize_url(url: str) -> str:
    """Fetch URL and return formatted summary."""
    data = await fetch_url_content(url)
    
    if not data["success"]:
        return f"❌ <b>Failed to fetch URL</b>\n\nError: {escape_html(data['error'])}"
    
    content_preview = data["content"][:1000]
    if len(data["content"]) > 1000:
        content_preview += "\n\n...(content truncated)..."
    
    text = (
        f"🌐 <b>Page Summary</b>\n\n"
        f"<b>Title:</b> {escape_html(data['title'])}\n"
        f"<b>URL:</b> <u>{escape_html(url[:60])}</u>\n\n"
        f"<b>Content Preview:</b>\n"
        f"<i>{escape_html(content_preview)}</i>\n\n"
        f"<i>Tip: Forward this page to the bot for AI analysis!</i>"
    )
    
    return text


# ─────────────────────────────────────────────
# Weather API 🌤️
# ─────────────────────────────────────────────
async def get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"https://wttr.in/{city.replace(' ', '+')}?format=j1")
            resp.raise_for_status()
            data = resp.json()
        
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        
        temp_c = current.get("temp_C", "N/A")
        feels_c = current.get("FeelsLikeC", "N/A")
        desc = current.get("weatherDesc", [{}])[0].get("value", "N/A")
        humidity = current.get("humidity", "N/A")
        wind_kmph = current.get("windspeedKmph", "N/A")
        visibility = current.get("visibility", "N/A")
        
        area_name = area.get("areaName", [{}])[0].get("value", city)
        country = area.get("country", [{}])[0].get("value", "")
        
        emoji_map = {
            "sunny": "☀️", "clear": "🌙", "partly cloudy": "⛅",
            "cloudy": "☁️", "overcast": "☁️", "rain": "🌧️",
            "mist": "🌫️", "fog": "🌫️", "snow": "❄️", "thunder": "⛈️",
        }
        emoji = "🌤️"
        for key, val in emoji_map.items():
            if key in desc.lower():
                emoji = val
                break
        
        return (
            f"{emoji} <b>Weather in {escape_html(area_name)}, {escape_html(country)}</b>\n\n"
            f"🌡️ Temperature: <code>{temp_c}°C</code> (feels like {feels_c}°C)\n"
            f"📝 {escape_html(desc)}\n"
            f"💧 Humidity: <code>{humidity}%</code>\n"
            f"💨 Wind: <code>{wind_kmph} km/h</code>\n"
            f"👁️ Visibility: <code>{visibility} km</code>"
        )
    except Exception as e:
        return f"❌ Could not fetch weather: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# Stock/Crypto Prices 📈
# ─────────────────────────────────────────────
async def get_crypto_price(symbol: str) -> str:
    """Get cryptocurrency price from CoinGecko."""
    crypto_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "ADA": "cardano", "XRP": "ripple", "DOGE": "dogecoin",
        "BNB": "binancecoin", "DOT": "polkadot", "MATIC": "matic-network",
        "LINK": "chainlink", "AVAX": "avalanche-2", "SHIB": "shiba-inu",
    }
    
    coin_id = crypto_map.get(symbol.upper())
    if not coin_id:
        return f"❌ Unknown crypto symbol: {escape_html(symbol)}\n\nSupported: BTC, ETH, SOL, ADA, XRP, DOGE, BNB, DOT, MATIC, LINK, AVAX, SHIB"
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            )
            resp.raise_for_status()
            data = resp.json()
        
        coin_data = data.get(coin_id, {})
        price = coin_data.get("usd", 0)
        change = coin_data.get("usd_24h_change", 0)
        
        emoji = "🟢" if change >= 0 else "🔴"
        
        return (
            f"📈 <b>{symbol.upper()}/USD</b>\n\n"
            f"💰 Price: <b>${price:,.2f}</b>\n"
            f"{emoji} 24h Change: <code>{change:+.2f}%</code>"
        )
    except Exception as e:
        return f"❌ Could not fetch price: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# News Headlines 📰
# ─────────────────────────────────────────────
async def get_news() -> str:
    """Get top news headlines from BBC RSS."""
    try:
        import feedparser
        feed = feedparser.parse("https://feeds.bbci.co.uk/news/rss.xml")
        
        if not feed.entries:
            return "❌ Could not fetch news."
        
        text = "📰 <b>BBC Top Headlines</b>\n\n"
        for i, entry in enumerate(feed.entries[:10], 1):
            title = entry.get("title", "No title")
            summary = ""
            if entry.get("summary"):
                summary = re.sub(r"<[^>]+>", "", entry.summary)[:120]
            
            text += f"<b>{i}.</b> {escape_html(title)}\n"
            if summary:
                text += f"   <i>{escape_html(summary)}...</i>\n"
            text += "\n"
        
        return text.strip()
    except ImportError:
        return "📰 Install feedparser: pip install feedparser"
    except Exception as e:
        return f"❌ Could not fetch news: {escape_html(str(e)[:100])}"


# ─────────────────────────────────────────────
# File Storage Helpers 📁
# ─────────────────────────────────────────────
def get_file_path(file_id: str, user_id: int) -> Path:
    """Get path for storing user file."""
    user_dir = Path("bot_files") / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{file_id[:16]}.dat"


def save_file_metadata(user_id: int, file_id: str, file_name: str, file_type: str) -> dict:
    """Save file metadata to JSON."""
    metadata_dir = Path("bot_files") / str(user_id) / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    metadata_file = metadata_dir / f"{file_id[:16]}.json"
    metadata = {
        "file_id": file_id,
        "file_name": file_name,
        "file_type": file_type,
        "user_id": user_id,
    }
    
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    
    return metadata


def get_file_metadata(user_id: int, file_id: str) -> dict | None:
    """Get file metadata."""
    metadata_file = Path("bot_files") / str(user_id) / "metadata" / f"{file_id[:16]}.json"
    
    if metadata_file.exists():
        with open(metadata_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# ─────────────────────────────────────────────
# Tool Detection
# ─────────────────────────────────────────────
TOOL_PATTERNS = [
    (r"/search\s+(.+)", "web_search"),
    (r"/fetch\s+(https?://\S+)", "url_fetch"),
    (r"/weather\s+(.+)", "weather"),
    (r"/(?:stock|crypto)\s+(\w+)", "crypto"),
    (r"/news", "news"),
    (r"https?://\S+", "url_in_message"),
]


def detect_tool(text: str) -> tuple[str | None, str | None]:
    """Detect which tool to use from message text.
    Returns (tool_name, argument) or (None, None)."""
    for pattern, tool_name in TOOL_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            return tool_name, match.group(1) if match.lastindex else ""
    return None, None
