import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()
import requests
from openai import OpenAI

key = os.environ.get("NVIDIA_API_KEY", "")
if not key:
    print("FAIL: NVIDIA_API_KEY missing")
    sys.exit(1)

print("=== 1. key validity + model list ===")
try:
    r = requests.get(
        "https://integrate.api.nvidia.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"FAIL: HTTP {r.status_code} - {r.text[:200]}")
        sys.exit(1)
    ids = sorted(m["id"] for m in r.json().get("data", []))
    print(f"   [OK] key valid - {len(ids)} models available")
except Exception as exc:
    print(f"   FAIL: {exc}")
    sys.exit(1)

configured = os.environ.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
print("\n=== 2. configured model check ===")
exact = configured in ids
family = [i for i in ids if i.split("/")[-1].startswith(configured.split("/")[-1][:12])]
print(f"   configured: {configured}")
print(f"   exact match on server: {exact}")
if family and not exact:
    print(f"   close matches: {family[:5]}")

print("\n=== 3. live JSON completion ===")
client = OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1")
try:
    resp = client.chat.completions.create(
        model=configured,
        max_completion_tokens=400,
        messages=[
            {"role": "system", "content": "You are a JSON echo service."},
            {"role": "user", "content": 'Return exactly this JSON object: {"ok": true}'},
        ],
    )
    content = resp.choices[0].message.content
    print("   raw:", repr(content)[:150])
    print("   usage:", resp.usage.prompt_tokens, "in /", resp.usage.completion_tokens, "out")
except Exception as exc:
    print(f"   FAIL: {str(exc)[:300]}")
    sys.exit(1)

print("\n=== 4. full council router (Groq + NVIDIA rotation) ===")
from agent.llm import LLMClient

llm = LLMClient()
for h in llm.health():
    print(f"   endpoint: {h['provider']:8} {h['model']:35} cooling={h['cooling_for_s']}s")
votes = 0
for _ in range(4):
    out = llm.complete_json(
        "You are a JSON echo service.",
        'Return exactly: {"ok": true}',
        max_tokens=100,
    )
    if out and out.get("ok"):
        votes += 1
print(f"   router round-robin: {votes}/4 calls succeeded across providers")

print("\nALL NVIDIA CHECKS DONE")
