#!/usr/bin/env python3
"""
Productivity Integrations for Qwen Telegram Bot
Includes: GitHub, Notion, Image Generation, Google Drive, Calendar, Tasks
"""

import asyncio
import html
import os
import re
import base64
from pathlib import Path
from datetime import datetime

import httpx
from openai import OpenAI


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
GOOGLE_DRIVE_FOLDER = os.getenv("GOOGLE_DRIVE_FOLDER", "")
IMAGE_GENERATION_MODEL = os.getenv("IMAGE_MODEL", "dall-e-3")


# ─────────────────────────────────────────────
# Image Generation 🎨
# ─────────────────────────────────────────────
async def generate_image(prompt: str, size: str = "1024x1024") -> dict:
    """Generate image using Alibaba DashScope Wanx API."""
    result = {"success": False, "url": None, "error": None}
    
    try:
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            result["error"] = "DASHSCOPE_API_KEY not configured"
            return result
        
        # Use Wanx 2.7 for image generation via DashScope SDK-style API
        async with httpx.AsyncClient(timeout=120) as client:
            # Submit generation task
            submit_resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": "wan2.7-image-pro",
                    "input": {"prompt": prompt},
                    "parameters": {
                        "size": "1024x1024",
                        "n": 1,
                        "style": "<auto>",
                    },
                },
            )
            
            if submit_resp.status_code != 200:
                result["error"] = f"Submit failed: {submit_resp.status_code} - {submit_resp.text[:200]}"
                return result
            
            submit_data = submit_resp.json()
            task_id = submit_data.get("output", {}).get("task_id")
            
            if not task_id:
                result["error"] = "No task_id returned from API"
                return result
            
            # Poll for result
            for attempt in range(30):  # Wait up to 90 seconds
                await asyncio.sleep(3)
                
                status_resp = await client.get(
                    f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    task_status = status_data.get("output", {}).get("task_status", "")
                    
                    if task_status == "SUCCEEDED":
                        # Get image URL from output
                        output = status_data.get("output", {})
                        if "results" in output:
                            result["success"] = True
                            result["url"] = output["results"][0].get("url")
                            return result
                        elif "task_output" in output:
                            task_output = output.get("task_output", {})
                            if "url" in task_output:
                                result["success"] = True
                                result["url"] = task_output["url"]
                                return result
                    elif task_status in ["FAILED", "CANCELED"]:
                        result["error"] = f"Task failed: {status_data.get('output', {}).get('message', 'Unknown error')}"
                        return result
            
            result["error"] = "Generation timed out (took too long)"
            return result
        
    except Exception as e:
        result["error"] = str(e)[:200]
        return result


# ─────────────────────────────────────────────
# GitHub Integration 🐙
# ─────────────────────────────────────────────
async def github_get_user_info(username: str = None) -> dict:
    """Get GitHub user info."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        async with httpx.AsyncClient(timeout=15) as client:
            user = username or "user"
            url = f"https://api.github.com/users/{user}" if username else "https://api.github.com/user"
            resp = await client.get(url, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "login": data.get("login"),
                    "name": data.get("name"),
                    "public_repos": data.get("public_repos"),
                    "followers": data.get("followers"),
                    "following": data.get("following"),
                    "avatar": data.get("avatar_url"),
                    "bio": data.get("bio"),
                }
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def github_list_repos(username: str = None, limit: int = 10) -> dict:
    """List GitHub repositories."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        async with httpx.AsyncClient(timeout=15) as client:
            user = username or "user"
            url = f"https://api.github.com/users/{user}/repos" if username else "https://api.github.com/user/repos"
            resp = await client.get(f"{url}?sort=updated&per_page={limit}", headers=headers)
            
            if resp.status_code == 200:
                repos = resp.json()
                repo_list = []
                for repo in repos[:limit]:
                    repo_list.append({
                        "name": repo.get("full_name"),
                        "description": repo.get("description", "No description"),
                        "stars": repo.get("stargazers_count"),
                        "language": repo.get("language"),
                        "updated": repo.get("updated_at")[:10],
                        "url": repo.get("html_url"),
                    })
                return {"success": True, "repos": repo_list}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def github_get_issue(repo: str, issue_number: str) -> dict:
    """Get GitHub issue/PR details."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "number": data.get("number"),
                    "title": data.get("title"),
                    "state": data.get("state"),
                    "user": data.get("user", {}).get("login"),
                    "body": data.get("body", "")[:500],
                    "comments": data.get("comments"),
                    "is_pr": "pull_request" in data,
                }
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def github_search(query: str, limit: int = 5) -> dict:
    """Search GitHub repositories."""
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.github.com/search/repositories?q={query}&per_page={limit}",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                repos = []
                for item in data.get("items", [])[:limit]:
                    repos.append({
                        "name": item.get("full_name"),
                        "description": item.get("description", "No description")[:150],
                        "stars": item.get("stargazers_count"),
                        "language": item.get("language"),
                        "url": item.get("html_url"),
                    })
                return {"success": True, "repos": repos, "total": data.get("total_count")}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ─────────────────────────────────────────────
# Notion Integration 📝
# ─────────────────────────────────────────────
async def notion_search(query: str = "", limit: int = 10) -> dict:
    """Search Notion pages."""
    if not NOTION_TOKEN:
        return {"success": False, "error": "NOTION_TOKEN not configured"}
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.notion.com/v1/search",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"query": query, "page_size": limit},
            )
            
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("results", [])[:limit]:
                    results.append({
                        "id": item.get("id"),
                        "title": item.get("properties", {}).get("Name", {}).get("title", [{}])[0].get("plain_text", "Untitled"),
                        "type": item.get("object"),
                        "url": item.get("url"),
                    })
                return {"success": True, "results": results}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def notion_create_page(title: str, content: str = "", parent_db: str = None) -> dict:
    """Create a new Notion page."""
    if not NOTION_TOKEN:
        return {"success": False, "error": "NOTION_TOKEN not configured"}
    
    try:
        database_id = parent_db or NOTION_DATABASE_ID
        if not database_id:
            return {"success": False, "error": "No Notion database configured"}
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.notion.com/v1/pages",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={
                    "parent": {"database_id": database_id},
                    "properties": {
                        "Name": {
                            "title": [{"text": {"content": title}}]
                        }
                    },
                    "children": [{
                        "object": "block",
                        "paragraph": {"rich_text": [{"text": {"content": content}}]}
                    }] if content else [],
                },
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "id": data.get("id"),
                    "url": data.get("url"),
                    "title": title,
                }
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


async def notion_get_database(db_id: str = None) -> dict:
    """Get Notion database content."""
    if not NOTION_TOKEN:
        return {"success": False, "error": "NOTION_TOKEN not configured"}
    
    try:
        database_id = db_id or NOTION_DATABASE_ID
        if not database_id:
            return {"success": False, "error": "No Notion database configured"}
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                },
                json={"page_size": 20},
            )
            
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("results", [])[:10]:
                    results.append({
                        "id": item.get("id"),
                        "title": item.get("properties", {}).get("Name", {}).get("title", [{}])[0].get("plain_text", "Untitled"),
                        "url": item.get("url"),
                    })
                return {"success": True, "results": results}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ─────────────────────────────────────────────
# Google Drive (Basic File Ops) 📁
# ─────────────────────────────────────────────
async def gdrive_list_files(folder_id: str = None, limit: int = 10) -> dict:
    """List Google Drive files (requires OAuth setup)."""
    # This is a placeholder - full GDrive requires OAuth2
    return {
        "success": False,
        "error": "Google Drive requires OAuth2 setup. See README for instructions.",
    }


# ─────────────────────────────────────────────
# Formatting Helpers
# ─────────────────────────────────────────────
def escape_html(text: str) -> str:
    return html.escape(str(text), quote=False)


def format_github_user(data: dict) -> str:
    if not data.get("success"):
        return f"❌ {escape_html(data.get('error', 'Unknown error'))}"
    
    text = f"🐙 <b>GitHub: {escape_html(data['login'])}</b>\n\n"
    if data.get("name"):
        text += f"👤 {escape_html(data['name'])}\n"
    if data.get("bio"):
        text += f"📝 {escape_html(data['bio'][:150])}\n"
    text += f"⭐ <b>{data['public_repos']}</b> repos\n"
    text += f"👥 <b>{data['followers']}</b> followers · {data['following']} following\n"
    if data.get("avatar"):
        text += f"\n[Profile image available]"
    return text


def format_github_repos(data: dict) -> str:
    if not data.get("success"):
        return f"❌ {escape_html(data.get('error', 'Unknown error'))}"
    
    text = f"🐙 <b>Repositories ({len(data['repos'])})</b>\n\n"
    for i, repo in enumerate(data["repos"], 1):
        text += f"<b>{i}.</b> <a href='{escape_html(repo['url'])}'>{escape_html(repo['name'])}</a>\n"
        if repo.get("description"):
            text += f"   <i>{escape_html(repo['description'][:100])}</i>\n"
        text += f"   ⭐ {repo['stars']} · {repo.get('language', 'N/A')} · Updated: {repo['updated']}\n\n"
    return text


def format_notion_results(data: dict) -> str:
    if not data.get("success"):
        return f"❌ {escape_html(data.get('error', 'Unknown error'))}"
    
    text = f"📝 <b>Notion Results ({len(data['results'])})</b>\n\n"
    for i, item in enumerate(data["results"], 1):
        emoji = "📄" if item["type"] == "page" else "🗄️"
        text += f"{emoji} <b>{i}.</b> <a href='{escape_html(item['url'])}'>{escape_html(item['title'])}</a>\n"
    return text


# ─────────────────────────────────────────────
# Command Detection
# ─────────────────────────────────────────────
PRODUCTIVITY_PATTERNS = [
    (r"/image\s+(.+)", "image_gen"),
    (r"/imagine\s+(.+)", "image_gen"),
    (r"/github\s+(\S+)", "github_user"),
    (r"/gh\s+(\S+)", "github_user"),
    (r"/repo\s+(\S+)", "github_repos"),
    (r"/issue\s+(\S+)\s+(\d+)", "github_issue"),
    (r"/gitsearch\s+(.+)", "github_search"),
    (r"/notion\s*(.*)", "notion_search"),
    (r"/notionpage\s+(.+)\s+(.+)", "notion_create"),
]


def detect_productivity_command(text: str) -> tuple:
    """Detect productivity command from text."""
    for pattern, cmd in PRODUCTIVITY_PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            return cmd, match.groups()
    return None, None
