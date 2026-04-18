"""
Kim and Chang Trading Technologies — Streamlit Dashboard
Clean professional layout. Never places trades.
"""

from __future__ import annotations
from datetime import date, datetime, timedelta

import bcrypt
import pandas as pd
import plotly.graph_objects as go
import psutil
import streamlit as st

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

# ── CSS (minimal — only what Streamlit can't do natively) ─────────────────────

st.markdown("""<style>
[data-testid="stSidebarCollapsedControl"] { display:none; }
.block-container { max-width:100% !important; padding-top:0.75rem !important; }
hr { border-color:#1e3a5f !important; margin:0.5rem 0 !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:6px !important; }
</style>""", unsafe_allow_html=True)

# ── Chart config ──────────────────────────────────────────────────────────────

_CHART = dict(
    paper_bgcolor="#0a0e1a",
    plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(l=0, r=8, t=20, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
    hovermode="x unified",
)
_NO_TOOLBAR = {"displayModeBar": False}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _panel_header(title: str) -> None:
    st.markdown(
        f'<p style="font-size:0.7rem;font-weight:600;letter-spacing:0.12em;'
        f'color:#00d4aa;text-transform:uppercase;margin-bottom:0.5rem;">{title}</p>',
        unsafe_allow_html=True)

def _num_style(v) -> str:
    try:
        n = float(str(v).replace("$","").replace(",","").replace("%","").replace("+",""))
        if n > 0: return "color:#00c896"
        if n < 0: return "color:#ff4b4b"
    except (ValueError, TypeError): pass
    return ""

def _side_style(v) -> str:
    return {"buy": "color:#00c896;font-weight:600",
            "sell": "color:#ff4b4b;font-weight:600"}.get(v, "")

@st.cache_data(ttl=30)
def _sys_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=0.5)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot = datetime.fromtimestamp(psutil.boot_time())
    up   = datetime.now() - boot
    h    = int(up.total_seconds()) // 3600
    return dict(
        cpu=cpu, ram_pct=mem.percent, ram_used=mem.used >> 20, ram_total=mem.total >> 20,
        disk_pct=disk.percent, disk_used=disk.used >> 30, disk_total=disk.total >> 30,
        uptime=f"{h//24}d {h%24}h" if h >= 24 else f"{h}h {int(up.total_seconds()%3600)//60}m",
    )

def _progress_bar_html(label: str, pct: float, note: str = "") -> str:
    color = "#00c896" if pct < 70 else "#ffa500" if pct < 90 else "#ff4b4b"
    note_html = f'<span style="color:#4a6a90;font-size:0.65rem;margin-left:6px;">{note}</span>' if note else ""
    return (
        f'<div style="display:flex;align-items:center;gap:6px;margin:4px 0;">'
        f'<span style="color:#6b8bb0;font-size:0.7rem;min-width:32px;">{label}</span>'
        f'<div style="flex:1;background:#1e3a5f;border-radius:3px;height:6px;">'
        f'<div style="background:{color};width:{min(pct,100):.0f}%;height:100%;border-radius:3px;"></div></div>'
        f'<span style="color:#e2e8f0;font-family:monospace;font-size:0.7rem;min-width:30px;'
        f'text-align:right;">{pct:.0f}%</span>{note_html}</div>'
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

def _equity_chart(df: pd.DataFrame, height: int = 200) -> go.Figure:
    up = df["equity"].iloc[-1] >= df["equity"].iloc[0]
    color = "#00c896" if up else "#ff4b4b"
    fill  = "rgba(0,200,150,0.08)" if up else "rgba(255,75,75,0.08)"
    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["equity"], mode="lines", fill="tozeroy",
        fillcolor=fill, line=dict(color=color, width=2),
        hovertemplate="$%{y:,.2f}<extra></extra>"))
    fig.update_layout(**_CHART, height=height)
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return fig

