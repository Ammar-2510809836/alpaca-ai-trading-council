import json
import os
from datetime import datetime, timezone

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

with tab_exec:
    left, right = st.columns(2)
    with left:
        st.subheader("Open positions")
        if positions:
            pos_df = pd.DataFrame(positions)
            cols = [
                c for c in ("symbol", "underlying", "side", "qty", "avg_entry_price",
                            "current_price", "unrealized_pl")
                if c in pos_df.columns
            ]
            st.dataframe(pos_df[cols], width="stretch", hide_index=True)
        else:
            st.caption("No open positions.")
    with right:
        st.subheader("Working orders")
        orders = broker.get_open_orders() if broker else []
        if orders:
            st.code("\n".join(orders), language=None)
        else:
            st.caption("No working orders.")

    st.subheader("Trade journal")
    trades_df = load_trades(40)
    if trades_df.empty:
        st.caption("No fills recorded yet.")
    else:
        st.dataframe(trades_df, width="stretch", hide_index=True)

with tab_perf:
    if broker:
        history = broker.get_portfolio_history(days=30)
        if history:
            hist_df = pd.DataFrame(history)
            hist_df["time"] = pd.to_datetime(hist_df["timestamp"], unit="s")
            hist_df = hist_df.set_index("time")
            start_eq = hist_df["equity"].iloc[0]
            end_eq = hist_df["equity"].iloc[-1]
            k1, k2, k3 = st.columns(3)
            k1.metric("Equity (30d)", money(end_eq), delta=money(end_eq - start_eq))
            peak = hist_df["equity"].cummax()
            dd = ((hist_df["equity"] / peak) - 1).min() * 100
            k2.metric("Max drawdown (30d)", f"{dd:.2f}%")
            rets = hist_df["equity"].pct_change().dropna()
            sharpe = (rets.mean() / rets.std() * (252 ** 0.5)) if len(rets) > 2 and rets.std() > 0 else 0
            k3.metric("Sharpe (annualized)", f"{sharpe:.2f}")
            st.line_chart(hist_df["equity"], height=330, color=TV_GREEN)
        else:
            st.caption("No portfolio history yet.")
    else:
        st.caption("Connect Alpaca keys to see performance.")
