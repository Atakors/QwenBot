import os, asyncio
os.chdir(r"D:\QwenBot")
from dotenv import load_dotenv
load_dotenv(override=True)
from telegram import Bot
bot = Bot(os.getenv("TELEGRAM_BOT_TOKEN"))

async def check():
    updates = await bot.get_updates(timeout=10)
    print(f"Pending updates: {len(updates)}")
    for u in updates:
        print(f"  #{u.update_id}: {u.message.text if u.message else '[no msg]'}")
    await bot.shutdown()

asyncio.run(check())
