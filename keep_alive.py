#!/usr/bin/env python3
"""
Render.com Keep-Alive Script
Deploy as a Render Cron Job to ping the bot's health endpoint every 5 minutes.
This prevents Render's free tier from putting the bot to sleep.
"""

import os
import sys
import logging
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The URL of your Render web service (set via RENDER_URL env var)
# Or the public URL of your Render service
BOT_URL = os.getenv("RENDER_URL", "https://qwen-telegram-bot.onrender.com")


def keep_alive():
    """Ping the bot's health endpoint."""
    try:
        response = httpx.get(f"{BOT_URL}/health", timeout=10)
        if response.status_code == 200:
            logger.info("✅ Bot is alive!")
            return True
        else:
            logger.warning(f"⚠️ Unexpected status: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Bot is down: {e}")
        return False


if __name__ == "__main__":
    success = keep_alive()
    sys.exit(0 if success else 1)
