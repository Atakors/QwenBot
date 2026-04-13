import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = os.getenv("DASHSCOPE_API_BASE")
model = os.getenv("QWEN_MODEL", "qwen-turbo")

print(f"API Key: {api_key[:10]}...")
print(f"Base URL: {base_url}")
print(f"Model: {model}")

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=httpx.Client(verify=True, trust_env=True),
)

messages = [
    {"role": "system", "content": "You are a helpful AI assistant powered by Qwen. Respond concisely and helpfully."},
    {"role": "user", "content": "Hello from bot test"}
]

try:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=1024,
    )
    print(f"SUCCESS: {response.choices[0].message.content}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
