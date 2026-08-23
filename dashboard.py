import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import yaml
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))

# Bridge Streamlit Cloud Secrets into os.environ
try:
    if hasattr(st, "secrets"):
        for _k, _v in st.secrets.items():
            if isinstance(_v, str) and _k not in os.environ:
                os.environ[_k] = _v
except Exception:
    pass

st.set_page_config(
    page_title="AI Trading Council",
    page_icon="chart",
    layout="wide",
    initial_sidebar_state="expanded",
)

TV_GREEN = "#089981"
TV_RED = "#f23645"
TV_BLUE = "#2962ff"
INK = "#131722"
MUTED = "#787b86"
BORDER = "#e0e3eb"
PANEL = "#ffffff"
BG = "#f8f9fd"

st.markdown(
    f"""
<style>
    .stApp {{ background: {BG}; color: {INK}; }}
    section[data-testid="stSidebar"] {{
        background: {PANEL}; border-right: 1px solid {BORDER};
    }}
    section[data-testid="stSidebar"] * {{ color: {INK} !important; }}
    section[data-testid="stSidebar"] .muted {{ color: {MUTED} !important; }}

    h1 {{ font-size: 1.4rem !important; font-weight: 700 !important;
         letter-spacing: -0.02em; margin-bottom: 0 !important; }}
    h2, h3 {{ font-weight: 650 !important; }}

    div[data-testid="stMetric"] {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
        padding: 12px 16px 8px; box-shadow: 0 1px 2px rgba(19,23,34,.04);
        min-width: 0; overflow: hidden;
    }}
    div[data-testid="stMetricLabel"] p {{
        color: {MUTED} !important; font-size: .76rem !important;
        text-transform: uppercase; letter-spacing: .06em; font-weight: 600 !important;
    }}
    div[data-testid="stMetricValue"] {{
        color: {INK} !important; font-weight: 750 !important;
        font-variant-numeric: tabular-nums;
        font-size: clamp(1.15rem, 2.1vw, 1.75rem) !important;
        line-height: 1.25 !important; white-space: nowrap;
    }}
    div[data-testid="stMetricDelta"] svg {{ display: none; }}
    div[data-testid="stMetricDelta"] {{
        font-variant-numeric: tabular-nums; font-size: .84rem !important;
    }}

    [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 2px solid {BORDER}; }}
    [data-baseweb="tab"] {{
        font-weight: 650; font-size: .88rem; padding: 8px 14px;
        letter-spacing: .03em;
    }}
    [aria-selected="true"] {{ background: #eef1f8; }}

    .phase-pill {{
        display: inline-block; padding: 5px 16px; border-radius: 999px;
        font-size: .84rem; font-weight: 650; letter-spacing: .02em;
        background: #eef4ff; border: 1px solid #c7d7fe; color: {TV_BLUE};
    }}
    .live-dot {{
        display: inline-block; width: 8px; height: 8px; border-radius: 50%;
        background: {TV_GREEN}; margin-right: 8px; vertical-align: middle;
        box-shadow: 0 0 0 3px rgba(8,153,129,.15);
        animation: pulse 1.4s infinite;
    }}
    .idle-dot {{
        display: inline-block; width: 8px; height: 8px; border-radius: 50%;
        background: #9aa2b1; margin-right: 8px; vertical-align: middle;
    }}
    @keyframes pulse {{ 0%{{opacity:1}} 50%{{opacity:.35}} 100%{{opacity:1}} }}

    .vote-chip {{
        padding: 3px 11px; border-radius: 999px; font-size: .76rem; font-weight: 700;
        margin-right: 6px; display: inline-block; border: 1px solid transparent;
        font-variant-numeric: tabular-nums;
    }}
    .vote-bullish {{ background: rgba(8,153,129,.09); color: {TV_GREEN};
                     border-color: rgba(8,153,129,.30); }}
    .vote-bearish {{ background: rgba(242,54,69,.08); color: {TV_RED};
                     border-color: rgba(242,54,69,.28); }}
    .vote-neutral {{ background: #f0f1f5; color: {MUTED}; border-color: {BORDER}; }}

    .decision-card {{
        background: {PANEL}; border: 1px solid {BORDER}; border-left: 3px solid {BORDER};
        border-radius: 10px; padding: 12px 16px; margin-bottom: 10px;
        box-shadow: 0 1px 2px rgba(19,23,34,.03);
    }}
    .decision-card.trade {{ border-left-color: {TV_BLUE}; }}
    .muted {{ color: {MUTED}; font-size: .82rem; }}
    .mono {{ font-variant-numeric: tabular-nums; }}

    .ticker-chip {{
        display:inline-block; padding: 3px 12px; margin: 0 5px 5px 0;
        background: #eef1f8; border: 1px solid {BORDER}; border-radius: 6px;
        font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
        font-size: .78rem; font-weight: 700; color: {INK};
    }}
    .sys-row {{ display:flex; align-items:center; gap:8px; padding:5px 0; font-size:.86rem; }}
    .dot-ok  {{ width:8px;height:8px;border-radius:50%;background:{TV_GREEN}; flex:none; }}
    .dot-off {{ width:8px;height:8px;border-radius:50%;background:#d1d5db; flex:none; }}
</style>
""",
    unsafe_allow_html=True,
)


