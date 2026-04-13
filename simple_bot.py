import logging
import os
import sys

os.chdir(r"D:\QwenBot")

from dotenv import load_dotenv
load_dotenv(override=True)

print(f"Python: {sys.version}")
print(f"CWD: {os.getcwd()}")
print(f"TELEGRAM_TOKEN: {os.getenv('TELEGRAM_BOT_TOKEN', 'NOT SET')[:15]}...")
print(f"DASHSCOPE_API_KEY: {os.getenv('DASHSCOPE_API_KEY', 'NOT SET')[:15]}...")
print(f"DASHSCOPE_API_BASE: {os.getenv('DASHSCOPE_API_BASE', 'NOT SET')}")
print(f"QWEN_MODEL: {os.getenv('QWEN_MODEL', 'NOT SET')}")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[HANDLER] /start called by {update.effective_user.id}")
    await update.message.reply_text("BOT IS CONNECTED!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[HANDLER] Message from {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text(f"Echo: {update.message.text}")

async def main():
    print("Building application...")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT, echo))
    
    print("Starting polling (Ctrl+C to stop)...")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
