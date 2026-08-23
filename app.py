import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# When executed by Streamlit Cloud (streamlit run app.py), delegate directly to dashboard
try:
    import streamlit.runtime
    if streamlit.runtime.exists():
        import dashboard  # noqa: F401
except Exception:
    pass

VENV_PYTHON = os.path.join(BASE, ".venv")


def venv_python_path() -> str:
    if os.name == "nt":
        return os.path.join(VENV_PYTHON, "Scripts", "python.exe")
    return os.path.join(VENV_PYTHON, "bin", "python")


def _deps_installed(python_exe: str) -> bool:
    probe = subprocess.run(
        [python_exe, "-c", "import alpaca, streamlit, yaml, dotenv, anthropic, openai, pandas"],
        cwd=BASE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return probe.returncode == 0


def ensure_venv():
    """Auto-relaunch inside the project venv, creating it first if needed."""
    target = venv_python_path()
    if os.path.abspath(sys.executable) == os.path.abspath(target):
        return

    print(f"[app] system python detected ({sys.executable})")
    if not os.path.exists(target):
        print("[app] creating virtual environment .venv (first run only)...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV_PYTHON])

    if not _deps_installed(target):
        print("[app] installing dependencies into .venv (first run only)...")
        subprocess.check_call(
            [target, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
             "-r", os.path.join(BASE, "requirements.txt")]
        )

    print(f"[app] relaunching inside .venv -> {target}")
    child = subprocess.Popen([target, os.path.abspath(__file__)] + sys.argv[1:], cwd=BASE)
    try:
        sys.exit(child.wait())
    except KeyboardInterrupt:
        child.terminate()
        sys.exit(0)


def free_port(start: int) -> int:
    port = start
    while port < start + 20:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    raise RuntimeError("no free port found")


def wait_for_port(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.4)
    return False


def run_engine(args):
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(threadName)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("engine.log", encoding="utf-8")],
    )

    from run import build, load_config, read_symbols_file

    config = load_config(args.config)
    if args.symbols:
        config["symbols"] = [s.strip().upper() for s in args.symbols.split(",")]
    elif read_symbols_file():
        config["symbols_file"] = "symbols.txt"
    if args.ignore_hours:
        config["ignore_market_hours"] = True
    if args.cycle:
        config["cycle_seconds"] = args.cycle

    broker, mcp_bridge, llm = build(config, dry_run=args.dry_run)

    from engine import TradingEngine

    engine = TradingEngine(broker, mcp_bridge, llm, config, dry_run=args.dry_run)

    try:
        while True:
            engine.run_cycle()
            if args.once or not broker:
                break
            time.sleep(int(config.get("cycle_seconds", 300)))
    except Exception as exc:
        logging.exception(f"Engine thread stopped: {exc}")
    finally:
        if mcp_bridge:
            mcp_bridge.stop()


def main():
    ensure_venv()

    parser = argparse.ArgumentParser(description="AI Trading Council — one-file launcher")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="engine runs a single cycle")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ignore-hours", action="store_true", help="trade even when market closed (testing)")
    parser.add_argument("--symbols", help="comma-separated override")
    parser.add_argument("--cycle", type=int, help="cycle interval seconds")
    parser.add_argument("--port", type=int, default=8501, help="dashboard port")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-engine", action="store_true", help="dashboard only")
    args = parser.parse_args()

    os.chdir(BASE)

    engine_thread = None
    if not args.no_engine:
        engine_thread = threading.Thread(
            target=run_engine,
            args=(args,),
            name="engine",
            daemon=True,
        )
        engine_thread.start()
        print("[app] engine thread started")

    if args.no_dashboard:
        if engine_thread:
            engine_thread.join()
        return

    port = free_port(args.port)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            os.path.join(BASE, "dashboard.py"),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=BASE,
    )

    url = f"http://localhost:{port}"
    if wait_for_port(port):
        print(f"[app] dashboard live at {url}")
        webbrowser.open(url)
    else:
        print(f"[app] dashboard did not open in time; check output above. URL: {url}")

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        print("[app] shutdown complete")


if __name__ == "__main__":
    is_streamlit = False
    try:
        import streamlit.runtime
        is_streamlit = bool(streamlit.runtime.exists())
    except Exception:
        pass

    if not is_streamlit:
        main()
