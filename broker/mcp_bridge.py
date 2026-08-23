import json
import logging
import os
import queue
import subprocess
import threading
from typing import Optional


class McpBridge:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        command: Optional[list] = None,
        startup_timeout: float = 60.0,
        call_timeout: float = 45.0,
    ):
        self.command = command or ["uvx", "alpaca-mcp-server"]
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self.available = False
        self.tool_names: list = []
        self._proc: Optional[subprocess.Popen] = None
        self._responses: dict = {}
        self._lock = threading.Lock()
        self._next_id = 10
        self.env = os.environ.copy()
        self.env.update(
            {
                "ALPACA_API_KEY": api_key,
                "ALPACA_SECRET_KEY": secret_key,
                "ALPACA_PAPER_TRADE": "true" if paper else "false",
                "PYTHONUNBUFFERED": "1",
            }
        )

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=self.env,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            logging.warning(f"MCP bridge unavailable ({self.command[0]} not found): {exc}")
            return False
        except Exception as exc:
            logging.warning(f"MCP bridge failed to start: {exc}")
            return False

        reader = threading.Thread(target=self._read_loop, daemon=True)
        reader.start()

        result = self._request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-trading-council", "version": "1.0"},
                },
            },
            timeout=self.startup_timeout,
        )
        if result is None:
            logging.warning("MCP handshake failed, falling back to REST-only mode")
            return False

        self._notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools = self._request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, timeout=self.startup_timeout)
        if tools is None:
            return False

        for tool in tools.get("tools", []):
            name = tool.get("name")
            if name:
                self.tool_names.append(name)

        self.available = True
        logging.info(f"MCP bridge online with {len(self.tool_names)} tools")
        return True

    def _read_loop(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_id = message.get("id")
            if msg_id is not None:
                with self._lock:
                    self._responses[msg_id] = message

    def _send(self, payload: dict) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return False
        try:
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()
            return True
        except Exception as exc:
            logging.error(f"MCP write failed: {exc}")
            return False

    def _request(self, payload: dict, timeout: float) -> Optional[dict]:
        msg_id = payload.get("id")
        with self._lock:
            self._responses.pop(msg_id, None)
        if not self._send(payload):
            return None

        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                response = self._responses.pop(msg_id, None)
            if response is not None:
                if "error" in response:
                    logging.error(f"MCP error on id={msg_id}: {response['error']}")
                    return None
                return response.get("result")
            time.sleep(0.05)

        logging.error(f"MCP timeout waiting for id={msg_id}")
        return None

    def _notify(self, payload: dict):
        self._send(payload)

    def call_tool(self, name: str, arguments: dict) -> Optional[str]:
        if not self.available or name not in self.tool_names:
            return None

        with self._lock:
            self._next_id += 1
            msg_id = self._next_id

        result = self._request(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            timeout=self.call_timeout,
        )
        if result is None:
            return None

        content = result.get("content", [])
        texts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(texts).strip()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self.available = False