def _trades_chart(trades: list, height: int = 180) -> go.Figure:
    cfg = {**_CHART, "hovermode": "closest"}  # override to closest for bar chart
    fig = go.Figure()
    if trades:
        df = pd.DataFrame(trades)
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
                        f"<b>%{{customdata[0]}}</b> — {name.upper()}<br>"
                        "Qty: <b>%{y:.0f}</b><br>"
                        "Price: $%{customdata[1]:.2f}<br>"
                        "Strategy: %{customdata[2]}<br>"
                        "%{customdata[3]}<extra></extra>"
                    )
                ))
    else:
        fig.add_annotation(
            text="No trades recorded yet", x=0.5, y=0.5,
            xref="paper", yref="paper", showarrow=False,
            font=dict(color="#4a6a90", size=12))
    fig.update_layout(**cfg, height=height, barmode="overlay")
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
        {"timestamp":"2026-04-18 08:55","level":"INFO", "message":"RSI signal: AAPL → hold"},
        {"timestamp":"2026-04-18 08:50","level":"WARN", "message":"API rate limit approaching: 178/200"},
        {"timestamp":"2026-04-17 15:30","level":"ERROR","message":"Order rejected: insufficient buying power"},
        {"timestamp":"2026-04-17 14:32","level":"INFO", "message":"BUY AAPL qty=10 @ $171.42"},
    ]

def _demo_portfolio_history() -> pd.DataFrame:
    import numpy as np
    rng  = pd.date_range(end=datetime.utcnow(), periods=30, freq="D")
    vals = 100_000 * (1 + pd.Series(np.random.randn(30).cumsum() * 0.007)).values
    return pd.DataFrame({"date": rng, "equity": vals})

# ── Load data ─────────────────────────────────────────────────────────────────

hb      = None if DEMO else db.get_heartbeat()
cfg     = {"trading_enabled":"true","active_strategy":"rsi"} if DEMO else db.get_all_config()
now_utc = datetime.utcnow()
uname   = st.session_state.get("username", "—")

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
    bot_lbl = ("🟢 ALIVE" if alive else "🔴 STALE") + f" {age_min}m"
else:
    alive, bot_lbl = False, "⚪ NOT STARTED"

on       = cfg.get("trading_enabled","true").lower() == "true"
strat    = cfg.get("active_strategy","—").upper()
api_n    = 0 if DEMO else db.count_recent_api_calls(60)
trade_lbl = "🟢 ON" if on else "🔴 HALTED"

# ── HEADER ────────────────────────────────────────────────────────────────────

title_col, btn_col = st.columns([7, 1])
with title_col:
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:0.75rem;flex-wrap:wrap;">'
        f'<span style="font-size:0.6rem;letter-spacing:0.18em;color:#00d4aa;">KIM &amp; CHANG</span>'
        f'<span style="font-size:1.1rem;font-weight:700;">TRADING TECHNOLOGIES</span>'
        f'<span style="font-size:0.75rem;color:#4a6a90;">|</span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">{bot_lbl}</span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">{trade_lbl}</span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">Strategy: '
        f'<span style="color:#e2e8f0;">{strat}</span></span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">API {api_n}/200</span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">{now_utc.strftime("%H:%M UTC")}</span>'
        f'<span style="font-size:0.75rem;color:#4a6a90;">|</span>'
        f'<span style="font-size:0.75rem;color:#6b8bb0;">Signed in as '
        f'<span style="color:#00d4aa;">{uname.upper()}</span></span>'
        f'</div>',
        unsafe_allow_html=True)
with btn_col:
    rc1, rc2 = st.columns(2)
    with rc1:
        if st.button("↺", help="Refresh page"): st.cache_data.clear(); st.rerun()
    with rc2:
        if st.button("⏻", help="Sign out"): st.session_state.clear(); st.rerun()

# ── ACCOUNT METRICS ───────────────────────────────────────────────────────────

st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Portfolio Balance", f"${eq:,.2f}")
m2.metric("Cash", f"${cash:,.2f}")
m3.metric("Buying Power", f"${bp:,.2f}")
m4.metric("Today P&L", f"${pnl:+,.2f}", delta=f"{pp:+.2f}%")
st.divider()

# ── MAIN: Left charts | Right data ────────────────────────────────────────────

left, right = st.columns([3, 2], gap="medium")

