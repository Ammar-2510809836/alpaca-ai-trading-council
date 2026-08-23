import argparse
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("engine.log", encoding="utf-8")],
    )


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def read_symbols_file(path="symbols.txt"):
    if not os.path.exists(path):
        return []
    symbols = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            token = line.split("#")[0].strip().upper()
            if token and token not in symbols:
                symbols.append(token)
    return symbols


def build(config, dry_run=False):
    from broker.alpaca_client import AlpacaBroker
    from broker.mcp_bridge import McpBridge
    from agent.llm import LLMClient

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    paper = str(config.get("mode", "paper")).lower() != "live"

    if not api_key or not secret_key:
        logging.warning("Alpaca keys missing -> running in offline simulation mode")

    llm_cfg = config.get("llm", {}) or {}
    provider = llm_cfg.get("provider") or "auto"
    if provider == "auto":
        provider = None
    llm = LLMClient(provider=provider, model=llm_cfg.get("model") or None)

    mcp = None
    broker = None
    if api_key and secret_key and not dry_run:
        mcp = McpBridge(api_key, secret_key, paper=paper)
        mcp.start()
        try:
            broker = AlpacaBroker(
                api_key,
                secret_key,
                paper=paper,
                data_feed=config.get("data_feed", "iex"),
                order_tag=config.get("order_tag", "aiagent"),
            )
            broker.get_clock()
        except Exception as exc:
            logging.error(f"Broker init failed: {exc}")
            broker = None
    elif dry_run:
        logging.info("DRY-RUN mode: no orders will be sent, simulated data used")

    return broker, mcp, llm


def main():
    parser = argparse.ArgumentParser(description="Alpaca AI Trading Council")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="no API calls, simulated data")
    parser.add_argument(
        "--ignore-hours",
        action="store_true",
        help="run cycles even when the market is closed (testing; orders queue until open)",
    )
    parser.add_argument("--symbols", help="comma-separated symbol override")
    args = parser.parse_args()

    load_dotenv()
    setup_logging()
    config = load_config(args.config)

    if args.symbols:
        config["symbols"] = [s.strip().upper() for s in args.symbols.split(",")]
    elif read_symbols_file():
        config["symbols_file"] = "symbols.txt"

    if args.ignore_hours:
        config["ignore_market_hours"] = True

    broker, mcp_bridge, llm = build(config, dry_run=args.dry_run)
    from engine import TradingEngine

    engine = TradingEngine(broker, mcp_bridge, llm, config, dry_run=args.dry_run)

    try:
        if args.once or not broker:
            engine.run_cycle()
        else:
            engine.run_forever()
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    finally:
        if mcp_bridge:
            mcp_bridge.stop()


if __name__ == "__main__":
    main()
