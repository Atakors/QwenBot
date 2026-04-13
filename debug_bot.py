import sys
print("Python:", sys.version)

print("Loading modules...")
try:
    from dotenv import load_dotenv
    print("dotenv OK")
except Exception as e:
    print(f"dotenv FAIL: {e}")

try:
    import telegram
    print(f"telegram OK ({telegram.__version__})")
except Exception as e:
    print(f"telegram FAIL: {e}")
    sys.exit(1)

try:
    from openai import AsyncOpenAI
    print("openai OK")
except Exception as e:
    print(f"openai FAIL: {e}")

print("\nLoading bot.py main()...")
import os
os.chdir(r"D:\QwenBot")

# Simulate what happens when we import bot
import importlib.util
spec = importlib.util.spec_from_file_location("bot", "bot.py")
bot = importlib.util.module_from_spec(spec)

print("Executing bot.py...")
try:
    spec.loader.exec_module(bot)
    print("Module loaded OK")
    print(f"TELEGRAM_TOKEN set: {bool(bot.TELEGRAM_TOKEN)}")
    print(f"DASHSCOPE_API_KEY set: {bool(bot.DASHSCOPE_API_KEY)}")
    print(f"DB_PATH: {bot.DB_PATH}")
    print(f"ADMIN_IDS: {bot.ADMIN_IDS}")
except Exception as e:
    print(f"Module FAIL: {e}")
    import traceback
    traceback.print_exc()
