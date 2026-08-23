import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()
import requests

r = requests.get(
    "https://paper-api.alpaca.markets/v2/orders?status=all&limit=10&nested=true",
    headers={
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    },
    timeout=30,
)

for o in r.json():
    legs = ",".join(
        f"{leg['side'][:1].upper()}{leg.get('qty','')}x{leg['symbol']}" for leg in (o.get("legs") or [])
    )
    limit = o.get("limit_price") or ""
    print(
        f"{o['created_at'][:16]}  {o['status']:>12}  {o['type']:>6}  "
        f"{o['symbol'][:26]:26} qty={o['qty']:>3}  lim={limit:>7}  {('[' + legs + ']') if legs else ''}"
    )
