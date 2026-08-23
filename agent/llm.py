import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Endpoint:
    name: str
    client: object
    model: str
    is_anthropic: bool = False
    cooldown_until: float = 0.0
    failures: int = 0


class LLMClient:
    BACKOFF_SECONDS = [30, 120, 900]

    def __init__(self, provider: str = None, model: str = None, temperature: float = 0.2):
        self.temperature = temperature
        self._lock = threading.Lock()
        self.endpoints = self._build_endpoints(provider, model)

        if not self.endpoints:
            logging.warning(
                "No LLM provider configured (set GROQ_API_KEY / NVIDIA_API_KEY / "
                "ANTHROPIC_API_KEY / OPENAI_API_KEY). Brains fall back to deterministic voting."
            )

    def _build_endpoints(self, provider, model):
        chosen = (provider or "").lower()
        endpoints = []

        def wanted(name):
            return chosen in ("", "auto") or chosen == name

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key and wanted("groq"):
            from openai import OpenAI

            client = OpenAI(
                api_key=groq_key,
                base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            )
            endpoints.append(
                Endpoint(
                    "groq",
                    client,
                    model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
                )
            )

        nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
        if nvidia_key and wanted("nvidia"):
            from openai import OpenAI

            client = OpenAI(
                api_key=nvidia_key,
                base_url=os.environ.get(
                    "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
                ),
            )
            endpoints.append(
                Endpoint(
                    "nvidia",
                    client,
                    model or os.environ.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
                )
            )

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key and wanted("anthropic"):
            import anthropic

            endpoints.append(
                Endpoint(
                    "anthropic",
                    anthropic.Anthropic(),
                    model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                    is_anthropic=True,
                )
            )

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key and wanted("openai"):
            from openai import OpenAI

            endpoints.append(
                Endpoint(
                    "openai",
                    OpenAI(),
                    model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                )
            )

        return endpoints

    @property
    def enabled(self) -> bool:
        return bool(self.endpoints)

    @property
    def model(self) -> str:
        if not self.endpoints:
            return ""
        return "+".join(f"{e.name}:{e.model}" for e in self.endpoints)

    def health(self):
        now = time.time()
        return [
            {
                "provider": e.name,
                "model": e.model,
                "status": "COOLING_DOWN" if e.cooldown_until > now else ("ONLINE" if e.failures == 0 else "RECOVERING"),
                "cooling_for_s": round(max(e.cooldown_until - now, 0)),
                "failures": e.failures,
            }
            for e in self.endpoints
        ]

    def _write_health(self, alert: dict = None, active_provider: str = None):
        try:
            os.makedirs("journals", exist_ok=True)
            path = os.path.join("journals", "llm_health.json")
            existing = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as h:
                        existing = json.load(h)
                except Exception:
                    existing = {}

            recent_alerts = existing.get("recent_alerts", [])
            if alert:
                recent_alerts.insert(0, alert)
                recent_alerts = recent_alerts[:20] # keep last 20 alerts

            now = time.time()
            endpoints_info = []
            active_rate_limits = []

            for e in self.endpoints:
                rem_cool = round(max(e.cooldown_until - now, 0))
                is_limited = rem_cool > 0
                st_label = f"Rate-Limited ({rem_cool}s)" if is_limited else ("Online" if e.failures == 0 else "Degraded")
                ep_data = {
                    "provider": e.name,
                    "model": e.model,
                    "status": st_label,
                    "is_cooling_down": is_limited,
                    "cooling_for_s": rem_cool,
                    "failures": e.failures,
                }
                endpoints_info.append(ep_data)
                if is_limited:
                    active_rate_limits.append(f"{e.name.upper()} ({rem_cool}s cooldown)")

            state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "active_provider": active_provider or existing.get("active_provider", ""),
                "active_rate_limits": active_rate_limits,
                "has_active_rate_limit": bool(active_rate_limits),
                "endpoints": endpoints_info,
                "recent_alerts": recent_alerts,
            }

            with open(path, "w", encoding="utf-8") as h:
                json.dump(state, h, indent=2)
        except Exception:
            pass

    def complete_json(self, system: str, prompt: str, max_tokens: int = 1200):
        if not self.endpoints:
            return None

        max_tokens = max(int(max_tokens), 400)

        errors = []
        for endpoint in self._ordered():
            try:
                raw = self._complete(endpoint, system, prompt, max_tokens)
                parsed = self._extract_json(raw)
                if parsed is None:
                    raise ValueError("unparseable JSON response")
                with self._lock:
                    endpoint.failures = 0
                self._write_health(active_provider=f"{endpoint.name} ({endpoint.model})")
                return parsed
            except Exception as exc:
                cooldown, is_rate_limit = self._register_failure(endpoint, exc)
                err_msg = str(exc)[:140]
                errors.append(f"{endpoint.name} ({endpoint.model}): {err_msg} [cooldown {cooldown}s]")

                # Record rate limit / error event for dashboard visibility
                self._write_health(
                    alert={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "provider": endpoint.name,
                        "model": endpoint.model,
                        "error_type": "RATE_LIMIT_429" if is_rate_limit else "API_ERROR",
                        "message": err_msg,
                        "cooldown_s": cooldown,
                    }
                )

        if errors:
            logging.warning("All LLM endpoints unavailable -> deterministic fallback. " + " | ".join(errors))
            self._write_health(
                alert={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": "ALL",
                    "model": "fallback",
                    "error_type": "FALLBACK_ENGAGED",
                    "message": "All configured LLM providers in cooldown/error -> voting fell back to deterministic MACD/RSI models",
                    "cooldown_s": 0,
                }
            )
        return None

    def _ordered(self):
        now = time.time()
        with self._lock:
            available = [e for e in self.endpoints if e.cooldown_until <= now]
            pool = available or sorted(self.endpoints, key=lambda e: e.cooldown_until)[:1]
            return sorted(pool, key=lambda e: (e.failures, e.name))

    def _complete(self, endpoint: Endpoint, system: str, prompt: str, max_tokens: int) -> str:
        if endpoint.is_anthropic:
            response = endpoint.client.messages.create(
                model=endpoint.model,
                max_tokens=max_tokens,
                temperature=self.temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
            return "\n".join(getattr(b, "text", "") for b in blocks)

        response = endpoint.client.chat.completions.create(
            model=endpoint.model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    def _register_failure(self, endpoint: Endpoint, exc: Exception) -> tuple[int, bool]:
        text = str(exc).lower()
        rate_limited = (
            type(exc).__name__.lower().startswith("ratelimit")
            or "429" in text
            or "rate limit" in text
            or "quota" in text
            or "tokens per" in text
            or "too many requests" in text
        )
        with self._lock:
            endpoint.failures += 1
            if rate_limited:
                idx = min(endpoint.failures - 1, len(self.BACKOFF_SECONDS) - 1)
                cooldown = self.BACKOFF_SECONDS[idx]
            else:
                cooldown = 10
            endpoint.cooldown_until = time.time() + cooldown
        logging.warning(
            f"LLM endpoint {endpoint.name} failed ({'rate-limit' if rate_limited else 'error'}), "
            f"cooling down {cooldown}s"
        )
        return cooldown, rate_limited

    @staticmethod
    def _extract_json(raw):
        if not raw:
            return None

        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return None
