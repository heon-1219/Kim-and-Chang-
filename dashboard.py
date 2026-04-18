"""
Kim and Chang Trading Technologies — Streamlit Dashboard
Clean professional layout. Paper trading only — never places real orders.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import bcrypt
import pandas as pd
import plotly.graph_objects as go
import psutil
import streamlit as st
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

import broker
import db
from backtest import run_backtest
from strategies import STRATEGIES

db.init_db()

st.set_page_config(
    page_title="KC Trading Technologies",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_login() -> bool:
    if st.session_state.get("authenticated"):
        return True
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        st.markdown("""
        <div style="padding:2rem;background:#111827;border:1px solid #1e3a5f;
                    border-top:3px solid #00d4aa;border-radius:6px;margin-top:10vh;">
          <p style="font-size:0.65rem;letter-spacing:0.2em;color:#00d4aa;margin-bottom:0.25rem;">
            KIM AND CHANG</p>
          <p style="font-size:1.3rem;font-weight:700;margin:0 0 1.5rem;">TRADING TECHNOLOGIES</p>
        </div>""", unsafe_allow_html=True)
        with st.form("login"):
            st.text_input("Username", key="u")
            st.text_input("Password", type="password", key="p")
            if st.form_submit_button("Sign In", use_container_width=True, type="primary"):
                u, p = st.session_state.u, st.session_state.p.encode()
                if (u == st.secrets["auth"]["username"] and
                        bcrypt.checkpw(p, st.secrets["auth"]["hashed_password"].encode())):
                    st.session_state.update({"authenticated": True, "demo": False, "username": u})
                    st.rerun()
                elif (u == st.secrets["demo"]["username"] and
                        bcrypt.checkpw(p, st.secrets["demo"]["hashed_password"].encode())):
                    st.session_state.update({"authenticated": True, "demo": True, "username": u})
                    st.rerun()
                else:
                    st.error("Invalid credentials.")
    return False

if not _check_login():
    st.stop()

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""<style>
[data-testid="stSidebarCollapsedControl"] { display:none; }
.block-container { max-width:100% !important; padding-top:0.5rem !important; padding-bottom:0.5rem !important; }
hr { border-color:#1e3a5f !important; margin:0.4rem 0 !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:6px !important; }
/* make metric label uppercase */
[data-testid="stMetricLabel"] > div { text-transform:uppercase; font-size:0.65rem !important; letter-spacing:0.08em; }
</style>""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

_CHART = dict(
    paper_bgcolor="#0a0e1a", plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(l=0, r=8, t=18, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
    hovermode="x unified",
)
_NO_TB = {"displayModeBar": False}

# Per-strategy colours for chart markers
_STRAT_CLR = {
    "rsi":          "#4ecdc4",
    "macd":         "#f7b731",
    "bollinger":    "#a29bfe",
    "ema_crossover":"#fd9644",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _panel_header(title: str, help_md: str = "") -> None:
    """Section title with optional ? popover button."""
    if help_md:
        c1, c2 = st.columns([11, 1])
        with c1:
            st.markdown(
                f'<p style="font-size:0.7rem;font-weight:600;letter-spacing:0.1em;'
                f'color:#00d4aa;text-transform:uppercase;margin:0 0 4px;">{title}</p>',
                unsafe_allow_html=True)
        with c2:
            with st.popover("?"):
                st.markdown(help_md)
    else:
        st.markdown(
            f'<p style="font-size:0.7rem;font-weight:600;letter-spacing:0.1em;'
            f'color:#00d4aa;text-transform:uppercase;margin:0 0 4px;">{title}</p>',
            unsafe_allow_html=True)

def _num_style(v) -> str:
    try:
        n = float(str(v).replace("$","").replace(",","").replace("%","").replace("+",""))
        if n > 0: return "color:#00c896"
        if n < 0: return "color:#ff4b4b"
    except (ValueError, TypeError): pass
    return ""

def _side_style(v) -> str:
    return {"buy":"color:#00c896;font-weight:600", "sell":"color:#ff4b4b;font-weight:600"}.get(v, "")

@st.cache_data(ttl=30)
def _sys_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=0.5)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    up   = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    h    = int(up.total_seconds()) // 3600
    return dict(cpu=cpu, ram_pct=mem.percent, ram_used=mem.used>>20, ram_total=mem.total>>20,
                disk_pct=disk.percent, disk_used=disk.used>>30, disk_total=disk.total>>30,
                uptime=f"{h//24}d {h%24}h" if h>=24 else f"{h}h {int(up.total_seconds()%3600)//60}m")

def _bar_html(label: str, pct: float, note: str = "") -> str:
    c = "#00c896" if pct < 70 else "#ffa500" if pct < 90 else "#ff4b4b"
    note_html = f' <span style="color:#4a6a90;font-size:0.62rem;">{note}</span>' if note else ""
    return (
        f'<div style="margin:4px 0 7px;">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
        f'<span style="color:#6b8bb0;font-size:0.68rem;">{label}{note_html}</span>'
        f'<span style="color:#e2e8f0;font-family:monospace;font-size:0.68rem;font-weight:600;">'
        f'{pct:.0f}%</span>'
        f'</div>'
        f'<div style="background:#1e3a5f;border-radius:3px;height:5px;">'
        f'<div style="background:{c};width:{min(pct,100):.0f}%;height:100%;border-radius:3px;">'
        f'</div></div>'
        f'</div>'
    )

@st.cache_data(ttl=300)
def _portfolio_history(period: str = "1M") -> pd.DataFrame | None:
    try:
        ph = broker.get_portfolio_history(period=period, timeframe="1D")
        if not ph.timestamp:
            return None
        df = pd.DataFrame({"date": pd.to_datetime(ph.timestamp, unit="s"),
                           "equity": ph.equity}).dropna()
        return df if not df.empty else None
    except Exception:
        return None

def _equity_fig(df: pd.DataFrame, trades: list, show_strats: list[str],
                height: int = 200) -> go.Figure:
    up    = df["equity"].iloc[-1] >= df["equity"].iloc[0]
    color = "#00c896" if up else "#ff4b4b"
    fill  = "rgba(0,200,150,0.08)" if up else "rgba(255,75,75,0.08)"
    fig   = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["equity"], mode="lines", fill="tozeroy",
        fillcolor=fill, line=dict(color=color, width=2), name="Portfolio",
        hovertemplate="$%{y:,.2f}<extra></extra>"))

    # Overlay trade markers per strategy
    if trades and show_strats:
        df_t = pd.DataFrame(trades)
        if {"timestamp","strategy"}.issubset(df_t.columns):
            df_t["ts"] = pd.to_datetime(df_t["timestamp"])
            df_eq = df.set_index("date")["equity"].sort_index()
            for strat in show_strats:
                sd = df_t[df_t["strategy"] == strat].copy()
                if sd.empty:
                    continue
                merged = pd.concat([df_eq,
                                    pd.Series(float("nan"), index=sd["ts"])]
                                   ).sort_index().interpolate("time")
                y_vals = merged.loc[sd["ts"].values].values
                fig.add_trace(go.Scatter(
                    x=sd["ts"], y=y_vals, mode="markers",
                    name=strat.upper(),
                    marker=dict(size=9, color=_STRAT_CLR.get(strat,"#fff"),
                                symbol="circle", line=dict(color="#0a0e1a", width=1.5)),
                    hovertemplate=(f"<b>{strat.upper()}</b><br>%{{x|%Y-%m-%d}}"
                                   f"<br>$%{{y:,.0f}}<extra></extra>")))
    fig.update_layout(**_CHART, height=height)
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return fig

def _trades_fig(trades: list, strategy_filter: list[str] | None,
                height: int = 180) -> go.Figure:
    chart_cfg = {**_CHART, "hovermode": "closest"}
    fig = go.Figure()
    data = trades or []
    if strategy_filter:
        data = [t for t in data if t.get("strategy") in strategy_filter]
    if data:
        df = pd.DataFrame(data)
        df["ts"] = pd.to_datetime(df["timestamp"])
        for col, default in [("symbol","?"),("actual_price",0.0),("strategy","?"),("quantity",1)]:
            if col not in df.columns:
                df[col] = default
        df["quantity"] = df["quantity"].astype(float)
        for side, color, name in [("buy","#00c896","Buy"),("sell","#ff4b4b","Sell")]:
            sd = df[df["side"] == side].copy()
            if not sd.empty:
                fig.add_trace(go.Bar(
                    x=sd["ts"], y=sd["quantity"], name=name,
                    marker_color=color, marker_opacity=0.8,
                    customdata=sd[["symbol","actual_price","strategy","timestamp"]].values,
                    hovertemplate=(
                        f"<b>%{{customdata[0]}}</b> — {name}<br>"
                        "Qty: <b>%{y:.0f}</b><br>"
                        "Price: $%{customdata[1]:.2f}<br>"
                        "Strategy: %{customdata[2]}<br>"
                        "%{customdata[3]}<extra></extra>")))
    else:
        fig.add_annotation(text="No trades recorded yet", x=0.5, y=0.5,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(color="#4a6a90", size=12))
    fig.update_layout(**chart_cfg, height=height, barmode="overlay")
    return fig

# ── Demo data ─────────────────────────────────────────────────────────────────

DEMO = st.session_state.get("demo", False)

def _demo_account():
    class _A:
        equity=101_842.67; cash=48_231.10; buying_power=96_462.20; last_equity=99_980.00
    return _A()

def _demo_positions():
    class _P:
        def __init__(self, sym, qty, entry, cur, val, pl, plpc):
            self.symbol=sym; self.qty=qty; self.avg_entry_price=entry
            self.current_price=cur; self.market_value=val
            self.unrealized_pl=pl; self.unrealized_plpc=plpc
    return [_P("AAPL",10,171.42,178.91,1789.10,74.90,0.0437),
            _P("MSFT",5, 415.80,421.33,2106.65,27.65,0.0133),
            _P("GOOGL",8,172.10,169.55,1356.40,-20.40,-0.0148)]

_SAMPLE_POSITIONS = [
    {"Symbol":"AAPL","Qty":10,"Price":178.91,"P&L ($)": 74.90,"P&L (%)": 4.37},
    {"Symbol":"MSFT","Qty": 5,"Price":421.33,"P&L ($)": 27.65,"P&L (%)": 1.33},
    {"Symbol":"GOOGL","Qty":8,"Price":169.55,"P&L ($)":-20.40,"P&L (%)":-1.48},
]

def _demo_trades():
    return [
        {"timestamp":"2026-04-17 14:32","symbol":"AAPL","side":"buy","quantity":10,"actual_price":171.42,"strategy":"rsi"},
        {"timestamp":"2026-04-16 10:11","symbol":"MSFT","side":"buy","quantity":5, "actual_price":415.80,"strategy":"macd"},
        {"timestamp":"2026-04-15 15:47","symbol":"GOOGL","side":"sell","quantity":8,"actual_price":169.55,"strategy":"rsi"},
        {"timestamp":"2026-04-14 09:35","symbol":"TSLA","side":"buy","quantity":3, "actual_price":242.10,"strategy":"bollinger"},
        {"timestamp":"2026-04-13 11:22","symbol":"TSLA","side":"sell","quantity":3,"actual_price":251.80,"strategy":"bollinger"},
    ]

def _demo_logs():
    return [
        {"timestamp":"2026-04-18 09:00","level":"INFO", "message":"Bot cycle started"},
        {"timestamp":"2026-04-18 08:55","level":"INFO", "message":"RSI: AAPL → hold"},
        {"timestamp":"2026-04-18 08:50","level":"WARN", "message":"API rate limit approaching: 178/200"},
        {"timestamp":"2026-04-17 15:30","level":"ERROR","message":"Order rejected: insufficient buying power"},
        {"timestamp":"2026-04-17 14:32","level":"INFO", "message":"BUY AAPL qty=10 @ $171.42"},
    ]

def _demo_ph() -> pd.DataFrame:
    import numpy as np
    rng  = pd.date_range(end=datetime.utcnow(), periods=30, freq="D")
    vals = 100_000 * (1 + pd.Series(np.random.randn(30).cumsum() * 0.007)).values
    return pd.DataFrame({"date": rng, "equity": vals})

# ── Load runtime data ─────────────────────────────────────────────────────────

hb      = None if DEMO else db.get_heartbeat()
cfg     = {"trading_enabled":"true","active_strategy":"rsi"} if DEMO else db.get_all_config()
now_utc = datetime.utcnow()
uname   = st.session_state.get("username", "—")
trades  = _demo_trades() if DEMO else db.get_recent_trades(limit=50)
logs    = _demo_logs()   if DEMO else db.get_recent_logs(limit=50)

try:
    ac   = _demo_account() if DEMO else broker.get_account()
    eq   = float(ac.equity)
    cash = float(ac.cash)
    bp   = float(ac.buying_power)
    leq  = float(ac.last_equity)
    pnl  = eq - leq
    pp   = (pnl / leq * 100) if leq else 0.0
except Exception:
    eq = cash = bp = pnl = pp = 0.0

if hb:
    age_min = int((now_utc - datetime.fromisoformat(hb["last_beat"])).total_seconds() / 60)
    alive   = (now_utc - datetime.fromisoformat(hb["last_beat"])) < timedelta(minutes=70)
    bot_lbl = ("🟢 ALIVE" if alive else "🔴 STALE") + f" ({age_min}m ago)"
else:
    alive, bot_lbl = False, "⚪ Not started"

on    = cfg.get("trading_enabled","true").lower() == "true"
strat = cfg.get("active_strategy","—").upper()
api_n = 0 if DEMO else db.count_recent_api_calls(60)

# Parse strategy allocations (JSON stored in db)
_alloc_raw  = cfg.get("strategy_allocation", "{}")
try:
    alloc_cfg: dict = json.loads(_alloc_raw)
except (json.JSONDecodeError, TypeError):
    alloc_cfg = {}

# ── HEADER ───────────────────────────────────────────────────────────────────

left_hdr, right_hdr = st.columns([7, 3])

with left_hdr:
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:0.8rem;flex-wrap:wrap;padding:0.2rem 0;">'
        f'<span style="font-size:0.6rem;letter-spacing:0.2em;color:#00d4aa;">KIM &amp; CHANG</span>'
        f'<span style="font-size:1.15rem;font-weight:700;">TRADING TECHNOLOGIES</span>'
        f'<span style="color:#1e3a5f;">|</span>'
        f'<span style="font-size:0.72rem;color:#6b8bb0;">{bot_lbl}</span>'
        f'<span style="font-size:0.72rem;color:{"#00c896" if on else "#ff4b4b"};">'
        f'{"🟢 Trading ON" if on else "🔴 Halted"}</span>'
        f'<span style="font-size:0.72rem;color:#6b8bb0;">Strategy: '
        f'<b style="color:#e2e8f0;">{strat}</b></span>'
        f'<span style="font-size:0.72rem;color:#6b8bb0;">API {api_n}/200 &nbsp; '
        f'{now_utc.strftime("%H:%M UTC")}</span>'
        f'</div>',
        unsafe_allow_html=True)

with right_hdr:
    u_col, r_col, l_col = st.columns([3, 1, 1])
    with u_col:
        st.markdown(
            f'<div style="display:flex;align-items:center;height:100%;">'
            f'<span style="font-size:0.72rem;color:#6b8bb0;">Signed in as&nbsp;'
            f'<b style="color:#00d4aa;">{uname.upper()}</b></span></div>',
            unsafe_allow_html=True)
    with r_col:
        if st.button("↺", help="Refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()
    with l_col:
        if st.button("⏻", help="Sign out", use_container_width=True):
            st.session_state.clear(); st.rerun()

# ── ACCOUNT METRICS ───────────────────────────────────────────────────────────

st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Portfolio Balance",  f"${eq:,.2f}")
m2.metric("Cash Available",     f"${cash:,.2f}")
m3.metric("Buying Power",       f"${bp:,.2f}")
m4.metric("Today P&L",         f"${pnl:+,.2f}", delta=f"{pp:+.2f}%")
st.divider()

# ── MAIN SECTION: charts (left) | data panels (right) ─────────────────────────

main_left, main_right = st.columns([3, 2], gap="medium")

with main_left:
    # ── Portfolio Equity ──────────────────────────────────────────────────────
    with st.container(border=True):
        _panel_header("Portfolio Equity", """
