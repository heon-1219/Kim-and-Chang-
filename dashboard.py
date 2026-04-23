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

import yfinance as yf

import broker
import db
import notifications
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
        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
        if st.button("👁  View as Guest", use_container_width=True, key="guest_btn"):
            st.session_state.update({"authenticated": True, "demo": False,
                                     "guest": True, "username": "guest"})
            st.rerun()
    return False

if not _check_login():
    st.stop()

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""<style>
/* ── Hide Streamlit chrome ── */
header[data-testid="stHeader"] { display:none !important; }
[data-testid="stToolbar"]       { display:none !important; }
[data-testid="stSidebarCollapsedControl"] { display:none; }

/* ── Layout (tight) ── */
.block-container { max-width:100% !important; padding:0.1rem 0.5rem 0.25rem !important; }
hr, [data-testid="stDivider"] { border-color:#1e3a5f !important; margin:0.15rem 0 !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:6px !important; }

/* Bordered container inner padding (default ~1rem → 0.45rem) */
[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalBlock"] {
    gap: 0.35rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"] { padding: 0 !important; }
div[data-testid="stVerticalBlock"] > div.element-container { margin-bottom: 0 !important; }

/* Column gaps and vertical block gaps — tighten */
div[data-testid="stHorizontalBlock"] { gap: 0.4rem !important; }
div[data-testid="stVerticalBlock"]   { gap: 0.25rem !important; }

/* Main markdown blocks: trim paragraph spacing */
[data-testid="stMarkdownContainer"] p { margin-bottom: 0.15rem !important; }

/* Expander spacing */
[data-testid="stExpander"] { margin: 0.15rem 0 !important; }
[data-testid="stExpander"] details > div { padding-top: 0.3rem !important; }

/* Inputs: reduce label/top padding */
[data-testid="stWidgetLabel"] { margin-bottom: 0.12rem !important; font-size: 0.7rem !important; }
[data-baseweb="input"] input, [data-baseweb="select"] { min-height: 30px !important; }
[data-testid="stNumberInput"] button { padding: 2px 6px !important; }

/* Buttons: slimmer */
.stButton button { padding: 0.25rem 0.55rem !important; min-height: 30px !important; }

/* Tabs: tighter */
[data-baseweb="tab-list"] { gap: 0.25rem !important; }
[data-baseweb="tab"] { padding: 0.25rem 0.65rem !important; }

/* Metric sizing (–30%) */
[data-testid="stMetricLabel"] > div { text-transform:uppercase; font-size:0.55rem !important; letter-spacing:0.07em; }
[data-testid="stMetricValue"]       { font-size:0.95rem !important; }
[data-testid="stMetricDelta"]       { font-size:0.58rem !important; }
[data-testid="stMetric"]            { padding: 0.15rem 0.4rem !important; }

/* Dataframes: slimmer header */
[data-testid="stDataFrame"] { padding: 0 !important; }

/* Plotly: kill default top margin */
.js-plotly-plot { margin-top: 0 !important; }

/* ── Mobile nav (hidden on desktop) ── */
.kc-nav { display:none; }
@media (max-width:768px) {
  .kc-nav {
    display:flex; overflow-x:auto; gap:5px; padding:4px 2px 5px;
    background:#0d1526; border:1px solid #1e3a5f; border-radius:6px;
    margin-bottom:4px; -webkit-overflow-scrolling:touch; scrollbar-width:none;
  }
  .kc-nav::-webkit-scrollbar { display:none; }
  .kc-nav a {
    color:#6b8bb0; text-decoration:none; font-size:0.68rem;
    padding:3px 10px; border-radius:4px; border:1px solid #1e3a5f;
    flex-shrink:0; white-space:nowrap;
  }
  .kc-nav a:active { color:#00d4aa; border-color:#00d4aa; }
  .block-container { padding-bottom:8px !important; }
}
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
    "momentum":     "#00c896",
    "short_ma":     "#ee5a6f",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _panel_header(title: str, help_md: str = "", panel_key: str = "",
                  page_link: str = "") -> bool:
    """Section title with optional ℹ popover and ⤢ expand/navigate toggle."""
    _t = (f'<p style="font-size:0.7rem;font-weight:600;letter-spacing:0.1em;'
          f'color:#00d4aa;text-transform:uppercase;margin:0 0 4px;">{title}</p>')
    state_key = f"_fsstate_{panel_key}"
    expanded = st.session_state.get(state_key, False) if panel_key else False

    def _expand_btn():
        if page_link:
            if st.button("⤢", key=f"fs_{panel_key}", use_container_width=True,
                         help="Open full analytics page"):
                st.switch_page(page_link)
        else:
            if st.button("⤡" if expanded else "⤢", key=f"fs_{panel_key}",
                         use_container_width=True,
                         help="Collapse" if expanded else "Expand"):
                st.session_state[state_key] = not expanded
                st.rerun()

    if help_md and panel_key:
        c1, c2, c3 = st.columns([10, 1, 1])
        with c1: st.markdown(_t, unsafe_allow_html=True)
        with c2:
            with st.popover("ℹ"): st.markdown(help_md)
        with c3:
            _expand_btn()
    elif help_md:
        c1, c2 = st.columns([11, 1])
        with c1: st.markdown(_t, unsafe_allow_html=True)
        with c2:
            with st.popover("ℹ"): st.markdown(help_md)
    elif panel_key:
        c1, c2 = st.columns([11, 1])
        with c1: st.markdown(_t, unsafe_allow_html=True)
        with c2:
            _expand_btn()
    else:
        st.markdown(_t, unsafe_allow_html=True)
    return expanded

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

@st.cache_data(ttl=60)
def _portfolio_history(period: str = "1D", timeframe: str = "1D") -> pd.DataFrame | None:
    """
    Fetch portfolio equity history. Alpaca rejects some period/timeframe pairs
    silently (empty timestamps) — e.g. intraday bars with long periods on
    accounts without enough history. When the primary combo returns empty,
    progressively fall back to safer combos so the chart always shows data.
    """
    # Each entry is (period, timeframe). First = requested; rest = fallbacks.
    attempts: list[tuple[str, str]] = [(period, timeframe)]
    # Intraday bars: fall back to a shorter period, then to daily.
    if timeframe in ("1Min", "5Min", "15Min"):
        attempts += [("1D", timeframe), ("1M", "1D"), ("1A", "1D")]
    elif timeframe == "1H":
        attempts += [("1W", "1H"), ("1M", "1D"), ("1A", "1D")]
    else:  # "1D" or anything else
        attempts += [("1A", "1D"), ("1M", "1D"), ("1W", "1D")]

    tried: set[tuple[str, str]] = set()
    for p, tf in attempts:
        if (p, tf) in tried:
            continue
        tried.add((p, tf))
        try:
            ph = broker.get_portfolio_history(period=p, timeframe=tf)
            if not ph.timestamp:
                continue
            df = pd.DataFrame({"date": pd.to_datetime(ph.timestamp, unit="s"),
                               "equity": ph.equity}).dropna()
            if not df.empty:
                return df
        except Exception:
            continue
    return None

@st.cache_data(ttl=30)
def _stock_info(symbol: str, period: str = "1d", interval: str = "15m",
                tail: int = 0) -> dict | None:
    """Current price + price history from yfinance. Returns None on bad ticker."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval, auto_adjust=True)
        if hist.empty:
            return None
        hist.index = pd.to_datetime([d.replace(tzinfo=None) for d in hist.index])
        if tail > 0:
            hist = hist.tail(tail)
        return {"price": float(hist["Close"].iloc[-1]), "hist": hist}
    except Exception:
        return None

_MT_PERIOD_OPTS: dict[str, tuple] = {
    "1H":  ("1d",  "5m",  12),
    "4H":  ("1d",  "5m",  48),
    "1D":  ("1d",  "15m", 0),
    "5D":  ("5d",  "30m", 0),
    "1M":  ("1mo", "1d",  0),
    "3M":  ("3mo", "1d",  0),
}

def _stock_mini_chart(hist: pd.DataFrame, height: int = 85) -> go.Figure:
    """Compact sparkline chart — no axes, used in the manual trade panel."""
    closes = hist["Close"]
    up     = float(closes.iloc[-1]) >= float(closes.iloc[0])
    clr    = "#00c896" if up else "#ff4b4b"
    fill   = "rgba(0,200,150,0.07)" if up else "rgba(255,75,75,0.07)"
    fig    = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist.index, y=closes, mode="lines", fill="tozeroy",
        fillcolor=fill, line=dict(color=clr, width=1.5), showlegend=False,
        hovertemplate="$%{y:.2f}<extra></extra>"))
    fig.update_layout(
        paper_bgcolor="#0a0e1a", plot_bgcolor="#111827",
        margin=dict(l=0, r=0, t=2, b=0), height=height,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False, hovermode="x unified")
    return fig

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
        # Bars for magnitude + markers so single trades are always visible
        # even when quantities are tiny.
        for side, color, name in [("buy","#00c896","Buy"),("sell","#ff4b4b","Sell")]:
            sd = df[df["side"] == side].copy()
            if sd.empty:
                continue
            cd = sd[["symbol","actual_price","strategy","timestamp"]].values
            fig.add_trace(go.Bar(
                x=sd["ts"], y=sd["quantity"], name=name,
                marker_color=color, marker_opacity=0.85,
                marker_line=dict(color=color, width=1),
                customdata=cd,
                hovertemplate=(
                    f"<b>%{{customdata[0]}}</b> — {name}<br>"
                    "Qty: <b>%{y:.0f}</b><br>"
                    "Price: $%{customdata[1]:.2f}<br>"
                    "Strategy: %{customdata[2]}<br>"
                    "%{customdata[3]}<extra></extra>")))
            # Marker dots on top of each bar so every trade is legible
            fig.add_trace(go.Scatter(
                x=sd["ts"], y=sd["quantity"], mode="markers",
                name=f"{name} ·", showlegend=False,
                marker=dict(size=7, color=color,
                            line=dict(color="#0a0e1a", width=1)),
                customdata=cd,
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
    trades_cfg = {**chart_cfg,
                  "legend": dict(orientation="h", yanchor="bottom", y=1.0,
                                 xanchor="right", x=1.0,
                                 bgcolor="rgba(0,0,0,0)", font=dict(size=10))}
    fig.update_layout(**trades_cfg, height=height, barmode="group",
                      bargap=0.15, bargroupgap=0.05)
    fig.update_yaxes(title_text="Quantity", rangemode="tozero")
    return fig

# ── Demo data ─────────────────────────────────────────────────────────────────

DEMO  = st.session_state.get("demo",  False)
GUEST = st.session_state.get("guest", False)

_DEMO_STRAT_POS: dict[str, list[dict]] = {
    "rsi":          [{"Symbol":"AAPL","Qty":10,"Price":178.91,"Value":1789.10},
                     {"Symbol":"GOOGL","Qty":8,"Price":169.55,"Value":1356.40}],
    "macd":         [{"Symbol":"MSFT","Qty":5,"Price":421.33,"Value":2106.65}],
    "bollinger":    [],
    "ema_crossover":[],
    "manual":       [{"Symbol":"TSLA","Qty":2,"Price":242.10,"Value":484.20}],
}

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


def _send_bt_to_telegram(bt_result: dict, strategy: str, symbols: list[str],
                         interval: str, start, end, inline: bool = False) -> None:
    """
    Ship the current backtest result to Telegram with a strategy-vs-hold verdict.
    `inline=True` surfaces success/failure toast inside the backtest panel.
    """
    metrics = bt_result.get("metrics", {})
    hold_df = bt_result.get("buy_and_hold_curve")
    hold_ret: float | None = None
    try:
        if hold_df is not None and not hold_df.empty:
            start_eq = float(hold_df["equity"].iloc[0])
            end_eq   = float(hold_df["equity"].iloc[-1])
            if start_eq > 0:
                hold_ret = (end_eq - start_eq) / start_eq * 100
    except Exception:
        hold_ret = None

    ok = notifications.send_backtest_result(
        strategy=strategy, symbols=symbols, interval=interval,
        start=str(start), end=str(end),
        metrics=metrics, buy_and_hold_return_pct=hold_ret,
    )
    if inline:
        if ok:
            st.toast("📲 Backtest summary sent to Telegram", icon="✅")
        else:
            st.toast("Telegram not configured or send failed — check .env", icon="⚠️")


_BT_HELP = """
**How to use:**
1. Enter one or more symbols (e.g. `AAPL` or `AAPL, MSFT, GOOGL`), choose a strategy,
   set a date range and starting capital. For multi-symbol runs the capital is split
   evenly and the strategy runs independently per symbol.
2. Pick a **Bar interval** — daily for swing testing, or intraday (1m–1h) for
   high-frequency testing. Intraday data has yfinance window caps:
   · **1m** → last 7 days · **5/15/30m** → last 60 days · **1h** → last 730 days.
3. Click **Run Backtest**. Results appear below. Data sourced from Yahoo Finance (free).
4. A dashed grey **Buy & Hold** line shows what holding the same basket passively would have returned.
5. Click **Add to comparison** to store a result, then run another backtest to compare curves.
6. Click **Clear** to reset stored comparisons.
7. Click the **⤢** top-right to enter fullscreen for a much larger chart; **⤡** to collapse.
"""

_BT_INTERVALS: dict[str, str] = {
    "1 Day (swing)":  "1d",
    "1 Hour (HFT)":   "1h",
    "30 Min (HFT)":   "30m",
    "15 Min (HFT)":   "15m",
    "5 Min (HFT)":    "5m",
    "1 Min (HFT)":    "1m",
}

_BT_INTERVAL_MAX_DAYS: dict[str, int | None] = {
    "1d": None, "1h": 729, "30m": 59, "15m": 59, "5m": 59, "1m": 7,
}


def _render_backtest_panel(chart_height: int) -> None:
    """Render the full Backtest panel contents. The surrounding bordered
    container and the _panel_header should already be set by the caller."""
    if DEMO:
        st.info("Demo mode — backtesting requires live API access.")
        return
    if GUEST:
        st.info("👁 View-only mode — sign in to run backtests.")
        return

    b1, b2 = st.columns([3, 2])
    with b1:
        sym_bt_raw = st.text_input("Symbols (comma-separated)", "AAPL",
                                   placeholder="AAPL, MSFT, GOOGL")
        sym_bt_list = [s.strip().upper() for s in sym_bt_raw.split(",") if s.strip()]
    with b2:
        strat_bt = st.selectbox("Strategy", list(STRATEGIES.keys()))

    b3, b4, b5 = st.columns([1, 1, 1.2])
    with b3: bt_interval_lbl = st.selectbox(
        "Bar interval", list(_BT_INTERVALS.keys()), index=0,
        help="Daily for swing, 1m–1h for high-frequency. Intraday has history caps.")
    bt_interval = _BT_INTERVALS[bt_interval_lbl]
    # Default end date is today for all intervals; default start shortens for HFT
    # so we land inside the yfinance window.
    _max_d = _BT_INTERVAL_MAX_DAYS.get(bt_interval)
    _def_start = (date.today() - timedelta(days=min(_max_d, 30)) if _max_d
                  else date(2024, 1, 1))
    with b4: s_bt = st.date_input("Start", _def_start, key=f"bt_start_{bt_interval}")
    with b5: e_bt = st.date_input("End",   date.today(), key=f"bt_end_{bt_interval}")

    cap_bt = st.number_input("Starting capital ($)", value=100_000, step=10_000)

    # Per-strategy parameter overrides for this backtest run
    with st.expander("⚙ Strategy Parameters", expanded=False):
        if strat_bt == "rsi":
            pc1,pc2,pc3 = st.columns(3)
            with pc1: bt_rsi_p  = st.number_input("RSI Period",  2,   50, int(cfg.get("rsi_period",    "14")),          key="bt_rsi_p")
            with pc2: bt_rsi_ov = st.number_input("Oversold",   10.,  50., float(cfg.get("rsi_oversold", "30")), step=1., key="bt_rsi_ov")
            with pc3: bt_rsi_ob = st.number_input("Overbought", 50.,  90., float(cfg.get("rsi_overbought","70")), step=1., key="bt_rsi_ob")
            bt_strat_cfg = {"rsi_period": bt_rsi_p, "rsi_oversold": bt_rsi_ov, "rsi_overbought": bt_rsi_ob}
        elif strat_bt == "macd":
            pc1,pc2,pc3 = st.columns(3)
            with pc1: bt_mf  = st.number_input("Fast",   2,  50, int(cfg.get("macd_fast",   "12")), key="bt_mf")
            with pc2: bt_ms  = st.number_input("Slow",   5, 100, int(cfg.get("macd_slow",   "26")), key="bt_ms")
            with pc3: bt_msg = st.number_input("Signal", 2,  50, int(cfg.get("macd_signal", "9")),  key="bt_msg")
            bt_strat_cfg = {"macd_fast": bt_mf, "macd_slow": bt_ms, "macd_signal": bt_msg}
        elif strat_bt == "bollinger":
            pc1,pc2 = st.columns(2)
            with pc1: bt_bw = st.number_input("Window",  5,  100, int(cfg.get("bb_window","20")),           key="bt_bw")
            with pc2: bt_bs = st.number_input("Std Dev", .5, 5.0, float(cfg.get("bb_std",  "2.0")), step=.5, key="bt_bs")
            bt_strat_cfg = {"bb_window": bt_bw, "bb_std": bt_bs}
        elif strat_bt == "ema_crossover":
            pc1,pc2 = st.columns(2)
            with pc1: bt_ef = st.number_input("Fast EMA", 2,  50, int(cfg.get("ema_fast","9")),  key="bt_ef")
            with pc2: bt_es = st.number_input("Slow EMA", 5, 200, int(cfg.get("ema_slow","21")), key="bt_es")
            bt_strat_cfg = {"ema_fast": bt_ef, "ema_slow": bt_es}
        elif strat_bt == "momentum":
            pc1,pc2 = st.columns(2)
            with pc1: bt_mw  = st.number_input("Window",   1, 20, int(cfg.get("momentum_window","3")),       key="bt_mw")
            with pc2: bt_mth = st.number_input("Threshold %", 0.05, 5.0, float(cfg.get("momentum_threshold","0.3")), step=0.05, key="bt_mth")
            bt_strat_cfg = {"momentum_window": bt_mw, "momentum_threshold": bt_mth}
        elif strat_bt == "short_ma":
            pc1,pc2 = st.columns(2)
            with pc1: bt_sf = st.number_input("Fast window",  2,  30, int(cfg.get("short_ma_fast","5")),  key="bt_sf")
            with pc2: bt_ss = st.number_input("Slow window",  5,  60, int(cfg.get("short_ma_slow","15")), key="bt_ss")
            bt_strat_cfg = {"short_ma_fast": bt_sf, "short_ma_slow": bt_ss}
        else:
            bt_strat_cfg = {}
    bt_settings = {**cfg, **bt_strat_cfg}

    run_c, add_c, tg_c, clr_c = st.columns([2, 1, 1, 1])
    with run_c:
        run_bt = st.button("▶  Run Backtest", type="primary", use_container_width=True)
    with add_c:
        add_bt = st.button("＋ Compare", use_container_width=True,
                           disabled="bt" not in st.session_state)
    with tg_c:
        send_tg = st.button("📲 Telegram", use_container_width=True,
                            disabled="bt" not in st.session_state,
                            help="Send the latest backtest summary to Telegram")
    with clr_c:
        if st.button("✕ Clear", use_container_width=True):
            st.session_state.pop("bt", None)
            st.session_state.pop("bt_compare", None)
            st.rerun()

    auto_tg = st.checkbox(
        "Auto-send backtest summary to Telegram on every run",
        value=st.session_state.get("bt_auto_tg", False), key="bt_auto_tg")

    if run_bt:
        if s_bt >= e_bt:
            st.error("Start must be before end.")
        elif not sym_bt_list:
            st.error("Enter at least one symbol.")
        else:
            # Defensive coercion: make sure every downstream consumer sees
            # a flat list of uppercase strings and a str strategy name.
            syms_clean = [str(s).strip().upper() for s in sym_bt_list
                          if str(s).strip()]
            strat_name = str(strat_bt)
            with st.spinner(f"Running {strat_name.upper()} on {', '.join(syms_clean)}…"):
                try:
                    st.session_state["bt"] = run_backtest(
                        syms_clean, strat_name, s_bt, e_bt,
                        float(cap_bt), bt_settings, interval=bt_interval)
                    label_syms = (syms_clean[0] if len(syms_clean) == 1
                                  else f"{len(syms_clean)} syms")
                    st.session_state["bt_lbl"] = (
                        f"{label_syms}·{strat_name.upper()}·{bt_interval}·{s_bt}→{e_bt}")
                    if st.session_state["bt"].get("errors"):
                        for err in st.session_state["bt"]["errors"]:
                            st.warning(err)
                    if auto_tg:
                        _send_bt_to_telegram(st.session_state["bt"],
                                             strat_name, syms_clean, bt_interval,
                                             s_bt, e_bt, inline=True)
                except Exception as ex:
                    import traceback
                    st.error(f"{type(ex).__name__}: {ex}")
                    with st.expander("Traceback", expanded=True):
                        st.code(traceback.format_exc(), language="python")

    if send_tg and "bt" in st.session_state:
        _send_bt_to_telegram(st.session_state["bt"],
                             str(strat_bt),
                             [str(s).strip().upper() for s in sym_bt_list],
                             bt_interval, s_bt, e_bt, inline=True)

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
                line_c = colors_bt[i % len(colors_bt)]
                fig_bt.add_trace(go.Scatter(
                    x=eq_c["date"], y=eq_c["equity"],
                    mode="lines", name=lbl,
                    line=dict(color=line_c, width=1.5),
                    hovertemplate="$%{y:,.0f}<extra>" + lbl + "</extra>"))

        # Buy-and-hold baseline for the latest run (summed across symbols)
        hold_c = st.session_state["bt"].get("buy_and_hold_curve", pd.DataFrame())
        if hold_c is not None and not hold_c.empty:
            fig_bt.add_trace(go.Scatter(
                x=hold_c["date"], y=hold_c["equity"],
                mode="lines", name="Buy & Hold",
                line=dict(color="#8899aa", width=1.3, dash="dash"),
                hovertemplate="$%{y:,.0f}<extra>Buy & Hold</extra>"))

        if fig_bt.data:
            fig_bt.add_hline(
                y=st.session_state["bt"]["metrics"]["starting_capital"],
                line=dict(color="#444", width=1, dash="dot"))
            fig_bt.update_layout(**_CHART, height=chart_height)
            fig_bt.update_yaxes(tickprefix="$", tickformat=",.0f")
            st.plotly_chart(fig_bt, use_container_width=True, config=_NO_TB)


# ── Load runtime data ─────────────────────────────────────────────────────────

hb      = None if DEMO else db.get_heartbeat()
cfg     = {"trading_enabled":"true","active_strategy":"rsi"} if DEMO else db.get_all_config()
now_utc = datetime.utcnow()
uname   = st.session_state.get("username", "—")
trades  = _demo_trades() if DEMO else db.get_recent_trades(limit=50)
logs    = _demo_logs()   if DEMO else db.get_recent_logs(limit=500)

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
api_n = 0 if DEMO else db.count_recent_api_calls(60)

# Parse strategy allocations (JSON stored in db)
_alloc_raw  = cfg.get("strategy_allocation", "{}")
try:
    alloc_cfg: dict = json.loads(_alloc_raw)
except (json.JSONDecodeError, TypeError):
    alloc_cfg = {}

n_active_strats = sum(1 for v in alloc_cfg.values() if v.get("enabled"))

# Backtest fullscreen collapses every other panel so the chart can take the page
BT_FULL = bool(st.session_state.get("_fsstate_backtest", False))

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
        f'<span style="font-size:0.72rem;color:#6b8bb0;">'
        f'<b style="color:#e2e8f0;">{n_active_strats}</b> '
        f'{"strategy" if n_active_strats == 1 else "strategies"} active</span>'
        f'<span style="font-size:0.72rem;color:#6b8bb0;">API {api_n}/200 &nbsp; '
        f'{now_utc.strftime("%H:%M UTC")}</span>'
        f'</div>',
        unsafe_allow_html=True)

with right_hdr:
    u_col, r_col, l_col = st.columns([3, 1, 1])
    with u_col:
        if GUEST:
            st.markdown(
                '<div style="display:flex;align-items:center;height:100%;">'
                '<span style="font-size:0.72rem;color:#6b8bb0;">Signed in as&nbsp;'
                '<b style="color:#ffa500;">GUEST</b>'
                '<span style="color:#4a6a90;font-size:0.62rem;"> (view only)</span>'
                '</span></div>',
                unsafe_allow_html=True)
        else:
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

# ── Backtest fullscreen mode: render only the backtest and halt the script ──

if BT_FULL:
    st.markdown('<div id="backtest"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        bt_expanded = _panel_header("Backtest Engine", panel_key="backtest", help_md=_BT_HELP)
        _render_backtest_panel(chart_height=640)
    # Keep the demo/guest badges visible in fullscreen too
    if DEMO:
        st.markdown(
            '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
            'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
            'border:1px solid #2a3a50;border-radius:4px;">DEMO MODE</div>',
            unsafe_allow_html=True)
    if GUEST:
        st.markdown(
            '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
            'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
            'border:1px solid #ffa50055;border-radius:4px;">👁 GUEST MODE</div>',
            unsafe_allow_html=True)
    st.stop()

# ── ACCOUNT METRICS ───────────────────────────────────────────────────────────

if not BT_FULL:
    st.markdown("""<div class="kc-nav">
  <a href="#equity">📈 Equity</a>
  <a href="#trades">📊 Trades</a>
  <a href="#positions">💼 Positions</a>
  <a href="#server">🖥 Server</a>
  <a href="#logs">📋 Logs</a>
  <a href="#backtest">🔬 Backtest</a>
  <a href="#manual">✋ Manual</a>
  <a href="#config">⚙️ Config</a>
</div>""", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Portfolio Balance",  f"${eq:,.2f}")
    m2.metric("Cash Available",     f"${cash:,.2f}")
    m3.metric("Buying Power",       f"${bp:,.2f}")
    m4.metric("Today P&L",         f"${pnl:+,.2f}", delta=f"{pp:+.2f}%")

# ── MAIN SECTION: charts (left) | data panels (right) ─────────────────────────

main_left, main_right = st.columns([3, 2], gap="small")

with main_left:
    # ── Portfolio Equity ──────────────────────────────────────────────────────
    st.markdown('<div id="equity"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        eq_expanded = _panel_header("Portfolio Equity", panel_key="equity", help_md="""
**How to use:**
- Each dropdown option sets the **bar size** — "1 Min" means each point on the chart
  represents one minute, "1 Day" means each point is one trading day, and so on.
  The chart always shows a sensible span for that bar size (e.g. 1-min bars = today,
  1-day bars = last year).
- Select one or more strategies below to overlay trade markers on the chart.
- This chart shows *total* portfolio equity sourced from Alpaca.
        """)
        # bar_size → (alpaca_period, alpaca_timeframe, resample_rule).
        # Each bar on the chart represents `bar_size`. `resample_rule` (pandas)
        # is applied when Alpaca doesn't natively offer that bar size.
        PERIOD_OPTS: dict[str, tuple] = {
            "1 Min":    ("1D", "1Min",  None),      # today, 1-min bars
            "5 Min":    ("1D", "5Min",  None),      # today, 5-min bars
            "15 Min":   ("5D", "15Min", None),      # 5 days, 15-min bars
            "30 Min":   ("1W", "15Min", "30min"),   # 1 week, 15-min resampled to 30-min
            "1 Hour":   ("1W", "1H",    None),      # 1 week, hourly bars
            "4 Hour":   ("1M", "1H",    "4h"),      # 1 month, hourly resampled to 4h
            "1 Day":    ("1M", "1D",    None),      # 1 month, daily bars
            "1 Week":   ("1A", "1D",    "W-FRI"),   # 1 year, daily resampled to weekly
            "1 Month":  ("5A", "1D",    "ME"),      # 5 years, daily resampled to monthly
            "1 Quarter":("5A", "1D",    "QE"),      # 5 years, daily resampled to quarterly
            "1 Year":   ("5A", "1D",    "YE"),      # 5 years, daily resampled to yearly
        }
        per_col, strat_col = st.columns([1, 2])
        with per_col:
            period_key = st.selectbox("Period", list(PERIOD_OPTS), index=6,
                                      label_visibility="collapsed")
        with strat_col:
            overlay_strats = st.multiselect(
                "Show strategy trades", list(STRATEGIES.keys()),
                default=[], placeholder="Overlay strategy trades…",
                label_visibility="collapsed")
        api_period, api_tf, resample_rule = PERIOD_OPTS[period_key]
        if DEMO:
            ph = _demo_ph()
        else:
            ph = _portfolio_history(api_period, api_tf)
        # Resample when the requested bar size isn't a native Alpaca timeframe.
        if ph is not None and resample_rule:
            rs = (ph.set_index("date")["equity"]
                    .resample(resample_rule).last().dropna().reset_index())
            if not rs.empty:
                ph = rs
        if ph is not None:
            st.plotly_chart(_equity_fig(ph, trades, overlay_strats,
                                        height=560 if eq_expanded else 320),
                            use_container_width=True, config=_NO_TB)
        else:
            st.info("No portfolio history available yet.")

    # ── Trade Activity ────────────────────────────────────────────────────────
    st.markdown('<div id="trades"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        all_strats = sorted({t.get("strategy","?") for t in trades} if trades else [])
        buys  = sum(1 for t in trades if t.get("side") == "buy")  if trades else 0
        sells = sum(1 for t in trades if t.get("side") == "sell") if trades else 0
        tr_expanded = _panel_header(f"Trade Activity — {buys} buy · {sells} sell",
                                    panel_key="trades", help_md="""
**How to use:**
- Each bar represents one paper trade (green = buy, red = sell).
- Hover a bar to see full details: symbol, price, quantity, strategy, timestamp.
- Use the filter below to view only trades from specific strategies.
        """)
        filt = st.multiselect("Filter by strategy", all_strats, default=all_strats,
                              label_visibility="collapsed",
                              placeholder="All strategies shown")
        st.plotly_chart(_trades_fig(trades, filt or None,
                                    height=440 if tr_expanded else 280),
                        use_container_width=True, config=_NO_TB)

with main_right:
    # ── Open Positions ────────────────────────────────────────────────────────
    st.markdown('<div id="positions"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        _panel_header("Open Positions", panel_key="positions",
                      page_link="pages/positions.py", help_md="""
**How to use:**
- Tabs show positions owned by each strategy (tracked via trade log).
- **All** tab shows every open Alpaca position with full P&L.
- Click ⤢ to open the full analytics page (charts, P&L breakdown, trade history).
        """)
        # Build Alpaca position price map
        try:
            _raw_pos = _demo_positions() if DEMO else broker.get_all_positions()
            pos_map  = {p.symbol: p for p in _raw_pos}
        except Exception:
            pos_map = {}
        all_syms = (["AAPL","MSFT","GOOGL","TSLA"] if DEMO
                    else db.get_all_traded_symbols())
        tab_h = 110

        STRAT_TABS = ["RSI","MACD","Bollinger","EMA","Momentum","Short MA","Manual","All"]
        STRAT_KEYS = ["rsi","macd","bollinger","ema_crossover","momentum","short_ma","manual", None]
        tabs = st.tabs(STRAT_TABS)

        for tab, strat_key in zip(tabs, STRAT_KEYS):
            with tab:
                if strat_key is None:
                    # All — raw Alpaca positions with P&L
                    if pos_map:
                        all_rows = [{"Symbol":p.symbol,"Qty":float(p.qty),
                                     "Price":float(p.current_price),
                                     "P&L ($)":float(p.unrealized_pl),
                                     "P&L (%)":float(p.unrealized_plpc)*100}
                                    for p in pos_map.values()]
                        df_all = pd.DataFrame(all_rows)
                        st.dataframe(
                            df_all.style
                                .format({"Price":"${:.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"})
                                .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                            use_container_width=True, hide_index=True, height=tab_h)
                    else:
                        st.caption("No open positions.")
                else:
                    # Strategy-specific holdings from trade log
                    if DEMO:
                        rows = _DEMO_STRAT_POS.get(strat_key, [])
                    else:
                        rows = []
                        for sym in all_syms:
                            qty = db.get_strategy_holding(sym, strat_key)
                            if qty > 0:
                                p = pos_map.get(sym)
                                price = float(p.current_price) if p else 0.0
                                rows.append({"Symbol":sym,"Qty":round(qty,4),
                                             "Price":price,"Value":round(qty*price,2)})
                    if rows:
                        df_s = pd.DataFrame(rows)
                        st.dataframe(
                            df_s.style.format({"Qty":"{:.0f}","Price":"${:.2f}","Value":"${:,.0f}"}),
                            use_container_width=True, hide_index=True, height=tab_h)
                    else:
                        st.caption(f"No active {(strat_key or '').upper()} positions.")

    # ── Server + Safety ───────────────────────────────────────────────────────
    st.markdown('<div id="server"></div>', unsafe_allow_html=True)
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
                st.dataframe(sdf[cols], use_container_width=True, hide_index=True, height=70)
            else:
                st.markdown(
                    '<div style="display:flex;align-items:center;gap:6px;'
                    'padding:6px 10px;margin-top:4px;background:rgba(0,200,150,0.08);'
                    'border:1px solid rgba(0,200,150,0.3);border-radius:4px;">'
                    '<span style="color:#00c896;font-size:0.85rem;">✓</span>'
                    '<span style="color:#00c896;font-size:0.7rem;letter-spacing:0.04em;">'
                    'No safety events</span></div>',
                    unsafe_allow_html=True)

    # ── Bot Logs ──────────────────────────────────────────────────────────────
    st.markdown('<div id="logs"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        _panel_header("Logs", panel_key="logs",
                      page_link="pages/log.py", help_md="""
**How to read:**
- **INFO** (grey) — routine status messages, including manual orders and kill-switch toggles.
- **WARN** (amber) — non-critical warnings (e.g. rate limit approaching).
- **ERROR** (red) — failures that need attention.
- Click ⤢ to open the full log page (search, filters, trade summary, signal events).
        """)
        if logs:
            df_l = pd.DataFrame(logs)[["timestamp","level","message"]]
            LS   = {"ERROR":"color:#ff4b4b;font-weight:600",
                    "WARN": "color:#ffa500",
                    "INFO": "color:#6b8bb0"}
            st.dataframe(df_l.style.map(lambda v: LS.get(v,""), subset=["level"]),
                         use_container_width=True, hide_index=True, height=256)
            st.caption(f"{len(df_l):,} most recent entries")
        else:
            st.caption("No log entries yet.")

    # ── Manual Trade (No Strategy) — now lives in the right column under Logs
    st.markdown('<div id="manual"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        _panel_header("Manual Trade — No Strategy", help_md="""
**How to use:**
- Search any symbol (e.g. TSLA) and set the quantity.
- Choose Buy or Sell, then click **Order(…)**.
- This places a paper market order that executes at market price.
- Orders placed here are logged as "manual" and appear in the Manual tab of Open Positions.
- **Paper trading only** — no real money is ever used.
        """)
        if DEMO:
            st.info("Demo mode — manual orders are disabled.")
        elif GUEST:
            st.info("👁 View-only mode — sign in with an account to place orders.")
        else:
            mt1, mt2, mt3 = st.columns([1.5, 0.9, 1.3])
            with mt1:
                mt_sym = st.text_input("Symbol", key="mt_sym", placeholder="e.g. TSLA").upper().strip()
            with mt2:
                mt_qty = st.number_input("Quantity", min_value=1, step=1, key="mt_qty")
            with mt3:
                mt_side = st.radio("Side", ["Buy", "Sell"], horizontal=True, key="mt_side")

            # Live price + period-selectable mini chart when symbol entered
            mt_price: float | None = None
            if mt_sym:
                info_row1, info_row2 = st.columns([2, 1])
                with info_row2:
                    mt_period_key = st.selectbox(
                        "Chart period", list(_MT_PERIOD_OPTS), index=2,
                        label_visibility="collapsed", key="mt_period")
                mt_per, mt_iv, mt_tail = _MT_PERIOD_OPTS[mt_period_key]
                info = _stock_info(mt_sym, mt_per, mt_iv, mt_tail)
                if info:
                    mt_price = info["price"]
                    owned_qty = sum(
                        db.get_strategy_holding(mt_sym, sk)
                        for sk in ["rsi", "macd", "bollinger", "ema_crossover",
                                   "momentum", "short_ma", "manual"]
                    )
                    with info_row1:
                        pi1, pi2 = st.columns(2)
                        pi1.metric("Live Price", f"${mt_price:,.2f}")
                        pi2.metric("You Own",    f"{owned_qty:g}")
                    st.plotly_chart(_stock_mini_chart(info["hist"], height=70),
                                    use_container_width=True, config=_NO_TB)
                else:
                    st.caption(f"No data for **{mt_sym}** — check the ticker symbol.")

            if mt_price is not None:
                btn_label = f"Order (${mt_price * mt_qty:,.2f})"
            else:
                btn_label = "Submit Paper Order"
            submit_mt = st.button(btn_label, type="primary", use_container_width=True)

            if submit_mt:
                if not mt_sym:
                    st.error("Enter a symbol.")
                else:
                    try:
                        req = MarketOrderRequest(
                            symbol=mt_sym,
                            qty=mt_qty,
                            side=OrderSide.BUY if mt_side == "Buy" else OrderSide.SELL,
                            time_in_force=TimeInForce.DAY,
                        )
                        result = broker.submit_order(req)
                        fill_price = mt_price if mt_price else 0.0
                        slippage_bps = int(cfg.get("slippage_bps", "5"))
                        sim_price = broker.apply_slippage(
                            fill_price, mt_side.lower(), slippage_bps)
                        db.log_trade(
                            symbol=mt_sym, side=mt_side.lower(), quantity=mt_qty,
                            actual_price=fill_price, simulated_price=sim_price,
                            order_id=str(result.id), strategy="manual",
                            notes="manual order via dashboard",
                        )
                        db.log("INFO",
                               f"[MANUAL] {mt_side.upper()} {mt_qty} {mt_sym}"
                               + (f" @ ${fill_price:,.2f}" if fill_price else "")
                               + f" (user={uname})")
                        st.success(
                            f"Paper order submitted — {mt_side.upper()} {mt_qty}× {mt_sym}"
                            + (f" @ ${fill_price:,.2f}" if fill_price else "")
                        )
                        _stock_info.clear()
                    except Exception as ex:
                        st.error(str(ex))

# ── BOTTOM SECTION: Backtest | Configuration ──────────────────────────────────

bt_col, cfg_col = st.columns([1, 1], gap="small")

# ── Backtest Engine ───────────────────────────────────────────────────────────
with bt_col:
    st.markdown('<div id="backtest"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        bt_expanded = _panel_header("Backtest Engine", panel_key="backtest", help_md=_BT_HELP)
        _render_backtest_panel(chart_height=280 if bt_expanded else 180)

# ── Configuration ─────────────────────────────────────────────────────────────
if not BT_FULL:
    cfg_col.markdown('<div id="config"></div>', unsafe_allow_html=True)
    with cfg_col.container(border=True):
        _panel_header("Configuration", help_md="""
**How to use:**
- **Trading enabled** — master kill switch. Disable to halt all bot activity immediately.
- **Strategy Allocation** — enable one or more strategies and set a USD amount for each.
  All enabled strategies run in parallel on every bot cycle.
- **Strategy Parameters** — tune each strategy's indicator settings. All four are always
  editable; enabled strategies start expanded.
- **Risk Limits** — global caps applied across all strategies.
- Click **Save Configuration** to persist all changes immediately.
        """)
        if DEMO:
            st.info("Demo mode — configuration is read-only.")
        else:
            if GUEST:
                st.caption("👁 View-only mode — sign in to edit configuration.")
            # Trading kill switch
            en = cfg.get("trading_enabled","true").lower() == "true"
            ne = st.toggle("Trading enabled (master switch)", value=en, disabled=GUEST)
            if ne != en and not GUEST:
                db.set_config("trading_enabled","true" if ne else "false")
                db.log("INFO",
                       f"[DASHBOARD] Kill switch turned {'ON' if ne else 'OFF'} by {uname}")
                st.rerun()

            # ── Strategy Allocation ───────────────────────────────────────────
            st.markdown("**Strategy Allocation**")
            st.caption(
                "Enable strategies and assign a capital amount (USD) to each. "
                "Total must stay within your portfolio balance. Remainder stays as idle cash.")

            DESCS = {
                "rsi":          "mean-reversion (횡보장)",
                "macd":         "trend-following (추세장)",
                "bollinger":    "band breakout (고변동성)",
                "ema_crossover":"golden/death cross",
                "momentum":     "ROC momentum — frequent signals",
                "short_ma":     "fast MA crossover — frequent signals",
            }
            max_eq = max(int(eq), 1)

            enabled_strats: list[str] = []
            new_alloc: dict = {}
            for strat_key in STRATEGIES:
                sc1, sc2, sc3, sc4 = st.columns([0.18, 2.4, 0.15, 1.0])
                raw_v   = alloc_cfg.get(strat_key, {})
                cur_en  = raw_v.get("enabled", False)
                cur_usd = (int(raw_v["alloc_usd"]) if "alloc_usd" in raw_v
                           else int(eq * raw_v.get("alloc_pct", 0) / 100))
                with sc1:
                    is_en = st.checkbox("", value=cur_en, key=f"en_{strat_key}", disabled=GUEST)
                with sc2:
                    st.markdown(
                        f'<p style="font-size:0.68rem;margin:0;padding-top:8px;'
                        f'color:#c8d6e8;white-space:nowrap;overflow:hidden;">'
                        f'<b>{strat_key.upper()}</b>'
                        f'<span style="color:#4a6a90;font-size:0.62rem;">'
                        f' — {DESCS.get(strat_key,"")}</span></p>',
                        unsafe_allow_html=True)
                with sc3:
                    st.markdown(
                        '<p style="font-size:0.78rem;margin:0;padding-top:8px;'
                        'color:#6b8bb0;text-align:right;">$</p>',
                        unsafe_allow_html=True)
                with sc4:
                    usd_val = st.number_input(
                        "", 0, max_eq, cur_usd if is_en else 0,
                        step=500, disabled=not is_en or GUEST,
                        label_visibility="collapsed", key=f"usd_{strat_key}")
                if is_en:
                    enabled_strats.append(strat_key)
                new_alloc[strat_key] = {"enabled": is_en, "alloc_usd": usd_val}

            # Enabled strategies with $0 get auto-split on save so the bot doesn't
            # silently drop them. We detect here purely for the warning.
            zero_enabled = [k for k in enabled_strats if new_alloc[k]["alloc_usd"] == 0]
            if zero_enabled:
                st.warning(
                    f"⚠ {', '.join(k.upper() for k in zero_enabled)} enabled with $0 — "
                    "on save these will be auto-split across the remaining idle cash, "
                    "otherwise the bot would skip them.")

            total_usd   = sum(v["alloc_usd"] for v in new_alloc.values())
            idle_usd    = max(eq - total_usd, 0)
            over_by     = max(total_usd - eq, 0)
            alloc_ok    = total_usd <= eq

            # Compact status row: allocation summary + top-N picker (was two rows)
            sm1, sm2 = st.columns([1.3, 1])
            with sm1:
                st.metric("Total allocated", f"${total_usd:,.0f}",
                          delta=(f"${idle_usd:,.0f} idle cash" if alloc_ok
                                 else f"⚠ Over by ${over_by:,.0f}"),
                          delta_color="normal" if alloc_ok else "inverse")
            with sm2:
                top_n = st.number_input(
                    "Top-N / strategy", min_value=1, max_value=100,
                    value=int(cfg.get("picker_top_n", "10")), step=1, disabled=GUEST,
                    help="Each enabled strategy ranks S&P 500 names and trades "
                         "its top-N per day.")

            # ── Popovers: Strategy Parameters, Risk Limits, Save ──────────────
            pv1, pv2, pv3 = st.columns([1.2, 1.2, 1])
            with pv1:
                with st.popover("⚙ Strategy Parameters",
                                use_container_width=True, disabled=GUEST):
                    st.caption("Tune indicator settings for each strategy. "
                               "Enabled strategies' tabs open first.")
                    tab_order = sorted(STRATEGIES.keys(),
                                       key=lambda k: (k not in enabled_strats, k))
                    TAB_LABELS = {"rsi":"RSI","macd":"MACD","bollinger":"Bollinger",
                                  "ema_crossover":"EMA","momentum":"Momentum",
                                  "short_ma":"Short MA"}
                    param_tabs = st.tabs([TAB_LABELS.get(k, k.upper()) for k in tab_order])
                    param_vals: dict = {}
                    for tab, key in zip(param_tabs, tab_order):
                        with tab:
                            if key == "rsi":
                                c1,c2,c3 = st.columns(3)
                                with c1: param_vals["rsi_period"]     = st.number_input("Period",     2,  50, int(cfg.get("rsi_period",14)),         key="rsi_p",   disabled=GUEST)
                                with c2: param_vals["rsi_oversold"]   = st.number_input("Oversold",  10., 50., float(cfg.get("rsi_oversold",30)),    step=1., key="rsi_ov",  disabled=GUEST)
                                with c3: param_vals["rsi_overbought"] = st.number_input("Overbought",50., 90., float(cfg.get("rsi_overbought",70)),  step=1., key="rsi_ob",  disabled=GUEST)
                            elif key == "macd":
                                c1,c2,c3 = st.columns(3)
                                with c1: param_vals["macd_fast"]   = st.number_input("Fast",  2,  50, int(cfg.get("macd_fast",12)),  key="macd_f", disabled=GUEST)
                                with c2: param_vals["macd_slow"]   = st.number_input("Slow",  5, 100, int(cfg.get("macd_slow",26)),  key="macd_s", disabled=GUEST)
                                with c3: param_vals["macd_signal"] = st.number_input("Signal",2,  50, int(cfg.get("macd_signal",9)), key="macd_g", disabled=GUEST)
                            elif key == "bollinger":
                                c1,c2 = st.columns(2)
                                with c1: param_vals["bb_window"] = st.number_input("Window",5,100, int(cfg.get("bb_window",20)),            key="bb_w", disabled=GUEST)
                                with c2: param_vals["bb_std"]    = st.number_input("Std Dev",.5,5.0, float(cfg.get("bb_std",2.0)), step=.5, key="bb_s", disabled=GUEST)
                            elif key == "ema_crossover":
                                c1,c2 = st.columns(2)
                                with c1: param_vals["ema_fast"] = st.number_input("Fast EMA",2, 50, int(cfg.get("ema_fast",9)),  key="ema_f", disabled=GUEST)
                                with c2: param_vals["ema_slow"] = st.number_input("Slow EMA",5,200, int(cfg.get("ema_slow",21)), key="ema_s", disabled=GUEST)
                            elif key == "momentum":
                                c1,c2 = st.columns(2)
                                with c1: param_vals["momentum_window"]    = st.number_input("Window (bars)", 1, 20, int(cfg.get("momentum_window",3)),          key="mom_w",  disabled=GUEST)
                                with c2: param_vals["momentum_threshold"] = st.number_input("Threshold %", 0.05,5.0, float(cfg.get("momentum_threshold",0.3)), step=0.05, key="mom_th", disabled=GUEST)
                            elif key == "short_ma":
                                c1,c2 = st.columns(2)
                                with c1: param_vals["short_ma_fast"] = st.number_input("Fast window", 2, 30, int(cfg.get("short_ma_fast",5)),   key="sma_f", disabled=GUEST)
                                with c2: param_vals["short_ma_slow"] = st.number_input("Slow window", 5, 60, int(cfg.get("short_ma_slow",15)),  key="sma_s", disabled=GUEST)

            with pv2:
                with st.popover("⚠ Risk Limits",
                                use_container_width=True, disabled=GUEST):
                    st.caption("Global caps applied across all strategies.")
                    rl1, rl2 = st.columns(2)
                    with rl1:
                        pct_r   = st.number_input("Position size %",    .5, 25., float(cfg.get("position_pct",5.)),         step=.5, disabled=GUEST)
                        mpos_r  = st.number_input("Max positions",      1,  20,  int(cfg.get("max_positions",4)),                    disabled=GUEST)
                    with rl2:
                        dloss_r = st.number_input("Daily loss limit %", .5, 20., float(cfg.get("daily_loss_limit_pct",2.)), step=.5, disabled=GUEST)
                        mdd_r   = st.number_input("Max drawdown %",     1., 50., float(cfg.get("max_drawdown_pct",10.)),    step=1., disabled=GUEST)

            # Unpack strategy params so the save handler signature stays identical
            p    = param_vals.get("rsi_period",     int(cfg.get("rsi_period",14)))
            ov   = param_vals.get("rsi_oversold",   float(cfg.get("rsi_oversold",30)))
            ob   = param_vals.get("rsi_overbought", float(cfg.get("rsi_overbought",70)))
            mf   = param_vals.get("macd_fast",      int(cfg.get("macd_fast",12)))
            ms   = param_vals.get("macd_slow",      int(cfg.get("macd_slow",26)))
            msg  = param_vals.get("macd_signal",    int(cfg.get("macd_signal",9)))
            bw   = param_vals.get("bb_window",      int(cfg.get("bb_window",20)))
            bs   = param_vals.get("bb_std",         float(cfg.get("bb_std",2.0)))
            ef   = param_vals.get("ema_fast",       int(cfg.get("ema_fast",9)))
            es   = param_vals.get("ema_slow",       int(cfg.get("ema_slow",21)))
            mw   = param_vals.get("momentum_window",    int(cfg.get("momentum_window",3)))
            mth  = param_vals.get("momentum_threshold", float(cfg.get("momentum_threshold",0.3)))
            smf  = param_vals.get("short_ma_fast",  int(cfg.get("short_ma_fast",5)))
            sms  = param_vals.get("short_ma_slow",  int(cfg.get("short_ma_slow",15)))

            with pv3:
                save_clicked = st.button(
                    "💾 Save", type="primary",
                    use_container_width=True, disabled=GUEST)

            if save_clicked:
                # Auto-split idle cash across enabled strategies that have $0
                final_alloc = {k: dict(v) for k, v in new_alloc.items()}
                zero_enabled_k = [k for k in enabled_strats
                                  if final_alloc[k]["alloc_usd"] == 0]
                if zero_enabled_k:
                    idle_cash = max(int(eq) - sum(v["alloc_usd"] for v in final_alloc.values()), 0)
                    if idle_cash > 0:
                        share = idle_cash // len(zero_enabled_k)
                        for k in zero_enabled_k:
                            final_alloc[k]["alloc_usd"] = int(share)
                # Strategy allocation (USD)
                db.set_config("strategy_allocation", json.dumps(final_alloc))
                if enabled_strats:
                    db.set_config("active_strategy", enabled_strats[0])
                # Picker top-N
                db.set_config("picker_top_n", str(int(top_n)))
                # Strategy params — always save all (all expanders are rendered)
                db.set_config("rsi_period",str(p)); db.set_config("rsi_oversold",str(ov)); db.set_config("rsi_overbought",str(ob))
                db.set_config("macd_fast",str(mf)); db.set_config("macd_slow",str(ms)); db.set_config("macd_signal",str(msg))
                db.set_config("bb_window",str(bw)); db.set_config("bb_std",str(bs))
                db.set_config("ema_fast",str(ef)); db.set_config("ema_slow",str(es))
                db.set_config("momentum_window",str(mw)); db.set_config("momentum_threshold",str(mth))
                db.set_config("short_ma_fast",str(smf)); db.set_config("short_ma_slow",str(sms))
                # Risk limits
                db.set_config("position_pct",str(pct_r))
                db.set_config("max_positions",str(mpos_r))
                db.set_config("daily_loss_limit_pct",str(dloss_r))
                db.set_config("max_drawdown_pct",str(mdd_r))
                st.cache_data.clear()
                db.log("INFO",
                       f"[DASHBOARD] Config saved by {uname} — "
                       f"strategies={enabled_strats or ['(none)']}, "
                       f"top_n={int(top_n)}")
                st.success("Configuration saved.")
                st.rerun()

# ── Demo badge ────────────────────────────────────────────────────────────────

if DEMO:
    st.markdown(
        '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
        'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
        'border:1px solid #2a3a50;border-radius:4px;">DEMO MODE</div>',
        unsafe_allow_html=True)
if GUEST:
    st.markdown(
        '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
        'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
        'border:1px solid #ffa50055;border-radius:4px;">👁 GUEST MODE</div>',
        unsafe_allow_html=True)
