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
            ok_u = st.session_state.u == st.secrets["auth"]["username"]
            ok_p = bcrypt.checkpw(st.session_state.p.encode(),
                                   st.secrets["auth"]["hashed_password"].encode())
            if ok_u and ok_p:
                st.session_state["authenticated"] = True
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

# ── Data ──────────────────────────────────────────────────────────────────────

hb      = db.get_heartbeat()
cfg     = db.get_all_config()
now_utc = datetime.utcnow()

# ── HEADER ────────────────────────────────────────────────────────────────────

hl, hr = st.columns([6, 1])
with hl:
    if hb:
        age_min = int((now_utc - datetime.fromisoformat(hb["last_beat"])).total_seconds() / 60)
        alive   = (now_utc - datetime.fromisoformat(hb["last_beat"])) < timedelta(minutes=70)
        bdot    = '<span style="color:#00c896;">●</span>' if alive else '<span style="color:#ff4b4b;">●</span>'
        blbl    = f"{'ALIVE' if alive else 'STALE'} {age_min}m"
    else:
        bdot, blbl = '<span style="color:#ffa500;">●</span>', "NOT STARTED"

    on    = cfg.get("trading_enabled","true").lower()=="true"
    tdot  = '<span style="color:#00c896;">●</span>' if on else '<span style="color:#ff4b4b;">●</span>'
    strat = cfg.get("active_strategy","—").upper()
    api_n = db.count_recent_api_calls(60)

    st.markdown(
        f'<span style="font-size:0.58rem;letter-spacing:0.2em;color:#00d4aa;">KIM AND CHANG</span> '
        f'<span style="font-size:0.92rem;font-weight:700;letter-spacing:0.04em;">TRADING TECHNOLOGIES</span>'
        f'<span style="font-size:0.62rem;color:#6b8bb0;margin-left:1.2rem;">'
        f'{bdot} {blbl} &nbsp; {tdot} {"ON" if on else "HALTED"} &nbsp; '
        f'<span style="color:#e2e8f0;">{strat}</span> &nbsp; API {api_n}/200 &nbsp; '
        f'{now_utc.strftime("%H:%M UTC")}</span>',
        unsafe_allow_html=True)

with hr:
    rc1, rc2 = st.columns(2)
    with rc1:
        if st.button("⟳", help="Refresh"):
            st.cache_data.clear(); st.rerun()
    with rc2:
        if st.button("⎋", help="Logout"):
            st.session_state.clear(); st.rerun()

# ── ACCOUNT METRICS ───────────────────────────────────────────────────────────

try:
    ac   = broker.get_account()
    eq   = float(ac.equity)
    cash = float(ac.cash)
    bp   = float(ac.buying_power)
    leq  = float(ac.last_equity)
    pnl  = eq - leq
    pp   = (pnl / leq * 100) if leq else 0.0
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Equity",       f"${eq:,.2f}")
    c2.metric("Cash",         f"${cash:,.2f}")
    c3.metric("Buying Power", f"${bp:,.2f}")
    c4.metric("Today P&L",    f"${pnl:,.2f}", delta=f"{pp:+.2f}%")
except Exception as e:
    st.error(f"Account: {e}")

# ── PORTFOLIO CHART  |  SYSTEM STATUS ─────────────────────────────────────────

ch_col, ss_col = st.columns([3, 1])

with ch_col:
    per_opts = {"1W":"1W","1M":"1M","3M":"3M","1Y":"1A"}
    per_lbl  = st.radio("p", list(per_opts), index=1, horizontal=True, label_visibility="collapsed")
    ph = _ph(per_opts[per_lbl])
    if ph is not None:
        up  = ph["equity"].iloc[-1] >= ph["equity"].iloc[0]
        fig = go.Figure(go.Scatter(
            x=ph["date"], y=ph["equity"], mode="lines", fill="tozeroy",
            fillcolor="rgba(0,200,150,0.07)" if up else "rgba(255,75,75,0.07)",
            line=dict(color="#00c896" if up else "#ff4b4b", width=1.5),
            hovertemplate="$%{y:,.2f}<extra></extra>"))
        fig.update_layout(**PCFG, height=140)
        fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True, config=DCFG)
    else:
        st.info("No portfolio history yet.")

