"""
Kim and Chang Trading Technologies — Streamlit Dashboard
Single-page, no-scroll tactical layout. Never places trades.
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
    page_title="Kim and Chang Trading Technologies",
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
        <div style="padding:1.75rem 2rem;background:#111827;border:1px solid #1e3a5f;
                    border-top:3px solid #00d4aa;border-radius:3px;margin-top:10vh;">
            <div style="font-size:0.55rem;letter-spacing:0.22em;color:#00d4aa;">KIM AND CHANG</div>
            <div style="font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;">TRADING TECHNOLOGIES</div>
        </div>""", unsafe_allow_html=True)
        with st.form("login_form"):
            st.text_input("USERNAME", key="u")
            st.text_input("PASSWORD", type="password", key="p")
            submitted = st.form_submit_button("ACCESS TERMINAL", use_container_width=True)
        if submitted:
            u, p = st.session_state.u, st.session_state.p.encode()
            if (u == st.secrets["auth"]["username"] and
                    bcrypt.checkpw(p, st.secrets["auth"]["hashed_password"].encode())):
                st.session_state["authenticated"] = True
                st.session_state["demo"] = False
                st.rerun()
            elif (u == st.secrets["demo"]["username"] and
                    bcrypt.checkpw(p, st.secrets["demo"]["hashed_password"].encode())):
                st.session_state["authenticated"] = True
                st.session_state["demo"] = True
                st.rerun()
            else:
                st.error("Access denied.")
    return False

if not _check_login():
    st.stop()

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""<style>
/* ── Layout: kill all padding ───────────────────────────────── */
.block-container { padding: 0.35rem 0.9rem 0.1rem !important; max-width:100% !important; }
section[data-testid="stMain"] > div { padding-top: 0 !important; }
[data-testid="stSidebarCollapsedControl"] { display:none; }

/* ── Column gaps ─────────────────────────────────────────────── */
[data-testid="stHorizontalBlock"] { gap: 0.5rem !important; }
[data-testid="stVerticalBlock"] > * { margin-bottom: 0 !important; }
.element-container { margin-bottom: 0.15rem !important; }

/* ── Metric cards ────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background:#111827; border:1px solid #1e3a5f;
    border-left:2px solid #00d4aa; border-radius:2px;
    padding: 0.28rem 0.55rem !important;
}
[data-testid="stMetricValue"] { font-size:0.95rem !important; font-weight:700 !important; font-family:monospace !important; }
[data-testid="stMetricLabel"] { font-size:0.5rem !important; letter-spacing:0.12em !important; text-transform:uppercase !important; color:#6b8bb0 !important; }
[data-testid="stMetricDelta"] { font-size:0.6rem !important; }

/* ── Inputs / selects ─────────────────────────────────────────── */
[data-testid="stTextInput"]   input  { padding:0.15rem 0.35rem !important; font-size:0.72rem !important; height:1.75rem !important; }
[data-testid="stNumberInput"] input  { padding:0.15rem 0.35rem !important; font-size:0.72rem !important; height:1.75rem !important; }
[data-testid="stDateInput"]   input  { padding:0.15rem 0.35rem !important; font-size:0.72rem !important; height:1.75rem !important; }
[data-testid="stSelectbox"]   > div > div { min-height:1.75rem !important; font-size:0.72rem !important; padding:0.15rem 0.35rem !important; }
[data-testid="stMultiSelect"] > div  { min-height:1.75rem !important; font-size:0.72rem !important; }

/* ── Buttons ──────────────────────────────────────────────────── */
[data-testid="stButton"] > button { padding:0.18rem 0.5rem !important; font-size:0.7rem !important; }
[data-testid="stFormSubmitButton"] > button { font-size:0.72rem !important; }

