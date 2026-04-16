#!/usr/bin/env python3
"""
CLI Controller for Qwen Telegram Bot
Allows admins to run bot commands via Telegram
"""

import asyncio
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx


# ─────────────────────────────────────────────
# CLI Commands Registry
# ─────────────────────────────────────────────
CLI_COMMANDS = {}


def register_cli(name: str, description: str, admin_only: bool = True):
    """Register a CLI command."""
    def decorator(func):
        CLI_COMMANDS[name] = {
            "func": func,
            "description": description,
            "admin_only": admin_only,
        }
        return func
    return decorator


# ─────────────────────────────────────────────
# CLI Command Implementations
# ─────────────────────────────────────────────
@register_cli("status", "🟢 Check bot status and health", admin_only=False)
async def cli_status():
    """Check bot status."""
    return {
        "status": "online",
        "uptime": _get_uptime(),
        "python_version": sys.version.split()[0],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@register_cli("models", "🤖 List available AI models", admin_only=False)
async def cli_models():
    """List available models from API."""
    try:
        api_base = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{api_base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_list = [m.get("id", "unknown") for m in models if m.get("id", "").startswith("qwen")]
                return {
                    "available": True,
                    "models": model_list,
                    "count": len(model_list),
                }
    except Exception as e:
        return {"available": False, "error": str(e)[:200]}
    
    return {"available": False, "error": "Could not fetch models"}


@register_cli("restart", "🔄 Restart the bot", admin_only=True)
async def cli_restart():
    """Restart the bot (requires Docker or systemd)."""
    try:
        # Try Docker restart
        result = subprocess.run(
            ["docker", "compose", "restart"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout or result.stderr or "Restarting...",
        }
    except Exception as e:
        return {
            "success": False,
            "output": f"Cannot restart via Docker: {str(e)[:200]}\n\nManual restart required.",
        }


@register_cli("logs", "📋 View recent bot logs", admin_only=True)
async def cli_logs(lines: int = 50):
    """View recent logs."""
    try:
        result = subprocess.run(
            ["docker", "compose", "logs", "--tail", str(lines)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent
        )
        return {
            "success": True,
            "logs": result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout,
        }
    except Exception as e:
        return {"success": False, "logs": f"Could not fetch logs: {str(e)[:200]}"}


@register_cli("config", "⚙️ View current configuration", admin_only=True)
async def cli_config():
    """View bot configuration."""
    config = {
        "model": os.getenv("QWEN_MODEL", "auto"),
        "api_base": os.getenv("DASHSCOPE_API_BASE", "not set")[:50] + "...",
        "rate_limit": os.getenv("RATE_LIMIT_SECONDS", "3"),
        "max_history": os.getenv("MAX_HISTORY", "10"),
        "admin_ids": "configured" if os.getenv("ADMIN_IDS") else "not set",
        "webhook": os.getenv("WEBHOOK_URL", "polling mode"),
    }
    return config


@register_cli("stats", "📊 View API usage statistics", admin_only=False)
async def cli_stats():
    """View usage stats from database."""
    try:
        import sqlite3
        db_path = Path("bot_data.db")
        
        if not db_path.exists():
            return {"error": "Database not found"}
        
        conn = sqlite3.connect(str(db_path))
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
            "users": total_users,
            "messages": total_messages,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model_usage": model_usage,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


@register_cli("clear", "🗑️ Clear conversation for a user (admin only)", admin_only=True)
async def cli_clear(user_id: str = None):
    """Clear conversation history."""
    if not user_id:
        return {"error": "Usage: /cli clear <user_id>"}
    
    try:
        import sqlite3
        db_path = Path("bot_data.db")
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,))
        count = c.fetchone()[0]
        
        c.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "cleared": count,
            "user_id": user_id,
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@register_cli("users", "👥 List active users", admin_only=True)
async def cli_users():
    """List all active users."""
    try:
        import sqlite3
        db_path = Path("bot_data.db")
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        c.execute("SELECT DISTINCT user_id, username FROM user_settings ORDER BY user_id")
        users = c.fetchall()
        
        conn.close()
        
        user_list = [{"id": u[0], "username": u[1] or "N/A"} for u in users]
        return {
            "count": len(user_list),
            "users": user_list[:50],  # Limit to 50
        }
    except Exception as e:
        return {"error": str(e)[:200]}


@register_cli("exec", "⚡ Run shell command (DANGER - admin only)", admin_only=True)
async def cli_exec(command: str):
    """Execute shell command (DANGEROUS - use with caution)."""
    if not command:
        return {"error": "Usage: /cli exec <command>"}
    
    # Block dangerous commands
    dangerous = ["rm -rf", "sudo", "chmod 777", "dd if=", ":(){:|:&}", "mkfs", "> /dev/"]
    for d in dangerous:
        if d in command:
            return {"error": f"⚠️ Dangerous command blocked: {d}"}
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:1000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out (>60s)"}
    except Exception as e:
        return {"error": str(e)[:200]}


@register_cli("help", "📖 Show available CLI commands", admin_only=False)
async def cli_help():
    """Show CLI help."""
    commands = []
    for name, data in CLI_COMMANDS.items():
        commands.append({
            "command": name,
            "description": data["description"],
            "admin": data["admin_only"],
        })
    return {"commands": commands}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _get_uptime() -> str:
    """Get bot uptime."""
    try:
        # Try to read uptime from file
        uptime_file = Path(".bot_start_time")
        if uptime_file.exists():
            start = float(uptime_file.read_text())
            delta = time.time() - start
            hours = int(delta // 3600)
            minutes = int((delta % 3600) // 60)
            return f"{hours}h {minutes}m"
    except Exception:
        pass
    return "unknown"


# ─────────────────────────────────────────────
# CLI Runner
# ─────────────────────────────────────────────
async def run_cli_command(cmd_name: str, args: str = "") -> dict:
    """Run a CLI command and return result."""
    if cmd_name not in CLI_COMMANDS:
        return {"error": f"Unknown command: {cmd_name}"}
    
    cmd_data = CLI_COMMANDS[cmd_name]
    func = cmd_data["func"]
    
    try:
        if args:
            result = await func(args)
        else:
            result = await func()
        return {"command": cmd_name, "result": result}
    except Exception as e:
        return {"command": cmd_name, "error": str(e)[:300]}


def format_cli_result(cmd: str, result: dict) -> str:
    """Format CLI result for Telegram."""
    text = f"🖥️ <b>CLI: {html.escape(cmd)}</b>\n\n"
    
    if "error" in result:
        text += f"❌ <b>Error:</b> {html.escape(str(result['error']))}"
        return text
    
    if "result" in result:
        data = result["result"]
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, indent=2)
                text += f"<b>{html.escape(str(key))}:</b> <code>{html.escape(str(value))}</code>\n"
        elif isinstance(data, list):
            for item in data:
                text += f"• {html.escape(str(item))}\n"
        else:
            text += html.escape(str(data))
    
    return text