**How to use:**
- Select a period (1W / 1M / 3M / 1Y) to change the time range.
- Select one or more strategies below to overlay trade markers on the chart.
  Each coloured dot marks a trade made by that strategy.
- This chart shows *total* portfolio equity from Alpaca.
        """)
        per_col, strat_col = st.columns([1, 2])
        with per_col:
            period_key = st.radio("Period", ["1W","1M","3M","1Y"], index=1,
                                  horizontal=True, label_visibility="collapsed")
        with strat_col:
            overlay_strats = st.multiselect(
                "Show strategy trades", list(STRATEGIES.keys()),
                default=[], placeholder="Select strategies to overlay…",
                label_visibility="collapsed")
        period_map = {"1W":"1W","1M":"1M","3M":"3M","1Y":"1A"}
        ph = _demo_ph() if DEMO else _portfolio_history(period_map[period_key])
        if ph is not None:
            st.plotly_chart(_equity_fig(ph, trades, overlay_strats, height=200),
                            use_container_width=True, config=_NO_TB)
        else:
            st.info("No portfolio history available yet.")

    # ── Trade Activity ────────────────────────────────────────────────────────
    with st.container(border=True):
        all_strats = sorted({t.get("strategy","?") for t in trades} if trades else [])
        buys  = sum(1 for t in trades if t.get("side") == "buy")  if trades else 0
        sells = sum(1 for t in trades if t.get("side") == "sell") if trades else 0
        _panel_header(f"Trade Activity — {buys} buy · {sells} sell", """
