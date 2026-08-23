import logging

import requests


def send_message(message: str, webhook_url: str):
    if not webhook_url:
        logging.info(f"Discord not configured; message: {message[:200]}")
        return
    try:
        response = requests.post(webhook_url, json={"content": message}, timeout=10)
        if response.status_code not in (200, 204):
            logging.warning(f"Discord webhook failed {response.status_code}: {response.text}")
    except Exception as exc:
        logging.error(f"Discord alert error: {exc}")


def trade_alert(webhook_url, symbol, underlying, structure, direction, qty, limit_price, order_id, mode):
    content = (
        "**AI Council Trade Placed**\n"
        f"Underlying: `{underlying}`\n"
        f"Structure: `{structure}` ({direction})\n"
        f"Qty: `{qty}`\n"
        f"Limit/Est: `${limit_price}`\n"
        f"Order: `{order_id}`\n"
        f"Mode: `{mode}`\n"
    )
    send_message(content, webhook_url)
