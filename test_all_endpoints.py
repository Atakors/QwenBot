import os
from openai import OpenAI

api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-d02ff66e4bee43d08ebe3a203a77c5af")

# Try default DashScope endpoint
endpoints = [
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://llm-k4l6h7dcie932cqo.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
]

for endpoint in endpoints:
    print(f"\nTesting: {endpoint}")
    try:
        client = OpenAI(api_key=api_key, base_url=endpoint, timeout=30.0)
        resp = client.chat.completions.create(
            model="qwen-turbo",
            messages=[{"role": "user", "content": "Hello test"}],
        )
        print(f"SUCCESS: {resp.choices[0].message.content}")
        break
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