with left:
    # Portfolio equity
    with st.container(border=True):
        _panel_header("Portfolio Equity")
        per_key = st.radio(
            "Period", ["1W","1M","3M","1Y"], index=1, horizontal=True,
            label_visibility="collapsed")
        period_map = {"1W":"1W","1M":"1M","3M":"3M","1Y":"1A"}
        ph = _demo_portfolio_history() if DEMO else _portfolio_history(period_map[per_key])
        if ph is not None:
            st.plotly_chart(_equity_chart(ph, height=200),
                            use_container_width=True, config=_NO_TOOLBAR)
        else:
            st.info("No portfolio history available yet.")

    # Trade activity
    with st.container(border=True):
        trades = _demo_trades() if DEMO else db.get_recent_trades(limit=50)
        buys   = sum(1 for t in trades if t.get("side") == "buy")  if trades else 0
        sells  = sum(1 for t in trades if t.get("side") == "sell") if trades else 0
        _panel_header(f"Trade Activity — {buys} buy · {sells} sell")
        st.plotly_chart(_trades_chart(trades, height=180),
                        use_container_width=True, config=_NO_TOOLBAR)

with right:
    # Positions
    with st.container(border=True):
        try:
            pos = _demo_positions() if DEMO else broker.get_all_positions()
            if pos:
                rows = [{"Symbol": p.symbol, "Qty": float(p.qty),
                         "Price": float(p.current_price),
                         "P&L ($)": float(p.unrealized_pl),
                         "P&L (%)": float(p.unrealized_plpc) * 100}
                        for p in pos]
                _panel_header(f"Open Positions ({len(pos)})")
                df_p = pd.DataFrame(rows)
                st.dataframe(
                    df_p.style
                        .format({"Price":"${:.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"})
                        .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                    use_container_width=True, hide_index=True, height=175)
            else:
                _panel_header("Open Positions — Sample")
                st.caption("No live positions. Showing illustrative sample data.")
                df_p = pd.DataFrame(_SAMPLE_POSITIONS)
                st.dataframe(
                    df_p.style
                        .format({"Price":"${:.2f}","P&L ($)":"${:+,.2f}","P&L (%)":"{:+.2f}%"})
                        .map(_num_style, subset=["P&L ($)","P&L (%)"]),
                    use_container_width=True, hide_index=True, height=145)
        except Exception as e:
            _panel_header("Open Positions")
            st.error(str(e))

    # Server status + Safety
    with st.container(border=True):
        srv_col, saf_col = st.columns([3, 2])
        with srv_col:
            _panel_header("Server")
            try:
                s = (dict(cpu=24,ram_pct=41,ram_used=3280,ram_total=7976,
                          disk_pct=18,disk_used=9,disk_total=50,uptime="12d 4h")
                     if DEMO else _sys_stats())
                html = (
                    _progress_bar_html("CPU",  s["cpu"])
                    + _progress_bar_html("RAM",  s["ram_pct"],
                                         f'{s["ram_used"]}/{s["ram_total"]} MB')
                    + _progress_bar_html("Disk", s["disk_pct"],
                                         f'{s["disk_used"]}/{s["disk_total"]} GB')
                    + f'<p style="font-size:0.7rem;color:#6b8bb0;margin:6px 0 0;">'
                    f'Uptime: <span style="color:#e2e8f0;font-family:monospace;">'
                    f'{s["uptime"]}</span></p>'
                )
                st.markdown(html, unsafe_allow_html=True)
            except Exception:
                st.caption("Stats unavailable")

        with saf_col:
            _panel_header("Safety")
            events = [] if DEMO else db.get_recent_safety_events(limit=5)
            if events:
                sdf       = pd.DataFrame(events)
                show_cols = [c for c in ["timestamp","event"] if c in sdf.columns]
                st.dataframe(sdf[show_cols], use_container_width=True,
                             hide_index=True, height=120)
            else:
                st.success("No safety events")

# ── BOTTOM: Backtest | Config + Logs ──────────────────────────────────────────

st.divider()
bt_col, cfg_col = st.columns([2, 3], gap="medium")

