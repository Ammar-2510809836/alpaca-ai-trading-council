import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv()
from broker.alpaca_client import AlpacaBroker

broker = AlpacaBroker(
    os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
)

for symbol in ["GLD", "SLV", "USO", "NVDA"]:
    price = broker.get_latest_price(symbol)
    chain = broker.get_option_chain(symbol, min_dte=7, max_dte=45)
    quoted = [c for c in chain if c["bid"] > 0 and c["ask"] > 0]
    with_greeks = [c for c in quoted if c["delta"]]
    print(
        f"{symbol:5} price=${price or 0:>8.2f} | contracts={len(chain):4} "
        f"| quoted={len(quoted):4} | w/greeks={len(with_greeks):4}"
    )