**How to use:**
- Each bar represents one paper trade (green = buy, red = sell).
- Hover a bar to see full details: symbol, price, quantity, strategy, timestamp.
- Use the filter below to view only trades from specific strategies.
        """)
        filt = st.multiselect("Filter by strategy", all_strats, default=all_strats,
                              label_visibility="collapsed",
                              placeholder="All strategies shown")
        st.plotly_chart(_trades_fig(trades, filt or None, height=170),
                        use_container_width=True, config=_NO_TB)

with main_right:
    # ── Open Positions ────────────────────────────────────────────────────────
    with st.container(border=True):
        _panel_header("Open Positions", """
**How to use:**
- Shows all currently open paper-trading positions.
- P&L columns are colour-coded: green = profit, red = loss.
- When no live positions are held, sample data is shown for reference.
        """)
        try:
            pos = _demo_positions() if DEMO else broker.get_all_positions()
            if pos:
                rows = [{"Symbol":p.symbol,"Qty":float(p.qty),"Price":float(p.current_price),
                         "P&L ($)":float(p.unrealized_pl),"P&L (%)":float(p.unrealized_plpc)*100}
                        for p in pos]
                df_p = pd.DataFrame(rows)
                st.dataframe(
                    df_p.style
                        .format({"Price":"${:.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"})
                        .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                    use_container_width=True, hide_index=True, height=165)
            else:
                st.caption("No live positions. Showing illustrative sample:")
                df_p = pd.DataFrame(_SAMPLE_POSITIONS)
                st.dataframe(
                    df_p.style
                        .format({"Price":"${:.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"})
                        .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                    use_container_width=True, hide_index=True, height=135)
        except Exception as e:
            st.error(str(e))

    # ── Server + Safety ───────────────────────────────────────────────────────
    with st.container(border=True):
        srv_c, saf_c = st.columns([3, 2])
        with srv_c:
            _panel_header("Server")
            try:
                s = (dict(cpu=24,ram_pct=41,ram_used=3280,ram_total=7976,
                          disk_pct=18,disk_used=9,disk_total=50,uptime="12d 4h")
                     if DEMO else _sys_stats())
                st.markdown(
                    _bar_html("CPU",  s["cpu"])
                    + _bar_html("RAM",  s["ram_pct"],  f'{s["ram_used"]}/{s["ram_total"]} MB')
                    + _bar_html("Disk", s["disk_pct"], f'{s["disk_used"]}/{s["disk_total"]} GB')
                    + f'<p style="font-size:0.7rem;color:#6b8bb0;margin:5px 0 0;">Uptime: '
                    + f'<span style="color:#e2e8f0;font-family:monospace;">{s["uptime"]}</span></p>',
                    unsafe_allow_html=True)
            except Exception:
                st.caption("Stats unavailable")
        with saf_c:
            _panel_header("Safety")
            events = [] if DEMO else db.get_recent_safety_events(limit=4)
            if events:
                sdf = pd.DataFrame(events)
                cols = [c for c in ["timestamp","event"] if c in sdf.columns]
                st.dataframe(sdf[cols], use_container_width=True, hide_index=True, height=100)
            else:
                st.success("No safety events")

    # ── Bot Logs ──────────────────────────────────────────────────────────────
    with st.container(border=True):
        _panel_header("Bot Logs", """