/* ── Dividers ─────────────────────────────────────────────────── */
hr { margin:0.25rem 0 !important; border-color:#1e3a5f !important; }

/* ── Dataframes ───────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border:1px solid #1e3a5f; border-radius:2px; }

/* ── Dialog ───────────────────────────────────────────────────── */
[data-testid="stDialog"] [data-testid="metric-container"] { border-left-color:#f0b429; }

/* ── Mobile ───────────────────────────────────────────────────── */
@media (max-width:640px) {
    [data-testid="column"] { min-width:46% !important; flex:1 1 46% !important; }
    [data-testid="stMetricValue"] { font-size:0.8rem !important; }
}
</style>""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

PCFG = dict(
    paper_bgcolor="#0a0e1a", plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=10),
    margin=dict(l=0, r=4, t=16, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", showgrid=True, zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", showgrid=True, zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.01, font=dict(size=9)),
    hovermode="x unified",
)
DCFG = {"displayModeBar": False}

def _lbl(text: str, color: str = "#00d4aa") -> None:
    st.markdown(
        f'<div style="font-size:0.55rem;letter-spacing:0.16em;color:{color};'
        f'text-transform:uppercase;border-bottom:1px solid #1e3a5f;padding-bottom:2px;'
        f'margin-bottom:5px;">{text}</div>', unsafe_allow_html=True)

def _num_css(v) -> str:
    try:
        n = float(str(v).replace("$","").replace(",","").replace("%","").replace("+",""))
        if n > 0: return "color:#00c896;font-family:monospace"
        if n < 0: return "color:#ff4b4b;font-family:monospace"
    except (ValueError, TypeError): pass
    return "font-family:monospace"

def _side_css(v) -> str:
    return {"buy":"color:#00c896;font-weight:600","sell":"color:#ff4b4b;font-weight:600"}.get(v,"")

@st.cache_data(ttl=30)
def _sys() -> dict:
    cpu  = psutil.cpu_percent(interval=0.4)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    up   = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    h    = int(up.total_seconds()) // 3600
    return dict(cpu=cpu, mp=mem.percent, mu=mem.used>>20, mt=mem.total>>20,
                dp=disk.percent, du=disk.used>>30, dt=disk.total>>30,
                up=f"{h//24}d {h%24}h" if h>=24 else f"{h}h {int(up.total_seconds()%3600)//60}m")

@st.cache_data(ttl=300)
def _ph(period: str = "1M") -> pd.DataFrame | None:
    try:
        ph = broker.get_portfolio_history(period=period, timeframe="1D")
        if not ph.timestamp: return None
        df = pd.DataFrame({"date": pd.to_datetime(ph.timestamp, unit="s"),
                            "equity": ph.equity}).dropna()
        return df if not df.empty else None
    except Exception: return None

# ── Dialogs ───────────────────────────────────────────────────────────────────

@st.dialog("▶  BACKTESTING ENGINE", width="large")
def _dlg_backtest(cfg: dict) -> None:
    c1,c2,c3,c4,c5 = st.columns([1.2,1,1,1,1])
    with c1: sym  = st.text_input("Symbol",   "AAPL", label_visibility="collapsed",
                                   placeholder="Symbol").upper()
    with c2: strat= st.selectbox("Strat", list(STRATEGIES.keys()), label_visibility="collapsed")
    with c3: s    = st.date_input("Start", date(2024,1,1), label_visibility="collapsed")
    with c4: e    = st.date_input("End",   date.today(),   label_visibility="collapsed")
    with c5: cap  = st.number_input("Cap", value=100_000, step=10_000, label_visibility="collapsed")

    if st.button("▶  RUN", type="primary", use_container_width=True):
        if s >= e:
            st.error("Start must be before end.")
        else:
            with st.spinner(f"Running {strat.upper()} on {sym}…"):
                try:
                    st.session_state["bt"] = run_backtest(sym, strat, s, e, float(cap), cfg)
                    st.session_state["bt_lbl"] = f"{sym} · {strat.upper()} · {s} → {e}"
                except Exception as ex:
                    st.error(str(ex))

    if "bt" in st.session_state:
        r, m = st.session_state["bt"], st.session_state["bt"]["metrics"]
        st.caption(st.session_state.get("bt_lbl",""))
        mc1,mc2,mc3,mc4,mc5 = st.columns(5)
        mc1.metric("Return",   f"{m['total_return_pct']:+.2f}%")
        mc2.metric("Sharpe",   f"{m['sharpe_ratio']:.3f}")
        mc3.metric("Max DD",   f"{m['max_drawdown_pct']:.2f}%")
        mc4.metric("Win Rate", f"{m['win_rate_pct']:.1f}%")
        mc5.metric("Trades",   m["total_trades"])

        eq = r["equity_curve"]
        if not eq.empty:
            up  = m["total_return_pct"] >= 0
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=eq["date"], y=eq["equity"], mode="lines",
                fill="tozeroy",
                fillcolor="rgba(0,200,150,0.07)" if up else "rgba(255,75,75,0.07)",
                line=dict(color="#00c896" if up else "#ff4b4b", width=1.5),
                hovertemplate="$%{y:,.2f}<extra></extra>"))
            for side, sym_m, col in [("buy","triangle-up","#00c896"),("sell","triangle-down","#ff4b4b")]:
                sd = pd.DataFrame([t for t in r["trades"] if t["side"]==side])
                if not sd.empty:
                    sd["date"] = pd.to_datetime(sd["date"])
                    mg = sd.merge(eq, on="date", how="left")
                    fig.add_trace(go.Scatter(x=mg["date"], y=mg["equity"], mode="markers",
                        marker=dict(symbol=sym_m, size=9, color=col), name=side.title(),
                        hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>"))
            fig.add_hline(y=m["starting_capital"], line=dict(color="#333", width=1, dash="dot"))
            fig.update_layout(**PCFG, height=240)
            fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.0f"))
            st.plotly_chart(fig, use_container_width=True, config=DCFG)

        if r["trades"]:
            tdf = pd.DataFrame(r["trades"])
            st.dataframe(tdf.style.map(_side_css, subset=["side"]),
                         use_container_width=True, hide_index=True, height=160)


@st.dialog("⚙️  CONFIGURATION", width="large")
def _dlg_config(cfg: dict) -> None:
    # Kill switch
    en = cfg.get("trading_enabled","true").lower()=="true"
    ne = st.toggle("Trading enabled", value=en)
    if ne != en:
        db.set_config("trading_enabled","true" if ne else "false"); st.rerun()

    st.divider()

    av  = list(STRATEGIES.keys())
    cur = cfg.get("active_strategy","rsi")
    ns  = st.selectbox("Strategy", av, index=av.index(cur) if cur in av else 0)
    DESCS = {
        "rsi":          "**RSI:** 과매도(기본 30↓)→매수, 과매수(70↑)→매도. 횡보장 적합.",
        "macd":         "**MACD:** 시그널선 상향돌파→매수, 하향돌파→매도. 추세장 적합.",
        "bollinger":    "**볼린저:** 하단 이탈→매수, 상단 이탈→매도. 고변동성 적합.",
        "ema_crossover":"**EMA 크로스:** 골든크로스→매수, 데드크로스→매도. 추세추종.",
    }
    st.info(DESCS.get(ns,""))
    syms = st.text_input("Symbols", value=cfg.get("symbols",""), placeholder="AAPL,MSFT,GOOGL")

    if ns == "rsi":
        c1,c2,c3 = st.columns(3)
        with c1: p   = st.number_input("Period",   2,  50, int(cfg.get("rsi_period",14)))
        with c2: ov  = st.number_input("Oversold", 10.,50.,float(cfg.get("rsi_oversold",30)), step=1.)
        with c3: ob  = st.number_input("Overbought",50.,90.,float(cfg.get("rsi_overbought",70)),step=1.)
    elif ns == "macd":
        c1,c2,c3 = st.columns(3)
        with c1: mf  = st.number_input("Fast",   2, 50,int(cfg.get("macd_fast",12)))
        with c2: ms  = st.number_input("Slow",   5,100,int(cfg.get("macd_slow",26)))
        with c3: msg = st.number_input("Signal", 2, 50,int(cfg.get("macd_signal",9)))
    elif ns == "bollinger":
        c1,c2 = st.columns(2)
        with c1: bw  = st.number_input("Window",  5,100, int(cfg.get("bb_window",20)))
        with c2: bs  = st.number_input("Std Dev", .5,5.0,float(cfg.get("bb_std",2.0)),step=.5)
    elif ns == "ema_crossover":
        c1,c2 = st.columns(2)
        with c1: ef  = st.number_input("Fast EMA", 2, 50,int(cfg.get("ema_fast",9)))
        with c2: es  = st.number_input("Slow EMA", 5,200,int(cfg.get("ema_slow",21)))

    st.divider()
    c1,c2 = st.columns(2)
    with c1:
        pct   = st.number_input("Position size %",  .5,25., float(cfg.get("position_pct",5.)),  step=.5)
        dloss = st.number_input("Daily loss limit %",.5,20., float(cfg.get("daily_loss_limit_pct",2.)),step=.5)
    with c2:
        mpos  = st.number_input("Max positions", 1,20, int(cfg.get("max_positions",4)))
        mdd   = st.number_input("Max drawdown %",1.,50.,float(cfg.get("max_drawdown_pct",10.)),step=1.)
    mtpm  = st.number_input("Max trades/min", 1,50, int(cfg.get("max_trades_per_minute",5)))
    slip  = st.number_input("Slippage (bps)",  0,100,int(cfg.get("slippage_bps",5)))

    if st.button("💾  SAVE", type="primary", use_container_width=True):
        db.set_config("active_strategy",ns); db.set_config("symbols",syms)
        if ns=="rsi":              db.set_config("rsi_period",str(p)); db.set_config("rsi_oversold",str(ov)); db.set_config("rsi_overbought",str(ob))
        elif ns=="macd":           db.set_config("macd_fast",str(mf)); db.set_config("macd_slow",str(ms)); db.set_config("macd_signal",str(msg))
        elif ns=="bollinger":      db.set_config("bb_window",str(bw)); db.set_config("bb_std",str(bs))
        elif ns=="ema_crossover":  db.set_config("ema_fast",str(ef)); db.set_config("ema_slow",str(es))
        db.set_config("position_pct",str(pct)); db.set_config("max_positions",str(mpos))
        db.set_config("daily_loss_limit_pct",str(dloss)); db.set_config("max_drawdown_pct",str(mdd))
        db.set_config("max_trades_per_minute",str(mtpm)); db.set_config("slippage_bps",str(slip))
        st.cache_data.clear()
        st.success("✅ Saved."); st.rerun()


@st.dialog("🚨  SAFETY EVENTS", width="large")
def _dlg_safety() -> None:
    events = db.get_recent_safety_events(limit=50)
    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
    else:
        st.success("✅ No safety events recorded.")

# ── Demo mode ────────────────────────────────────────────────────────────────

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

def _demo_trades():
    return [{"timestamp":"2026-04-17 14:32","symbol":"AAPL","side":"buy","quantity":10,"actual_price":171.42,"slip":0.09,"strategy":"rsi"},
            {"timestamp":"2026-04-16 10:11","symbol":"MSFT","side":"buy","quantity":5, "actual_price":415.80,"slip":0.21,"strategy":"macd"},
            {"timestamp":"2026-04-15 15:47","symbol":"GOOGL","side":"sell","quantity":8,"actual_price":169.55,"slip":0.08,"strategy":"rsi"},
            {"timestamp":"2026-04-14 09:35","symbol":"TSLA","side":"buy","quantity":3, "actual_price":242.10,"slip":0.12,"strategy":"bollinger"},
            {"timestamp":"2026-04-13 11:22","symbol":"TSLA","side":"sell","quantity":3,"actual_price":251.80,"slip":0.13,"strategy":"bollinger"}]

def _demo_logs():
    return [{"timestamp":"2026-04-18 09:00","level":"INFO","message":"Bot cycle started"},
            {"timestamp":"2026-04-18 08:55","level":"INFO","message":"RSI signal: AAPL → hold"},
            {"timestamp":"2026-04-18 08:50","level":"WARN","message":"API rate limit approaching: 178/200"},
            {"timestamp":"2026-04-18 08:45","level":"INFO","message":"Heartbeat OK"},
            {"timestamp":"2026-04-17 15:30","level":"ERROR","message":"Order rejected: insufficient buying power"},
            {"timestamp":"2026-04-17 14:32","level":"INFO","message":"BUY AAPL qty=10 @ $171.42"}]

def _demo_ph() -> pd.DataFrame:
    import numpy as np
    rng  = pd.date_range(end=datetime.utcnow(), periods=30, freq="D")
    vals = 100_000 * (1 + pd.Series(np.random.randn(30).cumsum() * 0.008)).values
    return pd.DataFrame({"date": rng, "equity": vals})

# ── Data ──────────────────────────────────────────────────────────────────────

hb      = None if DEMO else db.get_heartbeat()
cfg     = {"trading_enabled":"true","active_strategy":"rsi"} if DEMO else db.get_all_config()
now_utc = datetime.utcnow()

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
    blbl    = f"ALIVE {age_min}m" if alive else f"STALE {age_min}m"
else:
    alive, blbl = False, "NOT STARTED"

on     = cfg.get("trading_enabled","true").lower() == "true"
strat  = cfg.get("active_strategy","—").upper()
api_n  = 0 if DEMO else db.count_recent_api_calls(60)
bdot_c = "#00c896" if alive else ("#ffa500" if not hb else "#ff4b4b")
tdot_c = "#00c896" if on else "#ff4b4b"
pnl_c  = "#00c896" if pnl >= 0 else "#ff4b4b"
pnl_s  = "+" if pnl >= 0 else ""

# ── HEADER — title + account metrics + status all inline ─────────────────────

h_l, h_r = st.columns([11, 1])
with h_l:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;padding:0.15rem 0;">'
        f'<span style="font-size:0.55rem;letter-spacing:0.2em;color:#00d4aa;">KIM &amp; CHANG</span>'
        f'<span style="font-size:0.88rem;font-weight:700;">TRADING TECHNOLOGIES</span>'
        f'<span style="color:#1e3a5f;font-size:0.8rem;">│</span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;">EQ&nbsp;<span style="color:#e2e8f0;font-family:monospace;">${eq:,.0f}</span></span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;">CASH&nbsp;<span style="color:#e2e8f0;font-family:monospace;">${cash:,.0f}</span></span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;">BP&nbsp;<span style="color:#e2e8f0;font-family:monospace;">${bp:,.0f}</span></span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;">P&amp;L&nbsp;<span style="color:{pnl_c};font-family:monospace;">{pnl_s}${pnl:,.0f}&nbsp;({pp:+.2f}%)</span></span>'
        f'<span style="color:#1e3a5f;font-size:0.8rem;">│</span>'
        f'<span style="font-size:0.62rem;"><span style="color:{bdot_c};">●</span>&nbsp;<span style="color:#6b8bb0;">{blbl}</span></span>'
        f'<span style="font-size:0.62rem;"><span style="color:{tdot_c};">●</span>&nbsp;<span style="color:#6b8bb0;">{"ON" if on else "HALTED"}</span></span>'
        f'<span style="font-size:0.62rem;color:#e2e8f0;">{strat}</span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;">API&nbsp;{api_n}/200&nbsp;·&nbsp;{now_utc.strftime("%H:%M UTC")}</span>'
        f'</div>',
        unsafe_allow_html=True)
with h_r:
    b1, b2 = st.columns(2)
    with b1:
        if st.button("⟳", help="Refresh"): st.cache_data.clear(); st.rerun()
    with b2:
        if st.button("⎋", help="Logout"):  st.session_state.clear(); st.rerun()

# ── MAIN GRID: Chart | Positions | Server ────────────────────────────────────

col_ch, col_pos, col_srv = st.columns([2.5, 2, 1.2])

with col_ch:
    per_opts = {"1W":"1W","1M":"1M","3M":"3M","1Y":"1A"}
    per_lbl  = st.radio("p", list(per_opts), index=1, horizontal=True, label_visibility="collapsed")
    ph = _demo_ph() if DEMO else _ph(per_opts[per_lbl])
    if ph is not None:
        up  = ph["equity"].iloc[-1] >= ph["equity"].iloc[0]
        fig = go.Figure(go.Scatter(
            x=ph["date"], y=ph["equity"], mode="lines", fill="tozeroy",
            fillcolor="rgba(0,200,150,0.07)" if up else "rgba(255,75,75,0.07)",
            line=dict(color="#00c896" if up else "#ff4b4b", width=1.5),
            hovertemplate="$%{y:,.2f}<extra></extra>"))
        fig.update_layout(**PCFG, height=220)
        fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True, config=DCFG)
    else:
        st.info("No portfolio history yet.")

