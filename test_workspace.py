from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

# Try workspace-specific endpoint
api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = "https://llm-k4l6h7dcie932cqo.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

print(f"Testing workspace endpoint: {base_url}")
print(f"API Key: {api_key[:10]}...")

client = OpenAI(api_key=api_key, base_url=base_url)

try:
    response = client.chat.completions.create(
        model="qwen-plus",
        messages=[{"role": "user", "content": "Hello, test workspace API"}],
        temperature=0.7,
        max_tokens=100,
    )
    print(f"Success: {response.choices[0].message.content}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
