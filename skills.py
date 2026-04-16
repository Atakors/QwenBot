#!/usr/bin/env python3
"""
Minimal Skills Module for Qwen Telegram Bot
Only core helper functions - no utility skills.
"""

import html
import re

# ─────────────────────────────────────────────
# Skill Registry (empty - no utility skills)
# ─────────────────────────────────────────────
SKILL_COMMANDS = {}
AUTO_SKILLS = []


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


async def send_chunks(chat, text: str, parse_mode: str = "HTML"):
    """Send a potentially long message by splitting it."""
    for chunk in split_message(text):
        await chat.send_message(chunk, parse_mode=parse_mode)


# ─────────────────────────────────────────────
# Main Router (empty - no skills)
# ─────────────────────────────────────────────
async def handle_skill_command(command: str, update, context, args: str) -> str | None:
    """Handle a skill command. Returns response text or None if not a skill."""
    return None


def check_auto_skill(text: str) -> str | None:
    """Check if text matches an auto skill pattern. Returns response or None."""
    return None


def get_skill_commands() -> list:
    """Get all skill commands for registration."""
    from telegram import BotCommand
    return []