with col_pos:
    try:
        pos = _demo_positions() if DEMO else broker.get_all_positions()
        if pos:
            rows = [{"Sym":p.symbol,"Qty":float(p.qty),"Entry":float(p.avg_entry_price),
                     "Price":float(p.current_price),"Val":float(p.market_value),
                     "P&L($)":float(p.unrealized_pl),"P&L(%)":float(p.unrealized_plpc)*100}
                    for p in pos]
            df = pd.DataFrame(rows)
            _lbl(f"Positions ({len(pos)})")
            st.dataframe(
                df.style.format({"Entry":"${:.2f}","Price":"${:.2f}","Val":"${:,.0f}",
                                 "P&L($)":"${:+,.2f}","P&L(%)":"{:+.2f}%"})
                        .map(_num_css, subset=["P&L($)","P&L(%)"]),
                use_container_width=True, hide_index=True, height=220)
        else:
            _lbl("Positions"); st.info("No open positions")
    except Exception as e:
        _lbl("Positions"); st.error(str(e))

with col_srv:
    _lbl("Server")
    try:
        s = dict(cpu=24,mp=41,mu=3280,mt=7976,dp=18,du=9,dt=50,up="12d 4h") if DEMO else _sys()
        def _bar(p: float) -> str:
            c = "#00c896" if p < 70 else "#ffa500" if p < 90 else "#ff4b4b"
            filled = int(p / 10)
            return (f'<span style="color:{c};font-family:monospace;font-size:0.6rem;">'
                    f'{"█"*filled}{"░"*(10-filled)}</span>'
                    f'<span style="color:#6b8bb0;font-size:0.6rem;"> {p:.0f}%</span>')
        st.markdown(
            f'<div style="font-size:0.6rem;color:#6b8bb0;line-height:1.9;">'
            f'CPU&nbsp;&nbsp; {_bar(s["cpu"])}<br>'
            f'RAM&nbsp;&nbsp; {_bar(s["mp"])} <span style="color:#444;font-size:0.58rem;">{s["mu"]}/{s["mt"]}M</span><br>'
            f'DISK&nbsp; {_bar(s["dp"])} <span style="color:#444;font-size:0.58rem;">{s["du"]}/{s["dt"]}G</span><br>'
            f'UP&nbsp;&nbsp;&nbsp; <span style="color:#e2e8f0;font-family:monospace;font-size:0.62rem;">{s["up"]}</span>'
            f'</div>', unsafe_allow_html=True)
    except Exception:
        st.caption("Stats unavailable")

