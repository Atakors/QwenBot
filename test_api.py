import dashscope
from dashscope import Generation
from http import HTTPStatus
from dotenv import load_dotenv
import os

load_dotenv()

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

print("Testing DashScope API with official SDK...")
try:
    response = Generation.call(
        model=os.getenv("QWEN_MODEL", "qwen-turbo"),
        messages=[{"role": "user", "content": "Hello, test"}],
        result_format="message",
    )

    if response.status_code == HTTPStatus.OK:
        print(f"Success: {response.output.choices[0].message.content}")
    else:
        print(f"Error: {response.code} - {response.message}")
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")
