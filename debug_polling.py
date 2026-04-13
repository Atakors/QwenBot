import asyncio
import os
os.chdir(r"D:\QwenBot")

from dotenv import load_dotenv
load_dotenv(override=True)

from telegram.ext import ApplicationBuilder, CommandHandler
from telegram import Update
from telegram.ext import ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
print(f"Token: {TOKEN[:10]}...")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("TEST OK")

async def main():
    print("Building application...")
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    
    app.add_handler(CommandHandler("start", start))
    
    print("Initializing...")
    await app.initialize()
    
    print(f"Bot: @{app.bot.username}")
    
    print("Starting polling...")
    await app.start()
    
    # Manual get_updates loop
    print("Fetching updates...")
    updates = await app.bot.get_updates(timeout=30)
    print(f"Updates: {len(updates)}")
    for u in updates:
        print(f"  #{u.update_id}: {u.message.text if u.message else '[no msg]'}")
    
    await app.stop()
    await app.shutdown()

asyncio.run(main())