# ── LOWER GRID: Trades | Logs ─────────────────────────────────────────────────

col_tr, col_lg = st.columns([3, 2])

with col_tr:
    trades = _demo_trades() if DEMO else db.get_recent_trades(limit=50)
    if trades:
        df = pd.DataFrame(trades)
        b  = int((df["side"]=="buy").sum())
        s2 = int((df["side"]=="sell").sum())
        _lbl(f"Trades — {len(df)} · {b}B {s2}S")
        if not DEMO and "simulated_price" in df.columns:
            df["slip"] = df["simulated_price"] - df["actual_price"]
        cols = ["timestamp","symbol","side","quantity","actual_price","slip","strategy"]
        df   = df[[c for c in cols if c in df.columns]]
        st.dataframe(df.style.map(_side_css, subset=["side"]),
                     use_container_width=True, hide_index=True, height=120)
    else:
        _lbl("Trades"); st.info("No trades yet")

with col_lg:
    _lbl("Bot Logs")
    lvls = st.multiselect("lv", ["INFO","WARN","ERROR"], default=["INFO","WARN","ERROR"],
                           label_visibility="collapsed")
    logs = _demo_logs() if DEMO else db.get_recent_logs(limit=100)
    if logs:
        df = pd.DataFrame(logs)
        df = df[df["level"].isin(lvls)][["timestamp","level","message"]]
        LS = {"ERROR":"color:#ff4b4b;font-weight:700","WARN":"color:#ffa500","INFO":"color:#6b8bb0"}
        st.dataframe(df.style.map(lambda v: LS.get(v,""), subset=["level"]),
                     use_container_width=True, hide_index=True, height=120)
    else:
        st.info("No logs yet")

# ── ACTION BAR ────────────────────────────────────────────────────────────────

st.divider()
a1, a2, a3, a4 = st.columns([1, 1, 1, 5])
if DEMO:
    with a1: st.button("▶  Backtest", disabled=True, use_container_width=True, help="Demo mode — no live data")
    with a2: st.button("⚙️  Config",  disabled=True, use_container_width=True, help="Demo mode — read only")
    with a3: st.button("🚨  Safety",  disabled=True, use_container_width=True, help="Demo mode — no live data")
    with a4: st.markdown('<span style="font-size:0.62rem;color:#ffa500;">⬡ DEMO MODE — UI preview only. No real data, trades, or API calls.</span>', unsafe_allow_html=True)
else:
    with a1:
        if st.button("▶  Backtest", use_container_width=True): _dlg_backtest(cfg)
    with a2:
        if st.button("⚙️  Config",  use_container_width=True): _dlg_config(cfg)
    with a3:
        events = db.get_recent_safety_events(limit=50)
        lbl    = f"🚨  Safety ({len(events)})" if events else "🚨  Safety"
        if st.button(lbl, use_container_width=True): _dlg_safety()