**How to read:**
- **INFO** (grey) — routine status messages.
- **WARN** (amber) — non-critical warnings (e.g. rate limit approaching).
- **ERROR** (red) — failures that need attention.
        """)
        if logs:
            df_l = pd.DataFrame(logs)[["timestamp","level","message"]]
            LS   = {"ERROR":"color:#ff4b4b;font-weight:600",
                    "WARN": "color:#ffa500",
                    "INFO": "color:#6b8bb0"}
            st.dataframe(df_l.style.map(lambda v: LS.get(v,""), subset=["level"]),
                         use_container_width=True, hide_index=True, height=120)
        else:
            st.caption("No log entries yet.")

# ── BOTTOM SECTION: Backtest + Manual Trade | Configuration ────────────────────

st.divider()
bt_col, cfg_col = st.columns([2, 3], gap="medium")

# ── Backtest Engine ───────────────────────────────────────────────────────────
with bt_col:
    with st.container(border=True):
        _panel_header("Backtest Engine", """
**How to use:**
1. Enter a symbol (e.g. AAPL), choose a strategy, set a date range and starting capital.
2. Click **Run Backtest**. Results appear below.
3. Click **Add to comparison** to store a result, then run another backtest to compare curves.
4. Click **Clear** to reset stored comparisons.
        """)
        if DEMO:
            st.info("Demo mode — backtesting requires live API access.")
        else:
            b1, b2 = st.columns(2)
            with b1: sym_bt = st.text_input("Symbol", "AAPL", placeholder="AAPL").upper()
            with b2: strat_bt = st.selectbox("Strategy", list(STRATEGIES.keys()))
            b3, b4 = st.columns(2)
            with b3: s_bt = st.date_input("Start", date(2024,1,1))
            with b4: e_bt = st.date_input("End",   date.today())
            cap_bt = st.number_input("Starting capital ($)", value=100_000, step=10_000)

            run_c, add_c, clr_c = st.columns([2, 1, 1])
            with run_c:
                run_bt = st.button("▶  Run Backtest", type="primary", use_container_width=True)
            with add_c:
                add_bt = st.button("＋ Compare", use_container_width=True,
                                   disabled="bt" not in st.session_state)
            with clr_c:
                if st.button("✕ Clear", use_container_width=True):
                    st.session_state.pop("bt", None)
                    st.session_state.pop("bt_compare", None)
                    st.rerun()

            if run_bt:
                if s_bt >= e_bt:
                    st.error("Start must be before end.")
                else:
                    with st.spinner(f"Running {strat_bt.upper()} on {sym_bt}…"):
                        try:
                            st.session_state["bt"] = run_backtest(
                                sym_bt, strat_bt, s_bt, e_bt, float(cap_bt), cfg)
                            st.session_state["bt_lbl"] = (
                                f"{sym_bt}·{strat_bt.upper()}·{s_bt}→{e_bt}")
                        except Exception as ex:
                            st.error(str(ex))

            if add_bt and "bt" in st.session_state:
                comp = st.session_state.setdefault("bt_compare", {})
                lbl  = st.session_state.get("bt_lbl","run")
                comp[lbl] = st.session_state["bt"]

            if "bt" in st.session_state:
                m = st.session_state["bt"]["metrics"]
                st.caption(st.session_state.get("bt_lbl",""))
                r1, r2, r3, r4, r5 = st.columns(5)
                r1.metric("Return",   f"{m['total_return_pct']:+.2f}%")
                r2.metric("Sharpe",   f"{m['sharpe_ratio']:.2f}")
                r3.metric("Max DD",   f"{m['max_drawdown_pct']:.2f}%")
                r4.metric("Win %",    f"{m['win_rate_pct']:.0f}%")
                r5.metric("Trades",   m["total_trades"])

                # Build comparison chart (latest + any stored comparisons)
                compare = st.session_state.get("bt_compare", {})
                all_results = {**compare, st.session_state.get("bt_lbl","Latest"): st.session_state["bt"]}
                fig_bt = go.Figure()
                colors_bt = ["#00c896","#4ecdc4","#f7b731","#a29bfe","#fd9644"]
                for i, (lbl, res) in enumerate(all_results.items()):
                    eq_c = res.get("equity_curve", pd.DataFrame())
                    if not eq_c.empty:
                        up_c = res["metrics"]["total_return_pct"] >= 0
                        line_c = colors_bt[i % len(colors_bt)]
                        fig_bt.add_trace(go.Scatter(
                            x=eq_c["date"], y=eq_c["equity"],
                            mode="lines", name=lbl,
                            line=dict(color=line_c, width=1.5),
                            hovertemplate="$%{y:,.0f}<extra>" + lbl + "</extra>"))
                if fig_bt.data:
                    fig_bt.add_hline(
                        y=st.session_state["bt"]["metrics"]["starting_capital"],
                        line=dict(color="#444", width=1, dash="dot"))
                    fig_bt.update_layout(**_CHART, height=160)
                    fig_bt.update_yaxes(tickprefix="$", tickformat=",.0f")
                    st.plotly_chart(fig_bt, use_container_width=True, config=_NO_TB)

    # ── Manual Trade (No Strategy) ────────────────────────────────────────────
    with st.container(border=True):
        _panel_header("Manual Trade — No Strategy", """