with ss_col:
    try:
        s = _sys()
        def _bar(p: float) -> str:
            c = "#00c896" if p<70 else "#ffa500" if p<90 else "#ff4b4b"
            b = "█"*int(p/10) + "░"*(10-int(p/10))
            return f'<span style="color:{c};font-family:monospace;font-size:0.65rem;">{b} {p:.0f}%</span>'
        st.markdown(
            f'<div style="font-size:0.6rem;color:#6b8bb0;line-height:1.7;">'
            f'CPU&nbsp; {_bar(s["cpu"])}<br>'
            f'RAM&nbsp; {_bar(s["mp"])} <span style="color:#333;">{s["mu"]}/{s["mt"]}MB</span><br>'
            f'DISK {_bar(s["dp"])} <span style="color:#333;">{s["du"]}/{s["dt"]}GB</span><br>'
            f'UP&nbsp;&nbsp; <span style="color:#e2e8f0;font-family:monospace;">{s["up"]}</span>'
            f'</div>', unsafe_allow_html=True)
    except Exception:
        st.caption("Stats unavailable")

# ── OPEN POSITIONS ────────────────────────────────────────────────────────────

_lbl("Positions")
try:
    pos = broker.get_all_positions()
    if pos:
        rows = [{"Sym":p.symbol,"Qty":float(p.qty),"Entry":float(p.avg_entry_price),
                 "Price":float(p.current_price),"Value":float(p.market_value),
                 "P&L($)":float(p.unrealized_pl),"P&L(%)":float(p.unrealized_plpc)*100}
                for p in pos]
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.format({"Entry":"${:.2f}","Price":"${:.2f}","Value":"${:,.0f}",
                             "P&L($)":"${:+,.2f}","P&L(%)":"{:+.2f}%"})
                    .map(_num_css, subset=["P&L($)","P&L(%)"]),
            use_container_width=True, hide_index=True, height=100)
    else:
        st.info("No open positions")
except Exception as e:
    st.error(str(e))

# ── TRADES  |  LOGS ───────────────────────────────────────────────────────────

tc, lc = st.columns([3, 2])

with tc:
    trades = db.get_recent_trades(limit=50)
    if trades:
        df = pd.DataFrame(trades)
        b  = int((df["side"]=="buy").sum())
        s2 = int((df["side"]=="sell").sum())
        _lbl(f"Trades — {len(df)} total · {b}B · {s2}S")
        df["slip"] = df["simulated_price"] - df["actual_price"]
        cols = ["timestamp","symbol","side","quantity","actual_price","slip","strategy"]
        df   = df[[c for c in cols if c in df.columns]]
        st.dataframe(df.style.map(_side_css, subset=["side"]),
                     use_container_width=True, hide_index=True, height=120)
    else:
        _lbl("Trades"); st.info("No trades yet")

with lc:
    _lbl("Bot Logs")
    lvls = st.multiselect("lv", ["INFO","WARN","ERROR"], default=["INFO","WARN","ERROR"],
                           label_visibility="collapsed")
    logs = db.get_recent_logs(limit=100)
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
with a1:
    if st.button("▶  Backtest", use_container_width=True):
        _dlg_backtest(cfg)
with a2:
    if st.button("⚙️  Config", use_container_width=True):
        _dlg_config(cfg)
with a3:
    events = db.get_recent_safety_events(limit=50)
    lbl    = f"🚨  Safety ({len(events)})" if events else "🚨  Safety"
    if st.button(lbl, use_container_width=True):
        _dlg_safety()