# ── Backtest ──────────────────────────────────────────────────────────────────
with bt_col:
    with st.container(border=True):
        _panel_header("Backtest Engine")
        if DEMO:
            st.info("Demo mode — backtesting requires live API access.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                sym_bt = st.text_input("Symbol", "AAPL",
                                       placeholder="e.g. AAPL").upper()
            with c2:
                strat_bt = st.selectbox("Strategy", list(STRATEGIES.keys()))

            c3, c4 = st.columns(2)
            with c3: s_bt = st.date_input("Start date", date(2024, 1, 1))
            with c4: e_bt = st.date_input("End date",   date.today())

            cap_bt = st.number_input("Starting capital ($)", value=100_000, step=10_000)

            if st.button("▶  Run Backtest", type="primary", use_container_width=True):
                if s_bt >= e_bt:
                    st.error("Start date must be before end date.")
                else:
                    with st.spinner(f"Running {strat_bt.upper()} on {sym_bt}…"):
                        try:
                            st.session_state["bt"] = run_backtest(
                                sym_bt, strat_bt, s_bt, e_bt, float(cap_bt), cfg)
                            st.session_state["bt_lbl"] = (
                                f"{sym_bt} · {strat_bt.upper()} · {s_bt} → {e_bt}")
                        except Exception as ex:
                            st.error(str(ex))

            if "bt" in st.session_state:
                m = st.session_state["bt"]["metrics"]
                st.caption(st.session_state.get("bt_lbl", ""))
                r1, r2, r3 = st.columns(3)
                r1.metric("Return",   f"{m['total_return_pct']:+.2f}%")
                r2.metric("Sharpe",   f"{m['sharpe_ratio']:.2f}")
                r3.metric("Max DD",   f"{m['max_drawdown_pct']:.2f}%")
                r4, r5, _ = st.columns(3)
                r4.metric("Win Rate", f"{m['win_rate_pct']:.1f}%")
                r5.metric("Trades",   m["total_trades"])
                eq_bt = st.session_state["bt"]["equity_curve"]
                if not eq_bt.empty:
                    up_bt = m["total_return_pct"] >= 0
                    fig_bt = go.Figure(go.Scatter(
                        x=eq_bt["date"], y=eq_bt["equity"], mode="lines",
                        fill="tozeroy",
                        fillcolor="rgba(0,200,150,0.08)" if up_bt else "rgba(255,75,75,0.08)",
                        line=dict(color="#00c896" if up_bt else "#ff4b4b", width=1.5),
                        hovertemplate="$%{y:,.2f}<extra></extra>"))
                    fig_bt.add_hline(y=m["starting_capital"],
                                     line=dict(color="#444", width=1, dash="dot"))
                    fig_bt.update_layout(**_CHART, height=140)
                    fig_bt.update_yaxes(tickprefix="$", tickformat=",.0f")
                    st.plotly_chart(fig_bt, use_container_width=True, config=_NO_TOOLBAR)