**How to use:**
- Search any symbol (e.g. TSLA) and set the quantity.
- Choose Buy or Sell, then click **Submit**.
- This places a paper market order that executes at market price.
- Orders placed here are logged as "manual" and do not go through any strategy.
- **Paper trading only** — no real money is ever used.
        """)
        if DEMO:
            st.info("Demo mode — manual orders are disabled.")
        else:
            mt1, mt2 = st.columns(2)
            with mt1: mt_sym = st.text_input("Symbol", key="mt_sym", placeholder="e.g. TSLA").upper()
            with mt2: mt_qty = st.number_input("Quantity", min_value=1, step=1, key="mt_qty")
            mt3, mt4 = st.columns([1,1])
            with mt3: mt_side = st.radio("Side", ["Buy","Sell"], horizontal=True, key="mt_side")
            with mt4:
                st.markdown('<div style="height:22px;"></div>', unsafe_allow_html=True)
                submit_mt = st.button("Submit Paper Order", type="primary",
                                      use_container_width=True)
            if submit_mt:
                if not mt_sym:
                    st.error("Enter a symbol.")
                else:
                    try:
                        req = MarketOrderRequest(
                            symbol=mt_sym,
                            qty=mt_qty,
                            side=OrderSide.BUY if mt_side=="Buy" else OrderSide.SELL,
                            time_in_force=TimeInForce.DAY,
                        )
                        result = broker.submit_order(req)
                        st.success(f"Paper order submitted — {mt_side.upper()} {mt_qty}× {mt_sym}")
                    except Exception as ex:
                        st.error(str(ex))

# ── Configuration ─────────────────────────────────────────────────────────────
with cfg_col:
    with st.container(border=True):
        _panel_header("Configuration", """
