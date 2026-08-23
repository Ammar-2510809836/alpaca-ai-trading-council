import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from broker.alpaca_client import AlpacaBroker

api_key = os.environ.get("ALPACA_API_KEY", "")
secret_key = os.environ.get("ALPACA_SECRET_KEY", "")

if not api_key or not secret_key:
    print("FAIL: Alpaca keys missing in .env")
    sys.exit(1)

try:
    broker = AlpacaBroker(api_key, secret_key)
    clock = broker.get_clock()
    if clock is None:
        raise RuntimeError("get_clock returned None (bad keys or network)")
    print(f"[OK] Alpaca paper API reachable | market_open={clock['is_open']}")
    account = broker.get_account()
    print(
        f"[OK] Account: equity=${account['equity']:,.2f} | cash=${account['cash']:,.2f} "
        f"| buying_power=${account['buying_power']:,.2f} | paper={account['paper']}"
    )
except Exception as exc:
    print(f"FAIL: Alpaca error: {exc}")
    sys.exit(1)

groq_key = os.environ.get("GROQ_API_KEY", "")
if not groq_key:
    print("[WARN] GROQ_API_KEY empty - council will use deterministic fallback votes")
else:
    try:
        from agent.llm import LLMClient

        llm = LLMClient()
        result = llm.complete_json(
            "You are a JSON echo service. Respond with only a JSON object.",
            'Return exactly this object: {"ok": true, "brain_online": true}',
            max_tokens=100,
        )
        if result and result.get("ok"):
            print(f"[OK] Groq LLM online: {llm.model}")
        else:
            print(f"[WARN] Groq responded but JSON was invalid: {result}")
    except Exception as exc:
        print(f"FAIL: Groq error: {exc}")
        sys.exit(1)

print("\nAll good. Run a live-paper council cycle:")
print("  python run.py --once")