# ── Configuration + Logs ──────────────────────────────────────────────────────
with cfg_col:
    with st.container(border=True):
        _panel_header("Configuration")
        if DEMO:
            st.info("Demo mode — configuration is read-only.")
        else:
            DESCS = {
                "rsi":          "**RSI** — 과매도(↓30) 매수 · 과매수(↑70) 매도. 횡보장에 적합.",
                "macd":         "**MACD** — 시그널선 상향돌파 매수 · 하향돌파 매도. 추세장에 적합.",
                "bollinger":    "**Bollinger Bands** — 하단 이탈 매수 · 상단 이탈 매도. 고변동성 적합.",
                "ema_crossover":"**EMA Crossover** — 골든크로스 매수 · 데드크로스 매도. 추세추종.",
            }
            av  = list(STRATEGIES.keys())
            cur = cfg.get("active_strategy", "rsi")

            f1, f2 = st.columns([2, 1])
            with f1:
                ns = st.selectbox("Active strategy",
                                  av, index=av.index(cur) if cur in av else 0)
            with f2:
                en = cfg.get("trading_enabled","true").lower() == "true"
                ne = st.toggle("Trading enabled", value=en)
                if ne != en:
                    db.set_config("trading_enabled", "true" if ne else "false")
                    st.rerun()

            st.markdown(DESCS.get(ns, ""), help=None)

            # Strategy parameters
            if ns == "rsi":
                c1, c2, c3 = st.columns(3)
                with c1: p   = st.number_input("RSI period",   2,  50, int(cfg.get("rsi_period",14)))
                with c2: ov  = st.number_input("Oversold",    10., 50., float(cfg.get("rsi_oversold",30)),   step=1.)
                with c3: ob  = st.number_input("Overbought",  50., 90., float(cfg.get("rsi_overbought",70)), step=1.)
            elif ns == "macd":
                c1, c2, c3 = st.columns(3)
                with c1: mf  = st.number_input("Fast period",  2,  50, int(cfg.get("macd_fast",12)))
                with c2: ms  = st.number_input("Slow period",  5, 100, int(cfg.get("macd_slow",26)))
                with c3: msg = st.number_input("Signal period",2,  50, int(cfg.get("macd_signal",9)))
            elif ns == "bollinger":
                c1, c2 = st.columns(2)
                with c1: bw  = st.number_input("Window",  5, 100, int(cfg.get("bb_window",20)))
                with c2: bs  = st.number_input("Std dev", .5, 5.0, float(cfg.get("bb_std",2.0)), step=.5)
            elif ns == "ema_crossover":
                c1, c2 = st.columns(2)
                with c1: ef  = st.number_input("Fast EMA", 2,  50, int(cfg.get("ema_fast",9)))
                with c2: es  = st.number_input("Slow EMA", 5, 200, int(cfg.get("ema_slow",21)))

            st.markdown("**Risk limits**")
            r1, r2, r3, r4 = st.columns(4)
            with r1: pct   = st.number_input("Position size %",  .5, 25., float(cfg.get("position_pct",5.)),        step=.5)
            with r2: dloss = st.number_input("Daily loss limit %",.5, 20., float(cfg.get("daily_loss_limit_pct",2.)),step=.5)
            with r3: mpos  = st.number_input("Max positions",     1,  20,  int(cfg.get("max_positions",4)))
            with r4: mdd   = st.number_input("Max drawdown %",   1., 50., float(cfg.get("max_drawdown_pct",10.)),   step=1.)

            if st.button("Save configuration", type="primary", use_container_width=True):
                db.set_config("active_strategy", ns)
                if ns == "rsi":
                    db.set_config("rsi_period", str(p))
                    db.set_config("rsi_oversold", str(ov))
                    db.set_config("rsi_overbought", str(ob))
                elif ns == "macd":
                    db.set_config("macd_fast", str(mf))
                    db.set_config("macd_slow", str(ms))
                    db.set_config("macd_signal", str(msg))
                elif ns == "bollinger":
                    db.set_config("bb_window", str(bw))
                    db.set_config("bb_std", str(bs))
                elif ns == "ema_crossover":
                    db.set_config("ema_fast", str(ef))
                    db.set_config("ema_slow", str(es))
                db.set_config("position_pct", str(pct))
                db.set_config("max_positions", str(mpos))
                db.set_config("daily_loss_limit_pct", str(dloss))
                db.set_config("max_drawdown_pct", str(mdd))
                st.cache_data.clear()
                st.success("Configuration saved.")
                st.rerun()

    # Bot logs
    with st.container(border=True):
        _panel_header("Bot Logs")
        logs = _demo_logs() if DEMO else db.get_recent_logs(limit=50)
        if logs:
            df_l = pd.DataFrame(logs)[["timestamp","level","message"]]
            LS   = {"ERROR":"color:#ff4b4b;font-weight:600",
                    "WARN": "color:#ffa500",
                    "INFO": "color:#6b8bb0"}
            st.dataframe(
                df_l.style.map(lambda v: LS.get(v, ""), subset=["level"]),
                use_container_width=True, hide_index=True, height=160)
        else:
            st.info("No log entries yet.")

# ── Demo badge ────────────────────────────────────────────────────────────────

if DEMO:
    st.markdown(
        '<div style="position:fixed;bottom:12px;right:16px;font-size:0.7rem;'
        'color:#ffa500;background:#0a0e1a;padding:4px 10px;'
        'border:1px solid #2a3a50;border-radius:4px;">'
        'DEMO MODE</div>',
        unsafe_allow_html=True)