def load_config():
    path = os.path.join(BASE, "config.yaml")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


def load_engine_state():
    path = os.path.join(BASE, "journals", "engine_state.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}
    return {}


DECISION_COLUMNS = ["timestamp", "symbol", "action", "confidence", "summary",
                    "vetoed_by", "veto_reason", "votes"]
TRADE_COLUMNS = ["timestamp", "underlying", "symbol", "asset_class", "structure",
                 "direction", "qty", "limit_price", "client_order_id", "status"]


def load_position_tracking():
    path = os.path.join(BASE, "journals", "position_tracking.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}
    return {}


def load_decisions(limit=40):
    path = os.path.join(BASE, "journals", "decisions.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=DECISION_COLUMNS)
    try:
        df = pd.read_csv(path, on_bad_lines="skip")
    except Exception:
        return pd.DataFrame(columns=DECISION_COLUMNS)
    if df.empty or not {"timestamp", "symbol", "action"}.issubset(df.columns):
        return pd.DataFrame(columns=DECISION_COLUMNS)
    return df.dropna(subset=["symbol", "action"]).tail(limit).iloc[::-1]


def load_trades(limit=30):
    path = os.path.join(BASE, "journals", "trades.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=TRADE_COLUMNS)
    try:
        df = pd.read_csv(path, on_bad_lines="skip")
    except Exception:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    if df.empty or not {"timestamp", "symbol", "status"}.issubset(df.columns):
        return pd.DataFrame(columns=TRADE_COLUMNS)
    return df.dropna(subset=["symbol"]).tail(limit).iloc[::-1]


PHASE_META = {
    "cycle_start": ("Cycle starting", TV_BLUE),
    "market_data": ("Pulling market data", TV_BLUE),
    "indicators": ("Computing indicators", TV_BLUE),
    "llm_council": ("LLM council voting", TV_GREEN),
    "decision": ("Council decision reached", INK),
    "execution": ("Executing order", "#b45309"),
    "exits": ("Managing exits", TV_BLUE),
    "idle": ("Idle &middot; next cycle scheduled", MUTED),
}


def money(value, decimals=0):
    try:
        return f"${float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "$0"


config = load_config()

has_alpaca = bool(os.environ.get("ALPACA_API_KEY")) and bool(os.environ.get("ALPACA_SECRET_KEY"))
llm_provider = (
    "Groq + NVIDIA" if (os.environ.get("GROQ_API_KEY") and os.environ.get("NVIDIA_API_KEY"))
    else ("Groq Llama" if os.environ.get("GROQ_API_KEY")
          else ("Anthropic" if os.environ.get("ANTHROPIC_API_KEY")
                else ("OpenAI" if os.environ.get("OPENAI_API_KEY") else None)))
)

@st.cache_resource
def start_background_trading_engine():
    if not (os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_SECRET_KEY")):
        return False
    try:
        import threading
        from run import build
        from engine import TradingEngine
        
        cfg = load_config()
        b_client, m_bridge, l_client = build(cfg, dry_run=False)
        if b_client:
            eng = TradingEngine(b_client, m_bridge, l_client, cfg, dry_run=False)
            t = threading.Thread(target=eng.run_forever, name="engine-worker", daemon=True)
            t.start()
            return True
    except Exception as exc:
        print(f"Background engine startup note: {exc}")
    return False

start_background_trading_engine()

broker = None
if has_alpaca:
    try:
        from broker.alpaca_client import AlpacaBroker

        broker = AlpacaBroker(
            os.environ["ALPACA_API_KEY"],
            os.environ["ALPACA_SECRET_KEY"],
            paper=True,
        )
    except Exception as exc:
        st.sidebar.error(f"Alpaca error: {exc}")

with st.sidebar:
    st.markdown("### AI Trading Council")
    st.caption("Options-native multi-agent trading on Alpaca")

    state = load_engine_state()
    phase = state.get("phase", "")
    label, _accent = PHASE_META.get(phase, ("Waiting for first cycle", MUTED))
    running = phase not in ("", "idle")
    dot_cls = "live-dot" if running else "idle-dot"
    st.markdown(
        f'<div style="padding:10px 0"><span class="{dot_cls}"></span>'
        f'<span class="phase-pill">{label}</span></div>',
        unsafe_allow_html=True,
    )
    if state:
        sym_html = (
            f' &nbsp;<span class="mono">&middot; <b>{state.get("symbol")}</b></span>'
            if state.get("symbol") else ""
        )
        st.markdown(
            f'<span class="muted">{state.get("message","")}</span>{sym_html}',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**SYSTEM**")
    st.markdown(
        f'<div class="sys-row"><span class="{"dot-ok" if has_alpaca else "dot-off"}"></span>'
        f'Alpaca Paper {"connected" if has_alpaca else "keys missing"}</div>',
        unsafe_allow_html=True,
    )
    brain = llm_provider or "fallback votes"
    brain_dot = "dot-ok" if llm_provider else "dot-off"
    st.markdown(
        f'<div class="sys-row"><span class="{brain_dot}"></span>Brain: <b>&nbsp;{brain}</b></div>',
        unsafe_allow_html=True,
    )
    if state.get("llm_model"):
        st.markdown(f"<span class='muted mono'>{state['llm_model']}</span>", unsafe_allow_html=True)

    symbols = []
    symbols_path = os.path.join(BASE, config.get("symbols_file", "symbols.txt"))
    try:
        with open(symbols_path, "r", encoding="utf-8") as handle:
            for line in handle:
                token = line.split("#")[0].strip().upper()
                if token and token not in symbols:
                    symbols.append(token)
    except OSError:
        symbols = config.get("symbols", [])
    if symbols:
        st.markdown("**WATCHLIST**")
        st.markdown("".join(f"<span class='ticker-chip'>{s}</span>" for s in symbols), unsafe_allow_html=True)

    st.divider()
    log_path = os.path.join(BASE, "engine.log")
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="ignore") as handle:
            st.download_button("Download engine.log", handle.read(), file_name="engine.log")

account, positions = {}, []
clock = {}
if broker:
    account = broker.get_account() or {}
    positions = broker.get_positions()
    clock = broker.get_clock() or {}

header_l, header_r = st.columns([3, 1])
with header_l:
    st.title("AI Trading Council")
now_utc = datetime.now(timezone.utc)
session_day = now_utc.weekday() < 5
if clock.get("is_open"):
    mkt_label, mkt_color = "MARKET OPEN", TV_GREEN
elif not session_day:
    mkt_label, mkt_color = "WEEKEND &middot; MARKET CLOSED", "#b45309"
else:
    mkt_label, mkt_color = "MARKET CLOSED", "#b45309"
header_r.markdown(
    f"""<div style='text-align:right;padding-top:10px'>
    <span style='color:{mkt_color};font-weight:800;font-size:.85rem;letter-spacing:.05em'>
    &#9679;&nbsp;{mkt_label}</span><br>
    <span style='color:{MUTED};font-size:.8rem;font-variant-numeric:tabular-nums'>
    {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</span>
    </div>""",
    unsafe_allow_html=True,
)
st.caption("Multi-agent LLM council &middot; options-native execution &middot; Alpaca paper trading")

unrealized = sum(p.get("unrealized_pl", 0) for p in positions)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Equity", money(account.get("equity", 0)))
c2.metric("Cash available", money(account.get("cash", 0)))
c3.metric("Open positions", len(positions))
c4.metric("Unrealized P&L", money(unrealized, 2), delta=f"{unrealized:+,.2f}",
          delta_color="normal" if unrealized != 0 else "off")

tab_live, tab_council, tab_exec, tab_perf = st.tabs(
    ["LIVE AGENT", "COUNCIL DECISIONS", "ORDERS & POSITIONS", "PERFORMANCE"]
)

with tab_live:
    @st.fragment(run_every=6)
    def live_panel():
        state = load_engine_state()
        phase = state.get("phase", "")
        label, accent = PHASE_META.get(phase, ("Waiting for first cycle", MUTED))
        ts = str(state.get("timestamp", ""))[:19].replace("T", " ")

        lcol, rcol = st.columns([2, 1])
        with lcol:
            running = phase not in ("", "idle")
            dot = '<span class="live-dot"></span>' if running else '<span class="idle-dot"></span>'
            st.markdown(
                f"<div style='padding:6px 0 2px'>{dot}"
                f"<span style='font-size:1.06rem;font-weight:700;color:{INK}'>&nbsp;{label}</span></div>",
                unsafe_allow_html=True,
            )
            if state.get("message"):
                sym = state.get("symbol")
                st.markdown(
                    (f"<span class='ticker-chip'>{sym}</span>" if sym else "")
                    + f"<span class='muted'>{state.get('message')}</span>",
                    unsafe_allow_html=True,
                )
        with rcol:
            if ts:
                st.markdown(
                    "<div style='text-align:right;padding-top:10px'>"
                    f"<span class='muted mono'>last update {ts} UTC</span></div>",
                    unsafe_allow_html=True,
                )
        st.divider()

        st.subheader("Latest verdicts")
        df = load_decisions(12)
        if df.empty:
            st.info("No decisions yet — verdicts appear the moment the council finishes a symbol.")
        for _, row in df.iterrows():
            is_trade = row["action"] != "hold"
            badge = "TRADE SIGNAL" if is_trade else "HOLD"
            badge_color = TV_BLUE if is_trade else MUTED
            try:
                votes = json.loads(row["votes"])
                chips = "".join(
                    f"<span class='vote-chip vote-{v['direction']}'>{v['brain']} "
                    f"{v['direction'].upper()} {v['confidence']:.2f}</span>"
                    for v in votes
                )
            except Exception:
                chips = ""
            veto = ""
            vr = row.get("veto_reason")
            if isinstance(vr, str) and vr:
                veto = (f"<div class='muted' style='margin-top:6px'>&#128737; "
                        f"<b style='color:{TV_RED}'>VETO</b> &middot; {vr}</div>")
            st.markdown(
                f"""<div class="decision-card {'trade' if is_trade else ''}">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="mono" style="font-weight:800;font-size:1.02rem">{row['symbol']}</span>
                    <span style="color:{badge_color};font-weight:800;font-size:.78rem;
                                  letter-spacing:.08em">{badge}</span>
                </div>
                <div class="muted" style="margin:3px 0 8px">{row['summary']}</div>
                <div>{chips}</div>{veto}
                <div class="muted mono" style="margin-top:6px;font-size:.75rem">
                    {str(row['timestamp'])[:19].replace('T',' ')} UTC</div>
                </div>""",
                unsafe_allow_html=True,
            )

    live_panel()

with tab_council:
    df = load_decisions(60)
    if df.empty:
        st.caption("No decisions journaled yet.")
    else:
        show = df.copy()
        show["timestamp"] = show["timestamp"].astype(str).str.slice(0, 19)
        st.dataframe(
            show[["timestamp", "symbol", "action", "confidence", "summary", "veto_reason"]],
            width="stretch",
            hide_index=True,
        )
        st.caption("Full per-brain reasoning stored in journals/decisions.csv")

def format_relative_time(iso_str):
    if not iso_str:
        return "Just started"
    try:
        t = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = max(0, int((now - t).total_seconds()))
        if diff < 60:
            return f"{diff}s ago"
        elif diff < 3600:
            return f"{diff // 60}m ago"
        else:
            return f"{diff // 3600}h ago"
    except Exception:
        return str(iso_str)[:19].replace("T", " ")

with tab_exec:
    # 1. Portfolio Diversification & Risk Allocation Bar
    if account:
        eq = float(account.get("equity", 0) or 0)
        c_bal = float(account.get("cash", 0) or 0)
        crypto_val = sum(
            float(p.get("market_value", float(p.get("current_price", 0)) * float(p.get("qty", 0))))
            for p in positions if p.get("asset_class") == "crypto"
        )
        stocks_val = sum(
            float(p.get("market_value", float(p.get("current_price", 0)) * float(p.get("qty", 0))))
            for p in positions if p.get("asset_class") != "crypto"
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cash Reserve", money(c_bal), delta=f"{(c_bal/eq*100) if eq>0 else 0:.1f}% (Buffer >=20%)")
        c2.metric("Crypto Exposure", money(crypto_val), delta=f"{(crypto_val/eq*100) if eq>0 else 0:.1f}% / 20% max cap", delta_color="normal" if (crypto_val/eq <= 0.20 if eq>0 else True) else "inverse")
        c3.metric("Equities & Options", money(stocks_val), delta=f"{(stocks_val/eq*100) if eq>0 else 0:.1f}% allocation")
        c4.metric("Active Risk Limit", "10% per Asset", delta="Dynamic Breakeven & Trailing")

    st.divider()

    # 2. Open Positions Table with Trade Open Timestamps
    st.subheader("Open positions & live AI trend diagnosis")
    if positions:
        pos_df = pd.DataFrame(positions)
        tracking = load_position_tracking()

        peak_prices = []
        protections = []
        return_pcts = []
        trends = []
        signals = []
        evaluated = []
        opened_times = []
        all_recent_orders = broker.get_order_history(limit=50) if broker and hasattr(broker, "get_order_history") else []
        eng_state = load_engine_state()

        for _, r in pos_df.iterrows():
            sym = r.get("symbol", "")
            clean_sym = str(sym).replace("/", "").upper()
            entry = float(r.get("avg_entry_price") or 0)
            curr = float(r.get("current_price") or entry)
            ret = ((curr / entry - 1) * 100) if entry > 0 else 0.0
            return_pcts.append(f"{ret:+.2f}%")

            track = tracking.get(sym, {})
            peak = float(track.get("peak_price") or curr)
            peak_prices.append(f"${peak:,.2f}" if peak > 0 else f"${curr:,.2f}")

            trends.append(track.get("trend_status", "🟢 Bullish Momentum"))
            signals.append(track.get("trend_details", "EMA50 bullish · RSI healthy"))

            plan = track.get("action_plan")
            if not plan:
                if track.get("breakeven_active"):
                    plan = "🛡️ Breakeven Active"
                elif float(track.get("peak_gain_pct") or 0) >= 0.04:
                    plan = "📈 Trailing Stop Active"
                else:
                    needed = max(0.0, (0.03 - (ret / 100))) * 100
                    plan = f"⏳ Breakeven at +3.0% (needs +{needed:.2f}%)"
            protections.append(plan)

            # 1. Resolve exact Open Timestamp from tracking or broker fill history
            ent_time = track.get("entry_time")
            if not ent_time and all_recent_orders:
                matching = [
                    o for o in all_recent_orders
                    if str(o.get("symbol", "")).replace("/", "").upper() == clean_sym
                    and o.get("side") == "BUY"
                    and o.get("status") == "FILLED"
                ]
                if matching:
                    ent_time = matching[0].get("filled_at") or matching[0].get("created_at")

            if ent_time:
                opened_times.append(f"{str(ent_time)[:16].replace('T', ' ')} UTC ({format_relative_time(ent_time)})")
            else:
                opened_times.append(f"{format_relative_time(eng_state.get('timestamp'))}")

            # 2. Resolve exact Last Evaluated relative time
            eval_t = track.get("last_checked") or eng_state.get("timestamp")
            evaluated.append(format_relative_time(eval_t))

        pos_df["return_pct"] = return_pcts
        pos_df["ai_trend"] = trends
        pos_df["technical_signals"] = signals
        pos_df["safety_plan"] = protections
        pos_df["opened_at"] = opened_times
        pos_df["last_checked"] = evaluated

        cols = [
            c for c in ("symbol", "side", "qty", "avg_entry_price",
                        "current_price", "return_pct", "unrealized_pl", "ai_trend", "technical_signals", "safety_plan", "opened_at", "last_checked")
            if c in pos_df.columns
        ]
        st.dataframe(pos_df[cols], width="stretch", hide_index=True)
    else:
        st.caption("No open positions.")

    st.divider()

    # 3. Timeline & Calendar Filter Controls
    st.subheader("Trade history & executed order fills")
    f1, f2, f3 = st.columns([2, 2, 2])
    with f1:
        time_filter = st.selectbox(
            "Timeline Filter",
            ["All History", "Today", "Last 7 Days", "Last 30 Days", "Custom Date Range"],
            index=0,
        )
    with f2:
        view_filter = st.selectbox(
            "View Filter",
            ["Closed Trades (P&L Audit)", "All Executed Order Fills", "Working Orders"],
            index=0,
        )
    with f3:
        if time_filter == "Custom Date Range":
            custom_dates = st.date_input("Select Date Range", value=(date.today() - timedelta(days=7), date.today()))
        else:
            custom_dates = None

    # Calculate cutoff date for filtering
    cutoff = None
    today = date.today()
    if time_filter == "Today":
        cutoff = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    elif time_filter == "Last 7 Days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    elif time_filter == "Last 30 Days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # 4. Closed Round-Trip Trades (P&L Audit Log)
    if view_filter == "Closed Trades (P&L Audit)":
        closed_trades = broker.get_closed_trades() if broker else []
        if closed_trades:
            ct_df = pd.DataFrame(closed_trades)

            # Apply date filters
            if cutoff and "exit_time" in ct_df.columns:
                ct_df["exit_dt"] = pd.to_datetime(ct_df["exit_time"], utc=True)
                ct_df = ct_df[ct_df["exit_dt"] >= cutoff]
            elif custom_dates and len(custom_dates) == 2 and "exit_time" in ct_df.columns:
                ct_df["exit_dt"] = pd.to_datetime(ct_df["exit_time"], utc=True).dt.date
                ct_df = ct_df[(ct_df["exit_dt"] >= custom_dates[0]) & (ct_df["exit_dt"] <= custom_dates[1])]

            if not ct_df.empty:
                # Format columns
                show_ct = ct_df.copy()
                show_ct["realized_pnl"] = show_ct["realized_pnl"].apply(lambda v: f"+${v:,.2f}" if v > 0 else (f"-${abs(v):,.2f}" if v < 0 else "$0.00"))
                show_ct["return_pct"] = show_ct["return_pct"].apply(lambda v: f"{v:+.2f}%")
                show_ct["result"] = show_ct["result"].apply(lambda r: "🟢 WIN" if r == "WIN" else ("🔴 LOSS" if r == "LOSS" else "🛡️ BREAKEVEN"))
                show_ct["entry_time"] = show_ct["entry_time"].astype(str).str.slice(0, 19).str.replace("T", " ")
                show_ct["exit_time"] = show_ct["exit_time"].astype(str).str.slice(0, 19).str.replace("T", " ")

                cols = [c for c in ("symbol", "qty", "buy_price", "sell_price", "realized_pnl", "return_pct", "result", "duration", "entry_time", "exit_time") if c in show_ct.columns]
                st.dataframe(show_ct[cols], width="stretch", hide_index=True)
            else:
                st.caption("No closed trades in selected timeline.")
        else:
            st.caption("No closed trades recorded yet.")

    elif view_filter == "All Executed Order Fills":
        orders = broker.get_order_history(limit=150) if broker else []
        if orders:
            ord_df = pd.DataFrame(orders)
            if cutoff and "filled_at" in ord_df.columns:
                ord_df["dt"] = pd.to_datetime(ord_df["filled_at"].fillna(ord_df["created_at"]), utc=True)
                ord_df = ord_df[ord_df["dt"] >= cutoff]

            if not ord_df.empty:
                show_ord = ord_df.copy()
                show_ord["side"] = show_ord["side"].apply(lambda s: "🟢 BUY" if s == "BUY" else "🔴 SELL")
                show_ord["status"] = show_ord["status"].apply(lambda st_: "🟢 FILLED" if st_ == "FILLED" else ("🔵 WORKING" if st_ in ("NEW", "ACCEPTED") else f"⚪ {st_}"))
                show_ord["time"] = show_ord["filled_at"].fillna(show_ord["created_at"]).astype(str).str.slice(0, 19).str.replace("T", " ")
                show_ord["total_value"] = show_ord["total_value"].apply(lambda v: f"${v:,.2f}")

                cols = [c for c in ("time", "symbol", "side", "qty", "filled_avg_price", "total_value", "status", "client_order_id") if c in show_ord.columns]
                st.dataframe(show_ord[cols], width="stretch", hide_index=True)
            else:
                st.caption("No orders found in selected timeline.")
        else:
            st.caption("No order history available.")

    else:
        st.subheader("Working orders")
        w_orders = broker.get_open_orders() if broker else []
        if w_orders:
            st.code("\n".join(w_orders), language=None)
        else:
            st.caption("No working orders.")

with tab_perf:
    st.subheader("Performance analytics & portfolio scorecard")

    # 1. Interactive Timeline Filter
    t1, t2, t3, t4, t5 = st.columns(5)
    time_choice = st.radio(
        "Select Performance Period",
        ["1D (Today)", "1W (7 Days)", "1M (30 Days)", "3M (90 Days)", "1A (1 Year)"],
        index=2,
        horizontal=True,
    )

    days_map = {
        "1D (Today)": 1,
        "1W (7 Days)": 7,
        "1M (30 Days)": 30,
        "3M (90 Days)": 90,
        "1A (1 Year)": 365,
    }
    sel_days = days_map.get(time_choice, 30)

    if broker:
        history = broker.get_portfolio_history(days=sel_days)
        closed_trades = broker.get_closed_trades()

        # Calculate rich stats from closed trades
        total_closed = len(closed_trades)
        wins = [t for t in closed_trades if t.get("result") == "WIN"]
        losses = [t for t in closed_trades if t.get("result") == "LOSS"]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0.0

        gross_profits = sum(float(t.get("realized_pnl", 0)) for t in wins)
        gross_losses = abs(sum(float(t.get("realized_pnl", 0)) for t in losses))
        profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else (gross_profits if gross_profits > 0 else 1.0)
        net_realized = sum(float(t.get("realized_pnl", 0)) for t in closed_trades)

        avg_win = (gross_profits / win_count) if win_count > 0 else 0.0
        avg_loss = (gross_losses / loss_count) if loss_count > 0 else 0.0

        # Scorecard Row
        m1, m2, m3, m4 = st.columns(4)
        if history:
            hist_df = pd.DataFrame(history)
            hist_df["time"] = pd.to_datetime(hist_df["timestamp"], unit="s")
            hist_df = hist_df.set_index("time")
            start_eq = float(hist_df["equity"].iloc[0])
            end_eq = float(hist_df["equity"].iloc[-1])
            growth_dollar = end_eq - start_eq
            growth_pct = ((end_eq / start_eq - 1) * 100) if start_eq > 0 else 0.0

            m1.metric("Portfolio Equity", money(end_eq), delta=f"{growth_dollar:+,.2f} ({growth_pct:+.2f}%)")

            peak = hist_df["equity"].cummax()
            dd = ((hist_df["equity"] / peak) - 1).min() * 100
            rets = hist_df["equity"].pct_change().dropna()
            sharpe = (rets.mean() / rets.std() * (252 ** 0.5)) if len(rets) > 2 and rets.std() > 0 else 0.0

            m2.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{win_count} Wins / {loss_count} Losses")
            m3.metric("Net Realized P&L", f"${net_realized:+,.2f}", delta=f"Profit Factor: {profit_factor:.2f}")
            m4.metric("Sharpe & Drawdown", f"{sharpe:.2f} Sharpe", delta=f"Max DD: {dd:.2f}%", delta_color="inverse" if dd < -5 else "normal")

            st.divider()

            # Equity Curve Chart
            st.subheader(f"Equity curve ({time_choice})")
            st.line_chart(hist_df["equity"], height=320, color=TV_GREEN)

            # Trades P&L breakdown
            if closed_trades:
                st.subheader("Closed trades P&L distribution")
                ct_df = pd.DataFrame(closed_trades)
                pnl_series = ct_df.set_index("symbol")["realized_pnl"]
                st.bar_chart(pnl_series, height=220)
        else:
            st.caption("No portfolio history yet.")
    else:
        st.caption("Connect Alpaca keys to see performance.")
