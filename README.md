# 🤖 AI Trading Council

**An autonomous, options-native AI trading agent for Alpaca — four specialized LLM brains vote on every trade; a deterministic risk governor holds veto power.**

> Built for the [Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon) · lablab.ai · Aug 28 – Sep 4, 2026

---

## Overview

Most "AI trading bots" wrap one LLM call around an indicator and hope. **AI Trading Council** treats trade decisions like a committee meeting:

- Two **LLM analysts** independently assess direction (one reads price action, one reads news)
- A weighted **consensus** must form before anything happens — default behavior is HOLD
- An **options strategist** then designs a concrete structure (spreads, longs) from the live chain using Greeks & IV
- A purely **deterministic risk governor** can veto everything — it never hallucinates
- Every order executes through **Alpaca's official MCP Server** (REST fallback), on **paper trading**

The result is an agent that is *auditable*: every vote, every veto, every contract choice is journaled and rendered in a live dashboard.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            python app.py                                │
│                                                                         │
│   ENGINE THREAD                          LIVE DASHBOARD                 │
│   ───────────────                        ───────────────                │
│   5-min cycles Mon–Fri                   localhost:8501 (auto-open)     │
│        │                                 • live agent phase feed        │
│        ▼                                 • vote cards + LLM reasoning   │
│  ┌─────────────┐   closed bars only      • equity / Sharpe / drawdown    │
│  │ Market Data │◄── Alpaca REST/MCP       • working orders & positions   │
│  └──────┬──────┘                                                       │
│         ▼                                                               │
│  ┌─────────────┐   MACD · RSI-divergence · fractal structure · EMA HTF  │
│  │ Indicators  │◄── (ported from a production forex bot)               │
│  └──────┬──────┘                                                       │
│         ▼                                                               │
│  ╔══════════════════════ COUNCIL ═══════════════╗                      │
│  ║  🧠 technical-analyst (Groq Llama)  w=1.5    ║                      │
│  ║  🧠 news-sentiment   (Groq Llama)   w=1.0    ║→ weighted consensus  │
│  ╚══════════════════════╤═══════════════════════╝   |score| ≥ 0.45    │
│                         ▼                                               │
│  ┌──────────────────────────┐   chain + Greeks + IV → structure design  │
│  │ 🎯 options-strategist    │   long call/put · bull call · bear put    │
│  └────────────┬─────────────┘                                          │
│               ▼                                                         │
│  ┌──────────────────────────┐   market hours · position limits · 1%     │
│  │ 🛡 RISK GOVERNOR (rules) │   risk/trade · 3% daily loss cap → VETO   │
│  └────────────┬─────────────┘                                          │
│               ▼                                                         │
│  ┌──────────────────────────┐   MLEG limit spreads · single-leg limits  │
│  │ ⚡ EXECUTION             │   client_order_id attribution              │
│  └────────────┬─────────────┘                                          │
│               ▼                                                         │
│      journals/*.csv + Discord alerts + engine_state.json                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
cd alpaca-agent

# 1. Environment (venv already created at .venv — select it as your IDE interpreter)
uv venv --python 3.13 .venv          # first time only
.\.venv\Scripts\activate
pip install -r requirements.txt

# 2. Keys
copy .env.example .env               # fill ALPACA_API_KEY / SECRET + GROQ_API_KEY

# 3. Verify connectivity
python check_setup.py

# 4. Run everything — engine + live dashboard, auto-opens browser
python app.py
```

| `app.py` flag | Effect |
|---|---|
| *(none)* | 5-min cycles Mon–Fri + dashboard |
| `--once --ignore-hours` | weekend/single-cycle test (orders queue until open) |
| `--symbols AAPL,AMD` | watchlist override |
| `--cycle 60` | custom cycle interval |
| `--no-engine` / `--no-dashboard` | headless server / monitor-only |

**Watchlist:** edit `symbols.txt` (one symbol per line) — the engine re-reads it every cycle. New tickers start being traded within minutes, no restart.

---

## How a decision is made (per symbol, per cycle)

1. **Pending-order guard** — skip if an order for this underlying is already working (no duplicate stacking)
2. **Market data** — 5m/15m bars from Alpaca; the still-forming candle is dropped (**closed-bar discipline**, no lookahead)
3. **Indicator stack** — MACD(12,26,9) crossover state & histogram trend · RSI(14) with TradingView-exact divergence detection · fractal market-structure engine (HH/HL vs LH/LL breaks) · H1-EMA50 and D1-EMA20 regime resampled from raw bars
4. **🧠 Technical analyst votes** — LLM receives the indicator snapshot and must return structured JSON `{direction, confidence, reasoning}`; falls back to deterministic scoring if the LLM is down
5. **🧠 News analyst votes** — recent Alpaca headlines scored for sentiment *and* event risk (earnings/FDA/litigation warnings reduce confidence); fetched through the **MCP server**
6. **Consensus** — `score = Σ sign(directionᵢ) · confidenceᵢ · weightᵢ`; requires `|score| ≥ threshold` (default 0.45). Otherwise → HOLD
7. **🎯 Options strategist designs the trade**
   - LLM-first: sees the top-of-book chain snapshot (strike/DTE/mid/IV/delta) and picks the structure
   - Rule-based fallback: long leg ≈ 0.45Δ, 7–45 DTE; when chain-average IV is elevated (>0.45) build a **vertical spread** (short leg ≈ 0.25Δ same expiry), otherwise take the naked long
   - Sanity gates reject degenerate structures (spread debit < $0.05, width < $1, naked premium < $0.10)
8. **🛡 Risk governor veto** — pure Python, no LLM: market-hours · max open positions · one-position-per-underlying (incl. working orders) · per-trade cost vs 1% equity budget (auto qty-reduction before hard veto) · 3% daily-loss circuit breaker
9. **⚡ Execution** — multi-leg = native **MLEG limit order** (net debit priced at mid); single-leg = limit order at mid; both tagged `aiagent-{structure}-{id}` for attribution
10. **Journal + alert** — decision, all votes with reasoning, and order status land in CSV; optional Discord webhook fires instantly
11. **Exit management (every cycle)** — stop at −35% of option premium, target at +60%, forced close at DTE ≤ 1; spread short-legs are managed alongside their long pair

---

## The four brains

| Brain | Type | Input | Output | Weight |
|---|---|---|---|---|
| `technical-analyst` | LLM + rules fallback | Indicator snapshot, last 10 closes | direction/confidence/reasoning JSON | 1.5 |
| `news-sentiment` | LLM | Headlines via MCP `get_news` | direction/confidence/reasoning JSON | 1.0 |
| `options-strategist` | LLM + rules | Full chain snapshot, consensus direction | Concrete contract-level structure | 1.2 |
| `risk-governor` | **Deterministic only** | Account, positions, orders, journal | VETO / qty-adjustment / pass | veto |

**Why a council?** A single LLM will happily invent conviction from noise. Requiring independent agreement — and giving final say to code that cannot be sweet-talked — is what makes this deployable. It also means the system **degrades gracefully**: no LLM key → rule-based voting still runs; no MCP (`uvx` missing) → transparent REST fallback; market closed → nothing trades unless you explicitly force it.

## Execution & broker integration

- **Dual path**: the official [`alpaca-mcp-server`](https://github.com/alpacahq/alpaca-mcp-server) is launched automatically over stdio (JSON-RPC handshake implemented in `broker/mcp_bridge.py` — 74 tools detected in testing). News, chains and account calls prefer MCP; every call has a direct REST equivalent via `alpaca-py`.
- **Order types**: single-leg option limit · native multi-leg (MLEG) limit spreads · stock bracket orders available
- **Attribution**: every order carries a `client_order_id` of the form `aiagent-bear-put-spread-a1b2c3d4`
- **Paper-first**: `mode: paper` in config; live trading requires explicit opt-in plus live keys

## Risk framework

| Guardrail | Default | Behavior |
|---|---|---|
| Per-trade risk | 1% of equity | qty auto-reduced to fit; veto at >1.5× budget |
| Daily loss cap | 3% of equity | blocks new entries after breach |
| Max open positions | 4 | new entries blocked |
| Concentration | 1 position per underlying | incl. pending orders |
| Option stop / target | −35% / +60% premium | evaluated every cycle |
| Expiry risk | DTE ≤ 1 | forced close |
| Market hours | enforced | entries skipped; test override exists |

## Live monitoring (`dashboard.py`, auto-launched by `app.py`)

- **Live agent panel** — pulsing phase indicator fed by the engine's real-time state file: `cycle_start → market_data → indicators → llm_council → decision → execution → exits → idle`, with the current symbol and message
- **Verdict cards** — every decision with per-brain vote chips, confidence scores, full LLM reasoning, vetoes
- **Performance tab** — 30-day equity curve, max drawdown, annualized Sharpe
- **Execution tab** — working orders (with spread legs), open positions, trade journal
- Dark production theme; sidebar shows connection status, brain/model in use, and the hot-reloaded watchlist

## Backtesting

```bash
python -m backtest.simulate                    # uses symbols.txt, real Alpaca history
python -m backtest.simulate --offline          # synthetic random-walk demo, zero setup
python -m backtest.simulate --symbols AAPL,NVDA --days 730 --stop .30 --target .55
```

Methodology: bar-by-bar replay on daily bars (closed bars only) · entry = MACD cross + EMA20-regime + RSI-bound confluence (deterministic proxy of the council's technical brain) · option P&L repriced daily with **Black-Scholes** (IV = realized-vol × 1.15, 30-DTE ATM) · 1%-risk compounding sizing · exits: −35%/+60%/time/signal-flip · reports win rate, profit factor, max drawdown, equal-weight portfolio return; exports `backtest/results/{trades,equity}.csv`.

## Project structure

```
alpaca-agent/
├── app.py                  ← ONE COMMAND: engine thread + dashboard + browser
├── run.py                  # standalone engine CLI
├── engine.py               # cycle loop, exits, live-state writer
├── journal.py              # decisions.csv / trades.csv audit trail
├── notify.py               # Discord webhook alerts
├── show_orders.py          # quick paper-account order viewer
├── check_setup.py          # key/API/Groq health check
├── symbols.txt             # HOT-RELOADED watchlist (edit anytime)
├── config.yaml             # thresholds, risk, exits, webhooks
├── .env.example            # ALPACA_* GROQ_MODEL templates
├── agent/
│   ├── llm.py              # Groq / Anthropic / OpenAI provider-agnostic client
│   ├── tools.py            # MCP-first tool layer w/ REST fallback
│   ├── models.py           # Vote / TradeProposal / CouncilDecision dataclasses
│   └── brains/
│       ├── analyst.py            # 🧠 technical analyst
│       ├── news_brain.py         # 🧠 news sentiment
│       ├── options_strategist.py # 🎯 structure designer
│       ├── risk_governor.py      # 🛡 deterministic veto layer
│       └── consensus.py          # weighted voting orchestrator
├── broker/
│   ├── alpaca_client.py    # REST facade (bars, chains+Greeks, MLEG orders…)
│   └── mcp_bridge.py       # stdio JSON-RPC client for alpaca-mcp-server
├── indicators/             # macd · rsi(+divergence) · ema · fractal_structure
├── signals/macd_v4.py      # technical context builder (closed-bar only)
├── backtest/simulate.py    # Black-Scholes bar-by-bar backtester
├── dashboard.py            # Streamlit live mission control
├── journals/               # decisions.csv · trades.csv · engine_state.json
└── .venv                   # Python 3.13 environment (select in your IDE)
```

## Configuration highlights (`config.yaml`)

```yaml
council:
  consensus_threshold: 0.45     # higher = pickier
options:
  min_dte: 7
  max_dte: 45
  high_iv_threshold: 0.45       # above → verticals instead of naked longs
risk:
  max_open_positions: 4
  max_risk_per_trade_pct: 0.01
  daily_loss_cap_pct: 0.03
exits:
  stop_loss_pct: 0.35
  take_profit_pct: 0.60
  force_close_dte: 1
discord_webhook: ""             # optional live alerts
```

## Hackathon compliance

| Requirement | Status | Where |
|---|---|---|
| Alpaca Trading API | ✅ verified live | `broker/alpaca_client.py` (paper account, real orders accepted) |
| Alpaca MCP Server **or** CLI | ✅ MCP online, 74 tools | `broker/mcp_bridge.py` |
| Options trading required | ✅ options-native | every entry is an option structure incl. multi-leg MLEG spreads |
| Paper environment, dedicated account | ✅ | `mode: paper` |
| Judging: P&L performance | risk-governor circuit breakers, premium stops, expiry hygiene | |
| Judging: technology implementation | dual REST+MCP execution, graceful degradation everywhere | |
| Judging: creativity | council architecture w/ deterministic veto — auditable by design | |
| Judging: presentation | one-command demo (`app.py`) with live reasoning dashboard | |

## Rate-limit resilience (free-tier LLMs)

The council is built for **multiple free LLM providers** with automatic load distribution:

1. **Provider pool & rotation** — every key in `.env` becomes an endpoint (`GROQ_API_KEY`, `NVIDIA_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Requests rotate across healthy endpoints.
2. **429-aware failover** — on a rate-limit response the endpoint is put into cooldown (30s → 120s → 15min exponential backoff) and the **next provider serves the call instantly** — the cycle never stalls.
3. **Token-saver caches** — news headlines cached 10 min, news *votes* cached 30 min per symbol: steady-state drops from ~10 LLM calls/cycle to ~5 (technical analyst only), because fresh price data is what genuinely needs re-reasoning each cycle.
4. **Graceful degradation** — if *every* provider is cooling down, brains vote deterministically that cycle instead of erroring.

To add your NVIDIA NIM key (build.nvidia.com → API key):

```
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=meta/llama-3.3-70b-instruct
```

That's it — Groq and NVIDIA now share the load automatically. `engine.log` shows which endpoint served each call and every cooldown event; `LLMClient.health()` exposes live provider status.

> Note: reasoning models (`openai/gpt-oss-*`) consume completion tokens for hidden chain-of-thought before answering — the client enforces a minimum token budget so answers never get truncated to nothing.

## Design notes & honest limitations

- Signals evaluate on **closed bars only**; the forming candle is dropped (same discipline as the author's production forex system this was ported from).
- Weekend/indicative option quotes can carry zeroed Greeks — the strategist filters these out rather than trusting them.
- Spread exits manage the long leg's P&L; paired short legs are force-closed together near expiry. Native net-position tracking is a roadmap item.
- Backtester prices options with Black-Scholes approximations — it validates signal quality, not fills.
- Paper trading only during development; flipping to live requires `mode: live` **and** live keys (not recommended during the event).

## Disclaimer

Educational software for a hackathon. Not financial advice. Options involve substantial risk of loss.
