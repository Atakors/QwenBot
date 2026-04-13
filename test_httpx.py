import os
import httpx
from openai import OpenAI

api_key = "sk-d02ff66e4bee43d08ebe3a203a77c5af"
endpoint = "https://llm-k4l6h7dcie932cqo.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

print(f"Testing with httpx client directly...")

# Try with httpx first
try:
    client = httpx.Client(timeout=30.0, verify=True)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "qwen-turbo",
        "messages": [{"role": "user", "content": "Hello test"}],
    }
    resp = client.post(f"{endpoint}/chat/completions", json=payload, headers=headers)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")
except Exception as e:
    print(f"httpx Error: {type(e).__name__}: {e}")

print("\nTesting with OpenAI client...")
try:
    openai_client = OpenAI(
        api_key=api_key,
        base_url=endpoint,
        timeout=30.0,
        http_client=httpx.Client(verify=True, trust_env=True),
    )
    resp = openai_client.chat.completions.create(
        model="qwen-turbo",
        messages=[{"role": "user", "content": "Hello test"}],
    )
    print(f"SUCCESS: {resp.choices[0].message.content}")
except Exception as e:
    print(f"OpenAI Error: {type(e).__name__}: {e}")
