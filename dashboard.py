"""
Kim and Chang Trading Technologies — Streamlit Dashboard
Single-page tactical layout. Never places trades.
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
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("""
        <div style="padding:2rem 2.25rem;background:#111827;
                    border:1px solid #1e3a5f;border-top:3px solid #00d4aa;
                    border-radius:3px;margin-top:8vh;">
            <div style="font-size:0.58rem;letter-spacing:0.22em;color:#00d4aa;">
                KIM AND CHANG
            </div>
            <div style="font-size:1.15rem;font-weight:700;margin-bottom:1.5rem;
                        letter-spacing:0.04em;">
                TRADING TECHNOLOGIES
            </div>
        </div>
        """, unsafe_allow_html=True)
        with st.form("login_form"):
            st.text_input("USERNAME", key="u", label_visibility="visible")
            st.text_input("PASSWORD", type="password", key="p", label_visibility="visible")
            submitted = st.form_submit_button("ACCESS TERMINAL", use_container_width=True)
        if submitted:
            valid_user = st.session_state.u == st.secrets["auth"]["username"]
            valid_pass = bcrypt.checkpw(
                st.session_state.p.encode(),
                st.secrets["auth"]["hashed_password"].encode(),
            )
            if valid_user and valid_pass:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Access denied.")
    return False


if not _check_login():
    st.stop()

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Core layout */
.block-container { padding: 0.9rem 1.4rem !important; max-width: 100% !important; }

/* Metric cards — left-accent style */
[data-testid="metric-container"] {
    background: #111827;
    border: 1px solid #1e3a5f;
    border-left: 3px solid #00d4aa;
    border-radius: 2px;
    padding: 0.7rem 1rem !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Courier New', monospace !important;
    font-size: 1.3rem !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.62rem !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    color: #6b8bb0 !important;
}
[data-testid="stMetricDelta"]  { font-size: 0.78rem !important; }

/* Backtest metric cards — yellow accent */
.bt-metric [data-testid="metric-container"] { border-left-color: #f0b429; }

/* Expander */
[data-testid="stExpander"] {
    border: 1px solid #1e3a5f !important;
    border-radius: 2px !important;
    background: #0d1220 !important;
}

/* Dataframe */
[data-testid="stDataFrame"] { border: 1px solid #1e3a5f; border-radius: 2px; }

/* Dividers */
hr { border-color: #1e3a5f !important; margin: 0.65rem 0 !important; }

/* Sidebar hidden — everything on main page */
[data-testid="stSidebarCollapsedControl"] { display: none; }

/* Mobile — wrap 4-col metrics to 2×2 */
@media (max-width: 640px) {
    [data-testid="column"]           { min-width: 46% !important; flex: 1 1 46% !important; }
    [data-testid="metric-container"] { padding: 0.5rem !important; }
    [data-testid="stMetricValue"]    { font-size: 1rem !important; }
    .block-container                 { padding: 0.5rem !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

PLOTLY_BASE: dict = dict(
    paper_bgcolor="#0a0e1a",
    plot_bgcolor="#111827",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(l=0, r=8, t=28, b=0),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", showgrid=True, zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", showgrid=True, zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.02),
    hovermode="x unified",
)
CHART_CFG = {"displayModeBar": False}


def _label(text: str, color: str = "#00d4aa") -> None:
    st.markdown(
        f'<div style="font-size:0.6rem;letter-spacing:0.18em;color:{color};'
        f'text-transform:uppercase;border-bottom:1px solid #1e3a5f;'
        f'padding-bottom:3px;margin-bottom:10px;">{text}</div>',
        unsafe_allow_html=True,
    )


def _num_color(val) -> str:
    try:
        n = float(str(val).replace("$","").replace(",","").replace("%","").replace("+",""))
        if n > 0: return "color:#00c896;font-family:monospace"
        if n < 0: return "color:#ff4b4b;font-family:monospace"
    except (ValueError, TypeError):
        pass
    return "font-family:monospace"


def _side_color(val) -> str:
    if val == "buy":  return "color:#00c896;font-weight:600"
    if val == "sell": return "color:#ff4b4b;font-weight:600"
    return ""


@st.cache_data(ttl=30)
def _sys_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=0.5)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot = datetime.fromtimestamp(psutil.boot_time())
    up   = datetime.now() - boot
    h, m = divmod(int(up.total_seconds()), 3600)
    return {
        "cpu": cpu, "mem_pct": mem.percent,
        "mem_used_mb": mem.used // 1024 // 1024,
        "mem_total_mb": mem.total // 1024 // 1024,
        "disk_pct": disk.percent,
        "disk_used_gb": disk.used // 1024 // 1024 // 1024,
        "disk_total_gb": disk.total // 1024 // 1024 // 1024,
        "uptime": f"{h // 24}d {h % 24}h {m // 60}m" if h >= 24 else f"{h}h {m}m",
    }


@st.cache_data(ttl=300)
def _portfolio_history(period: str = "1M") -> pd.DataFrame | None:
    try:
        ph = broker.get_portfolio_history(period=period, timeframe="1D")
        if not ph.timestamp:
            return None
        df = pd.DataFrame({
            "date":   pd.to_datetime(ph.timestamp, unit="s"),
            "equity": ph.equity,
            "pnl":    ph.profit_loss,
        }).dropna(subset=["equity"])
        return df if not df.empty else None
    except Exception:
        return None


# ── Global data ───────────────────────────────────────────────────────────────

hb      = db.get_heartbeat()
cfg     = db.get_all_config()
now_utc = datetime.utcnow()

# ── HEADER ────────────────────────────────────────────────────────────────────

h_left, h_right = st.columns([5, 1])
with h_left:
    st.markdown(
        '<span style="font-size:0.57rem;letter-spacing:0.22em;color:#00d4aa;">'
        'KIM AND CHANG</span><br>'
        '<span style="font-size:1.2rem;font-weight:700;letter-spacing:0.05em;">'
        'TRADING TECHNOLOGIES</span>',
        unsafe_allow_html=True,
    )

with h_right:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("⟳", help="Refresh page"):
            st.cache_data.clear()
            st.rerun()
    with c2:
        if st.button("⎋", help="Logout"):
            st.session_state.clear()
            st.rerun()

# Status bar
if hb:
    last_beat = datetime.fromisoformat(hb["last_beat"])
    age_min   = int((now_utc - last_beat).total_seconds() / 60)
    alive     = (now_utc - last_beat) < timedelta(minutes=70)
    dot       = '<span style="color:#00c896;">●</span>' if alive else '<span style="color:#ff4b4b;">●</span>'
    label     = f"BOT {'ALIVE' if alive else 'STALE'} &nbsp;·&nbsp; {age_min}m ago"
else:
    dot, label = '<span style="color:#ffa500;">●</span>', "BOT NOT STARTED"

strategy_label = cfg.get("active_strategy", "—").upper()
trading_on     = cfg.get("trading_enabled", "true").lower() == "true"
trade_dot      = '<span style="color:#00c896;">●</span>' if trading_on else '<span style="color:#ff4b4b;">●</span>'

st.markdown(
    f'<div style="font-size:0.7rem;color:#6b8bb0;margin:0.2rem 0 0.6rem;">'
    f'{dot} {label} &nbsp;&nbsp;'
    f'{trade_dot} TRADING {"ON" if trading_on else "HALTED"} &nbsp;&nbsp;'
    f'STRATEGY: <span style="color:#e2e8f0;">{strategy_label}</span> &nbsp;&nbsp;'
    f'<span style="color:#444;">{now_utc.strftime("%Y-%m-%d %H:%M UTC")}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

st.divider()

# ── ACCOUNT METRICS ───────────────────────────────────────────────────────────

try:
    acct         = broker.get_account()
    equity       = float(acct.equity)
    cash         = float(acct.cash)
    buying_power = float(acct.buying_power)
    last_equity  = float(acct.last_equity)
    pnl          = equity - last_equity
    pnl_pct      = (pnl / last_equity * 100) if last_equity else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equity",       f"${equity:,.2f}")
    c2.metric("Cash",         f"${cash:,.2f}")
    c3.metric("Buying Power", f"${buying_power:,.2f}")
    c4.metric("Today P&L",    f"${pnl:,.2f}", delta=f"{pnl_pct:+.2f}%")
except Exception as e:
    st.error(f"Account unavailable: {e}")

st.divider()

# ── EQUITY CURVE  |  SYSTEM STATUS ───────────────────────────────────────────

chart_col, sys_col = st.columns([3, 1])

with chart_col:
    period_options = {"1 Week": "1W", "1 Month": "1M", "3 Months": "3M", "1 Year": "1A"}
    sel_period_label = st.radio(
        "Period", list(period_options.keys()), index=1,
        horizontal=True, label_visibility="collapsed",
    )
    sel_period = period_options[sel_period_label]
    _label(f"Portfolio Equity — {sel_period_label}")

    ph_df = _portfolio_history(sel_period)
    if ph_df is not None:
        # Color the fill based on overall P&L direction
        fill_color = "rgba(0,200,150,0.08)" if ph_df["equity"].iloc[-1] >= ph_df["equity"].iloc[0] else "rgba(255,75,75,0.08)"
        line_color = "#00c896" if ph_df["equity"].iloc[-1] >= ph_df["equity"].iloc[0] else "#ff4b4b"

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=ph_df["date"], y=ph_df["equity"],
            mode="lines", fill="tozeroy",
            fillcolor=fill_color,
            line=dict(color=line_color, width=1.8),
            name="Equity",
            hovertemplate="$%{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(**PLOTLY_BASE, height=230)
        fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
    else:
        st.info("No portfolio history yet — the bot needs to have run at least once.")

with sys_col:
    _label("Server")
    try:
        s = _sys_stats()
        def _bar(pct: float, warn=70, crit=90) -> str:
            color = "#00c896" if pct < warn else "#ffa500" if pct < crit else "#ff4b4b"
            filled = int(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            return f'<span style="color:{color};font-family:monospace;">{bar}</span>'

        st.markdown(f"""
        <div style="font-size:0.72rem;line-height:2.2;">
        <span style="color:#6b8bb0;font-size:0.6rem;">CPU</span><br>
        {_bar(s["cpu"])} <span style="font-family:monospace;">{s["cpu"]:.0f}%</span><br>
        <span style="color:#6b8bb0;font-size:0.6rem;">RAM</span><br>
        {_bar(s["mem_pct"])} <span style="font-family:monospace;">{s["mem_pct"]:.0f}%</span>
        <span style="color:#333;font-size:0.65rem;"> {s["mem_used_mb"]}/{s["mem_total_mb"]} MB</span><br>
        <span style="color:#6b8bb0;font-size:0.6rem;">DISK</span><br>
        {_bar(s["disk_pct"])} <span style="font-family:monospace;">{s["disk_pct"]:.0f}%</span>
        <span style="color:#333;font-size:0.65rem;"> {s["disk_used_gb"]}/{s["disk_total_gb"]} GB</span><br>
        <span style="color:#6b8bb0;font-size:0.6rem;">UPTIME</span><br>
        <span style="font-family:monospace;color:#e2e8f0;">{s["uptime"]}</span>
        </div>
        """, unsafe_allow_html=True)
    except Exception:
        st.caption("System stats unavailable")

    st.divider()
    _label("API")
    api_count = db.count_recent_api_calls(60)
    st.progress(min(api_count / 200, 1.0))
    st.markdown(
        f'<span style="font-family:monospace;font-size:0.75rem;">{api_count}</span>'
        f'<span style="color:#444;font-size:0.72rem;"> / 200 per min</span>',
        unsafe_allow_html=True,
    )

    st.divider()
    _label("Kill Switch")
    new_enabled = st.toggle("Trading enabled", value=trading_on, label_visibility="collapsed")
    if new_enabled != trading_on:
        db.set_config("trading_enabled", "true" if new_enabled else "false")
        st.rerun()
    st.markdown(
        f'<span style="font-size:0.75rem;color:{"#00c896" if new_enabled else "#ff4b4b"};">'
        f'{"● TRADING ON" if new_enabled else "● TRADING HALTED"}</span>',
        unsafe_allow_html=True,
    )

st.divider()

# ── OPEN POSITIONS ────────────────────────────────────────────────────────────

_label("Open Positions — Live from Alpaca")
try:
    positions = broker.get_all_positions()
    if positions:
        rows = [{
            "Symbol":    p.symbol,
            "Qty":       float(p.qty),
            "Avg Entry": float(p.avg_entry_price),
            "Current":   float(p.current_price),
            "Mkt Value": float(p.market_value),
            "P&L ($)":   float(p.unrealized_pl),
            "P&L (%)":   float(p.unrealized_plpc) * 100,
        } for p in positions]
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style
              .format({
                  "Avg Entry": "${:.2f}", "Current": "${:.2f}",
                  "Mkt Value": "${:,.2f}",
                  "P&L ($)": "${:+,.2f}", "P&L (%)": "{:+.2f}%",
              })
              .map(_num_color, subset=["P&L ($)", "P&L (%)"]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No open positions")
except Exception as e:
    st.error(f"Positions unavailable: {e}")

st.divider()

# ── TRADES  |  LOGS ───────────────────────────────────────────────────────────

t_col, l_col = st.columns([3, 2])

with t_col:
    trades = db.get_recent_trades(limit=50)
    if trades:
        df    = pd.DataFrame(trades)
        buys  = int((df["side"] == "buy").sum())
        sells = int((df["side"] == "sell").sum())
        _label(f"Recent Trades — {len(df)} total · {buys} buys · {sells} sells")
        df["slippage"] = df["simulated_price"] - df["actual_price"]
        cols = ["timestamp","symbol","side","quantity","actual_price","simulated_price","slippage","strategy"]
        df = df[[c for c in cols if c in df.columns]]
        st.dataframe(
            df.style.map(_side_color, subset=["side"]),
            use_container_width=True, hide_index=True, height=300,
        )
    else:
        _label("Recent Trades")
        st.info("No trades yet")

with l_col:
    _label("Bot Logs")
    level_filter = st.multiselect(
        "levels", ["INFO","WARN","ERROR"], default=["INFO","WARN","ERROR"],
        label_visibility="collapsed",
    )
    logs = db.get_recent_logs(limit=150)
    if logs:
        df = pd.DataFrame(logs)
        df = df[df["level"].isin(level_filter)][["timestamp","level","message"]]
        _LVL = {"ERROR":"color:#ff4b4b;font-weight:700","WARN":"color:#ffa500;font-weight:600","INFO":"color:#6b8bb0"}
        st.dataframe(
            df.style.map(lambda v: _LVL.get(v,""), subset=["level"]),
            use_container_width=True, hide_index=True, height=300,
        )
    else:
        st.info("No logs yet")

st.divider()

# ── BACKTESTING ───────────────────────────────────────────────────────────────

_label("Backtesting Engine", color="#f0b429")

bc1, bc2, bc3, bc4, bc5 = st.columns([1, 1, 1, 1, 1])
with bc1: bt_symbol   = st.text_input("Symbol",   value="AAPL",       key="bt_sym").upper()
with bc2: bt_strategy = st.selectbox("Strategy",  list(STRATEGIES.keys()), key="bt_strat")
with bc3: bt_start    = st.date_input("Start",    value=date(2024, 1, 1), key="bt_start")
with bc4: bt_end      = st.date_input("End",      value=date.today(),     key="bt_end")
with bc5: bt_capital  = st.number_input("Capital ($)", value=100_000, step=10_000, key="bt_cap")

if st.button("▶  RUN BACKTEST", type="primary", use_container_width=True):
    if bt_start >= bt_end:
        st.error("Start date must be before end date.")
    else:
        with st.spinner(f"Fetching {bt_symbol} data and running {bt_strategy.upper()} simulation…"):
            try:
                st.session_state["bt_result"] = run_backtest(
                    symbol=bt_symbol,
                    strategy_name=bt_strategy,
                    start=bt_start,
                    end=bt_end,
                    starting_capital=float(bt_capital),
                    settings=cfg,
                )
                st.session_state["bt_label"] = f"{bt_symbol} · {bt_strategy.upper()} · {bt_start} → {bt_end}"
            except Exception as e:
                st.error(f"Backtest failed: {e}")

if "bt_result" in st.session_state:
    result = st.session_state["bt_result"]
    m      = result["metrics"]
    eq_df  = result["equity_curve"]
    tlist  = result["trades"]

    st.caption(f"Results — {st.session_state.get('bt_label','')}")

    # Metrics row
    with st.container():
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        ret_color = "normal" if m["total_return_pct"] >= 0 else "inverse"
        mc1.metric("Total Return",   f"{m['total_return_pct']:+.2f}%")
        mc2.metric("Sharpe Ratio",   f"{m['sharpe_ratio']:.3f}")
        mc3.metric("Max Drawdown",   f"{m['max_drawdown_pct']:.2f}%")
        mc4.metric("Win Rate",       f"{m['win_rate_pct']:.1f}%")
        mc5.metric("Closed Trades",  m["total_trades"])

    # Equity curve with trade markers
    if not eq_df.empty:
        fig = go.Figure()
        line_c = "#00c896" if m["total_return_pct"] >= 0 else "#ff4b4b"
        fill_c = "rgba(0,200,150,0.07)" if m["total_return_pct"] >= 0 else "rgba(255,75,75,0.07)"

        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["equity"],
            mode="lines", fill="tozeroy",
            fillcolor=fill_c, line=dict(color=line_c, width=1.6),
            name="Equity", hovertemplate="$%{y:,.2f}<extra></extra>",
        ))

        # Buy markers
        buys_df = pd.DataFrame([t for t in tlist if t["side"] == "buy"])
        if not buys_df.empty:
            buys_df["date"] = pd.to_datetime(buys_df["date"])
            merged = buys_df.merge(eq_df, on="date", how="left")
            fig.add_trace(go.Scatter(
                x=merged["date"], y=merged["equity"], mode="markers",
                marker=dict(symbol="triangle-up", size=11, color="#00c896",
                            line=dict(color="#00c896", width=1)),
                name="Buy", hovertemplate="%{x}<br>$%{y:,.0f}<extra>Buy</extra>",
            ))

        # Sell markers
        sells_df = pd.DataFrame([t for t in tlist if t["side"] == "sell"])
        if not sells_df.empty:
            sells_df["date"] = pd.to_datetime(sells_df["date"])
            merged = sells_df.merge(eq_df, on="date", how="left")
            fig.add_trace(go.Scatter(
                x=merged["date"], y=merged["equity"], mode="markers",
                marker=dict(symbol="triangle-down", size=11, color="#ff4b4b",
                            line=dict(color="#ff4b4b", width=1)),
                name="Sell", hovertemplate="%{x}<br>$%{y:,.0f}<extra>Sell</extra>",
            ))

        # Starting capital reference line
        fig.add_hline(y=m["starting_capital"], line=dict(color="#444", width=1, dash="dot"))

        fig.update_layout(**PLOTLY_BASE, height=300)
        fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

    # Trade log
    if tlist:
        tdf = pd.DataFrame(tlist)
        st.dataframe(
            tdf.style.map(_side_color, subset=["side"]),
            use_container_width=True, hide_index=True, height=220,
        )

st.divider()

# ── SAFETY EVENTS ─────────────────────────────────────────────────────────────

events = db.get_recent_safety_events(limit=20)
_label(f"Safety Events — {'none recorded' if not events else str(len(events)) + ' recorded'}")
if events:
    st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
else:
    st.success("✅ No safety events — all clear.")

st.divider()

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

with st.expander("⚙️  CONFIGURATION", expanded=False):
    st.caption("Changes apply on the bot's next cycle (within an hour).")

    # Kill switch (also accessible here)
    st.markdown("##### Master Kill Switch")
    enabled_cfg  = cfg.get("trading_enabled", "true").lower() == "true"
    new_en       = st.toggle("Trading enabled", value=enabled_cfg, key="cfg_toggle",
                              help="Turn OFF to halt trading on next cycle.")
    if new_en != enabled_cfg:
        db.set_config("trading_enabled", "true" if new_en else "false")
        st.rerun()

    st.divider()

    # Strategy
    st.markdown("##### Strategy")
    available       = list(STRATEGIES.keys())
    cur_strat       = cfg.get("active_strategy", "rsi")
    strat_idx       = available.index(cur_strat) if cur_strat in available else 0
    new_strategy    = st.selectbox("Active strategy", available, index=strat_idx, key="cfg_strat")

    STRATEGY_DESC = {
        "rsi":          "**RSI (상대강도지수):** RSI가 과매도 구간(기본값 30 이하)에 진입하면 매수, 과매수 구간(기본값 70 이상)에 진입하면 매도합니다. 횡보장에서 효과적입니다.",
        "macd":         "**MACD (이동평균 수렴·확산):** MACD 선이 시그널 선을 상향 돌파하면 매수, 하향 돌파하면 매도합니다. 추세가 뚜렷한 시장에서 효과적입니다.",
        "bollinger":    "**볼린저 밴드:** 가격이 하단 밴드 아래로 떨어지면 매수, 상단 위로 올라가면 매도합니다. 변동성이 높은 구간에서 효과적입니다.",
        "ema_crossover":"**EMA 크로스오버:** 단기 EMA가 장기 EMA를 상향 돌파하면 매수(골든크로스), 하향 돌파하면 매도(데드크로스)합니다.",
    }
    st.info(STRATEGY_DESC.get(new_strategy, ""))

    new_symbols = st.text_input("Symbols (comma-separated)", value=cfg.get("symbols",""),
                                 help="Example: AAPL,MSFT,GOOGL")

    st.markdown("##### Strategy Parameters")
    if new_strategy == "rsi":
        c1, c2, c3 = st.columns(3)
        with c1: new_period     = st.number_input("RSI 기간",        2,   50, value=int(cfg.get("rsi_period",    14)))
        with c2: new_oversold   = st.number_input("과매도 기준 (매수)", 10.0,50.0,value=float(cfg.get("rsi_oversold", 30)),step=1.0)
        with c3: new_overbought = st.number_input("과매수 기준 (매도)", 50.0,90.0,value=float(cfg.get("rsi_overbought",70)),step=1.0)
    elif new_strategy == "macd":
        c1, c2, c3 = st.columns(3)
        with c1: new_macd_fast   = st.number_input("단기 (Fast)",    2, 50, value=int(cfg.get("macd_fast",  12)))
        with c2: new_macd_slow   = st.number_input("장기 (Slow)",    5,100, value=int(cfg.get("macd_slow",  26)))
        with c3: new_macd_signal = st.number_input("시그널 (Signal)", 2, 50, value=int(cfg.get("macd_signal", 9)))
    elif new_strategy == "bollinger":
        c1, c2 = st.columns(2)
        with c1: new_bb_window = st.number_input("이동평균 기간", 5,100, value=int(cfg.get("bb_window",  20)))
        with c2: new_bb_std    = st.number_input("표준편차 배수",0.5,5.0,value=float(cfg.get("bb_std",   2.0)),step=0.5)
    elif new_strategy == "ema_crossover":
        c1, c2 = st.columns(2)
        with c1: new_ema_fast = st.number_input("단기 EMA",  2, 50, value=int(cfg.get("ema_fast",  9)))
        with c2: new_ema_slow = st.number_input("장기 EMA",  5,200, value=int(cfg.get("ema_slow", 21)))

    st.markdown("##### Risk Limits")
    c1, c2 = st.columns(2)
    with c1:
        new_pos_pct    = st.number_input("Position size (% equity)", 0.5, 25.0, value=float(cfg.get("position_pct",        5.0)),step=0.5)
        new_daily_loss = st.number_input("Daily loss limit (%)",     0.5, 20.0, value=float(cfg.get("daily_loss_limit_pct",2.0)),step=0.5)
    with c2:
        new_max_pos    = st.number_input("Max concurrent positions",    1,   20, value=int(cfg.get("max_positions",        4)))
        new_max_dd     = st.number_input("Max drawdown (%)",          1.0, 50.0, value=float(cfg.get("max_drawdown_pct",  10.0)),step=1.0)

    new_max_tpm  = st.number_input("Max trades per minute", 1,  50, value=int(cfg.get("max_trades_per_minute", 5)))
    new_slip     = st.number_input("Slippage (basis pts)",  0, 100, value=int(cfg.get("slippage_bps",          5)))

    if st.button("💾  SAVE CONFIGURATION", type="primary", use_container_width=True):
        db.set_config("active_strategy", new_strategy)
        db.set_config("symbols",         new_symbols)
        if new_strategy == "rsi":
            db.set_config("rsi_period",     str(new_period))
            db.set_config("rsi_oversold",   str(new_oversold))
            db.set_config("rsi_overbought", str(new_overbought))
        elif new_strategy == "macd":
            db.set_config("macd_fast",   str(new_macd_fast))
            db.set_config("macd_slow",   str(new_macd_slow))
            db.set_config("macd_signal", str(new_macd_signal))
        elif new_strategy == "bollinger":
            db.set_config("bb_window", str(new_bb_window))
            db.set_config("bb_std",    str(new_bb_std))
        elif new_strategy == "ema_crossover":
            db.set_config("ema_fast", str(new_ema_fast))
            db.set_config("ema_slow", str(new_ema_slow))
        db.set_config("position_pct",          str(new_pos_pct))
        db.set_config("max_positions",         str(new_max_pos))
        db.set_config("daily_loss_limit_pct",  str(new_daily_loss))
        db.set_config("max_drawdown_pct",      str(new_max_dd))
        db.set_config("max_trades_per_minute", str(new_max_tpm))
        db.set_config("slippage_bps",          str(new_slip))
        st.success("✅ 저장 완료. 봇이 다음 사이클에서 변경 사항을 반영합니다.")
        st.cache_data.clear()
        st.rerun()
