import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = os.getenv("DASHSCOPE_API_BASE")
model = os.getenv("QWEN_MODEL", "qwen-turbo")

print(f"API Key: {api_key[:10]}...")
print(f"Base URL: {base_url}")
print(f"Model: {model}")

# Test direct httpx first
print("\nTesting direct httpx...")
try:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello test"}],
    }
    with httpx.Client(verify=True, trust_env=True, timeout=30.0) as http_client:
        resp = http_client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print(f"SUCCESS: {resp.json()['choices'][0]['message']['content']}")
        else:
            print(f"ERROR: {resp.text[:500]}")
except Exception as e:
    print(f"httpx ERROR: {type(e).__name__}: {e}")

# Test OpenAI client
print("\nTesting OpenAI client...")
try:
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=httpx.Client(verify=True, trust_env=True),
        timeout=30.0,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Hello test"}],
    )
    print(f"SUCCESS: {response.choices[0].message.content}")
except Exception as e:
    print(f"OpenAI ERROR: {type(e).__name__}: {e}")