**How to use:**
- **Trading enabled** — master kill switch. Disable to halt all bot activity.
- **Strategy Allocation** — enable one or more strategies and assign a percentage of
  portfolio equity to each. Allocations must total ≤ 100 %. Remaining equity stays as cash.
  *Note: running multiple strategies simultaneously requires the bot to be updated —
  contact your developer.*
- **Strategy Parameters** — tweak each active strategy's indicator settings.
- **Risk Limits** — caps that apply globally across all strategies.
- Click **Save Configuration** to persist all changes immediately.
        """)
        if DEMO:
            st.info("Demo mode — configuration is read-only.")
        else:
            # Trading kill switch
            en = cfg.get("trading_enabled","true").lower() == "true"
            ne = st.toggle("Trading enabled (master switch)", value=en)
            if ne != en:
                db.set_config("trading_enabled","true" if ne else "false")
                st.rerun()

            st.markdown("---")

            # ── Strategy Allocation ───────────────────────────────────────────
            st.markdown("**Strategy Allocation**")
            st.caption(
                "Enable strategies and set how much of the portfolio each manages. "
                "Total must be ≤ 100 %. Remaining equity stays as idle cash.")

            DESCS = {
                "rsi":          "RSI — 과매도 매수 · 과매수 매도 (횡보장)",
                "macd":         "MACD — 시그널 돌파 추세추종 (추세장)",
                "bollinger":    "Bollinger Bands — 밴드 이탈 역추세 (고변동성)",
                "ema_crossover":"EMA Crossover — 골든/데드크로스 추세추종",
            }

            enabled_strats: list[str] = []
            new_alloc: dict[str, int] = {}
            for strat_key in STRATEGIES:
                sc1, sc2, sc3 = st.columns([0.3, 2, 1])
                cur_en   = alloc_cfg.get(strat_key,{}).get("enabled", False)
                cur_pct  = alloc_cfg.get(strat_key,{}).get("alloc_pct", 0)
                with sc1:
                    is_en = st.checkbox("", value=cur_en, key=f"en_{strat_key}")
                with sc2:
                    st.markdown(
                        f'<p style="font-size:0.75rem;margin:0;padding-top:6px;">'
                        f'<b>{strat_key.upper()}</b> — {DESCS.get(strat_key,"")}</p>',
                        unsafe_allow_html=True)
                with sc3:
                    pct = st.number_input(
                        "Allocation %", 0, 100, cur_pct if is_en else 0,
                        disabled=not is_en, label_visibility="collapsed",
                        key=f"pct_{strat_key}")
                if is_en:
                    enabled_strats.append(strat_key)
                new_alloc[strat_key] = {"enabled": is_en, "alloc_pct": pct}

            total_alloc = sum(v["alloc_pct"] for v in new_alloc.values())
            alloc_colour = "normal" if total_alloc <= 100 else "inverse"
            st.metric("Total allocated", f"{total_alloc} %",
                      delta=f"{100-total_alloc} % idle cash" if total_alloc <= 100
                            else f"⚠ Over-allocated by {total_alloc-100} %",
                      delta_color=alloc_colour)

            st.markdown("---")

            # ── Strategy Parameters ───────────────────────────────────────────
            if enabled_strats:
                for s_key in enabled_strats:
                    with st.expander(f"{s_key.upper()} Parameters", expanded=True):
                        if s_key == "rsi":
                            c1,c2,c3 = st.columns(3)
                            with c1: p  = st.number_input("Period",     2,  50, int(cfg.get("rsi_period",14)),    key="rsi_p")
                            with c2: ov = st.number_input("Oversold",  10., 50., float(cfg.get("rsi_oversold",30)),  step=1., key="rsi_ov")
                            with c3: ob = st.number_input("Overbought",50., 90., float(cfg.get("rsi_overbought",70)),step=1., key="rsi_ob")
                        elif s_key == "macd":
                            c1,c2,c3 = st.columns(3)
                            with c1: mf  = st.number_input("Fast",  2,  50, int(cfg.get("macd_fast",12)),   key="macd_f")
                            with c2: ms  = st.number_input("Slow",  5, 100, int(cfg.get("macd_slow",26)),   key="macd_s")
                            with c3: msg = st.number_input("Signal",2,  50, int(cfg.get("macd_sig",9)),     key="macd_g")
                        elif s_key == "bollinger":
                            c1,c2 = st.columns(2)
                            with c1: bw = st.number_input("Window",5,100,int(cfg.get("bb_window",20)), key="bb_w")
                            with c2: bs = st.number_input("Std Dev",.5,5.0,float(cfg.get("bb_std",2.0)),step=.5,key="bb_s")
                        elif s_key == "ema_crossover":
                            c1,c2 = st.columns(2)
                            with c1: ef = st.number_input("Fast EMA",2, 50, int(cfg.get("ema_fast",9)), key="ema_f")
                            with c2: es = st.number_input("Slow EMA",5,200, int(cfg.get("ema_slow",21)),key="ema_s")
            else:
                st.caption("Enable at least one strategy above to configure its parameters.")

            st.markdown("---")

            # ── Risk Limits ───────────────────────────────────────────────────
            st.markdown("**Risk Limits** *(applied globally across all strategies)*")
            rl1, rl2, rl3, rl4 = st.columns(4)
            with rl1: pct_r   = st.number_input("Position size %",  .5, 25., float(cfg.get("position_pct",5.)),        step=.5)
            with rl2: dloss_r = st.number_input("Daily loss limit %",.5, 20., float(cfg.get("daily_loss_limit_pct",2.)),step=.5)
            with rl3: mpos_r  = st.number_input("Max positions",     1,  20,  int(cfg.get("max_positions",4)))
            with rl4: mdd_r   = st.number_input("Max drawdown %",   1., 50., float(cfg.get("max_drawdown_pct",10.)),   step=1.)

            if st.button("Save Configuration", type="primary", use_container_width=True):
                # Strategy allocation
                db.set_config("strategy_allocation", json.dumps(new_alloc))
                # Set primary active strategy (first enabled, for bot.py single-strategy mode)
                if enabled_strats:
                    db.set_config("active_strategy", enabled_strats[0])
                # Strategy params
                if "rsi" in enabled_strats:
                    db.set_config("rsi_period",str(p)); db.set_config("rsi_oversold",str(ov)); db.set_config("rsi_overbought",str(ob))
                if "macd" in enabled_strats:
                    db.set_config("macd_fast",str(mf)); db.set_config("macd_slow",str(ms)); db.set_config("macd_signal",str(msg))
                if "bollinger" in enabled_strats:
                    db.set_config("bb_window",str(bw)); db.set_config("bb_std",str(bs))
                if "ema_crossover" in enabled_strats:
                    db.set_config("ema_fast",str(ef)); db.set_config("ema_slow",str(es))
                # Risk limits
                db.set_config("position_pct",str(pct_r))
                db.set_config("max_positions",str(mpos_r))
                db.set_config("daily_loss_limit_pct",str(dloss_r))
                db.set_config("max_drawdown_pct",str(mdd_r))
                st.cache_data.clear()
                st.success("Configuration saved.")
                st.rerun()

# ── Demo badge ────────────────────────────────────────────────────────────────

if DEMO:
    st.markdown(
        '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
        'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
        'border:1px solid #2a3a50;border-radius:4px;">DEMO MODE</div>',
        unsafe_allow_html=True)
