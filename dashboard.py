"""
Streamlit dashboard for the trading bot.
- Reads bot state from SQLite
- Reads account state from Alpaca (paper)
- Allows editing config (which bot.py picks up on its next cycle)
- Never places trades
"""

from datetime import datetime, timedelta

import bcrypt
import pandas as pd
import streamlit as st

import broker
import db
from strategies import STRATEGIES

db.init_db()

st.set_page_config(
    page_title="Trading Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Auth ─────────────────────────────────────────────────────────────────────

def _check_login() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.markdown("""
    <div style="max-width:380px;margin:10vh auto;padding:2rem;
                background:#161b27;border:1px solid #2a3350;border-radius:14px;">
        <h2 style="margin:0 0 1.5rem;text-align:center;">📈 Trading Bot</h2>
    </div>
    """, unsafe_allow_html=True)
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)
    if submitted:
        valid_user = username == st.secrets["auth"]["username"]
        valid_pass = bcrypt.checkpw(
            password.encode(),
            st.secrets["auth"]["hashed_password"].encode(),
        )
        if valid_user and valid_pass:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid username or password.")
    return False


if not _check_login():
    st.stop()

# ── CSS ──────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Layout */
.block-container { padding-top: 1.25rem !important; padding-bottom: 1rem !important; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b27;
    border: 1px solid #2a3350;
    border-radius: 10px;
    padding: 1rem 1.25rem !important;
}
[data-testid="stMetricValue"]  { font-size: 1.45rem !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"]  { font-size: 0.78rem !important; color: #8fa8c8 !important; }
[data-testid="stMetricDelta"]  { font-size: 0.82rem !important; }

/* Sidebar */
[data-testid="stSidebar"] > div:first-child { background: #0d111c; }

/* Tabs */
[data-testid="stTabs"] [role="tab"]                        { font-weight: 600; font-size: 0.88rem; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"]  { color: #00d4aa !important; }

/* Divider */
hr { border-color: #2a3350 !important; }

/* Mobile: wrap 4 metric columns into 2×2 grid */
@media (max-width: 640px) {
    [data-testid="column"]          { min-width: 46% !important; flex: 1 1 46% !important; }
    [data-testid="metric-container"] { padding: 0.65rem !important; }
    [data-testid="stMetricValue"]   { font-size: 1.1rem !important; }
    .block-container                { padding: 0.6rem !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🤖 Bot Status")
    hb = db.get_heartbeat()
    if hb:
        last_beat = datetime.fromisoformat(hb["last_beat"])
        age = datetime.utcnow() - last_beat
        age_min = int(age.total_seconds() / 60)
        if age < timedelta(minutes=70):
            st.success(f"● Alive — {age_min}m ago")
        else:
            st.error(f"● Stale — last seen {age_min}m ago")
        st.caption(f"Status: {hb['status']}")
    else:
        st.warning("⏳ Bot has not run yet")

    st.divider()

    st.markdown("### 📡 API Usage")
    api_count = db.count_recent_api_calls(60)
    st.progress(min(api_count / 200, 1.0))
    if api_count < 100:
        st.success(f"{api_count} / 200 per min")
    elif api_count < 180:
        st.warning(f"{api_count} / 200 per min")
    else:
        st.error(f"{api_count} / 200 per min ⚠️")

    st.divider()

    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 📈 Trading Bot Dashboard")
st.caption(f"Paper trading · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
st.divider()

# ── Account metrics ───────────────────────────────────────────────────────────

try:
    account = broker.get_account()
    equity       = float(account.equity)
    cash         = float(account.cash)
    buying_power = float(account.buying_power)
    last_equity  = float(account.last_equity)
    pnl          = equity - last_equity
    pnl_pct      = (pnl / last_equity * 100) if last_equity else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Equity",        f"${equity:,.2f}")
    c2.metric("💵 Cash",          f"${cash:,.2f}")
    c3.metric("⚡ Buying Power",  f"${buying_power:,.2f}")
    c4.metric("📊 Today P&L",     f"${pnl:,.2f}", delta=f"{pnl_pct:+.2f}%")
except Exception as e:
    st.error(f"Failed to load account: {e}")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_pos, tab_trades, tab_logs, tab_safety, tab_config = st.tabs([
    "📊 Positions", "💱 Trades", "📋 Logs", "🚨 Safety", "⚙️ Config",
])

# helper: color a numeric column green/red
def _color_num(val):
    try:
        n = float(str(val).replace("$", "").replace(",", "").replace("%", "").replace("+", ""))
        if n > 0: return "color: #00c896"
        if n < 0: return "color: #ff4b4b"
    except (ValueError, TypeError):
        pass
    return ""


with tab_pos:
    st.subheader("Open Positions")
    st.caption("Live from Alpaca")
    try:
        positions = broker.get_all_positions()
        if positions:
            rows = [{
                "Symbol":       p.symbol,
                "Qty":          float(p.qty),
                "Avg Entry":    float(p.avg_entry_price),
                "Current":      float(p.current_price),
                "Mkt Value":    float(p.market_value),
                "P&L ($)":      float(p.unrealized_pl),
                "P&L (%)":      float(p.unrealized_plpc) * 100,
            } for p in positions]
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style
                  .format({
                      "Avg Entry": "${:.2f}", "Current":  "${:.2f}",
                      "Mkt Value": "${:,.2f}",
                      "P&L ($)":   "${:+,.2f}", "P&L (%)": "{:+.2f}%",
                  })
                  .map(_color_num, subset=["P&L ($)", "P&L (%)"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No open positions")
    except Exception as e:
        st.error(f"Failed to load positions: {e}")


with tab_trades:
    st.subheader("Recent Trades")
    trades = db.get_recent_trades(limit=100)
    if trades:
        df = pd.DataFrame(trades)
        df["slippage"] = df["simulated_price"] - df["actual_price"]

        buys  = int((df["side"] == "buy").sum())
        sells = int((df["side"] == "sell").sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Trades", len(df))
        c2.metric("Buys",  buys)
        c3.metric("Sells", sells)

        st.divider()

        cols = ["timestamp", "symbol", "side", "quantity",
                "actual_price", "simulated_price", "slippage", "strategy", "notes"]
        df = df[[c for c in cols if c in df.columns]]

        def _side_color(val):
            if val == "buy":  return "color: #00c896; font-weight:600"
            if val == "sell": return "color: #ff4b4b; font-weight:600"
            return ""

        st.dataframe(
            df.style.map(_side_color, subset=["side"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No trades yet")


with tab_logs:
    st.subheader("Bot Logs")
    level_filter = st.multiselect(
        "Filter by level",
        options=["INFO", "WARN", "ERROR"],
        default=["INFO", "WARN", "ERROR"],
    )
    logs = db.get_recent_logs(limit=200)
    if logs:
        df = pd.DataFrame(logs)
        df = df[df["level"].isin(level_filter)][["timestamp", "level", "message"]]

        _LEVEL_STYLE = {
            "ERROR": "color:#ff4b4b;font-weight:700",
            "WARN":  "color:#ffa500;font-weight:600",
            "INFO":  "color:#8fa8c8",
        }
        st.dataframe(
            df.style.map(lambda v: _LEVEL_STYLE.get(v, ""), subset=["level"]),
            use_container_width=True,
            hide_index=True,
            height=440,
        )
    else:
        st.info("No logs yet")


with tab_safety:
    st.subheader("Safety Events")
    st.caption("Auto-triggered kill switches stay off until manually re-enabled in Config.")
    events = db.get_recent_safety_events(limit=50)
    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
    else:
        st.success("✅ No safety events — all clear.")


with tab_config:
    st.subheader("Configuration")
    st.caption("Changes apply on the bot's next cycle (within an hour).")

    cfg = db.get_all_config()

    # ── Kill switch ──
    st.markdown("### 🛑 Master Kill Switch")
    enabled = cfg.get("trading_enabled", "true").lower() == "true"
    new_enabled = st.toggle("Trading enabled", value=enabled,
                             help="Turn OFF to halt all trading on next cycle.")
    if new_enabled != enabled:
        db.set_config("trading_enabled", "true" if new_enabled else "false")
        st.success(f"Trading {'enabled ✅' if new_enabled else 'disabled 🛑'}")
        st.rerun()

    st.divider()

    # ── Strategy ──
    st.markdown("### 📊 Strategy")
    available = list(STRATEGIES.keys())
    current_strategy = cfg.get("active_strategy", "rsi")
    strategy_idx = available.index(current_strategy) if current_strategy in available else 0
    new_strategy = st.selectbox("Active strategy", available, index=strategy_idx)

    STRATEGY_DESCRIPTIONS = {
        "rsi":          "**RSI (상대강도지수):** RSI가 과매도 구간(기본값 30 이하)에 진입하면 매수, 과매수 구간(기본값 70 이상)에 진입하면 매도합니다. 단기 평균 회귀를 노리는 전략으로, 횡보장에서 효과적입니다.",
        "macd":         "**MACD (이동평균 수렴·확산):** MACD 선이 시그널 선을 상향 돌파하면 매수, 하향 돌파하면 매도합니다. 추세 전환 시점을 포착하는 전략으로, 트렌드가 뚜렷한 시장에서 효과적입니다.",
        "bollinger":    "**볼린저 밴드:** 가격이 볼린저 밴드 하단 아래로 떨어지면 매수, 상단 위로 올라가면 매도합니다. 가격이 평균으로 회귀하는 성질을 이용하며, 변동성이 높은 구간에서 효과적입니다.",
        "ema_crossover":"**EMA 크로스오버:** 단기 지수이동평균(EMA)이 장기 EMA를 상향 돌파하면 매수(골든크로스), 하향 돌파하면 매도(데드크로스)합니다. 중장기 추세를 추종하는 전략입니다.",
    }
    st.info(STRATEGY_DESCRIPTIONS.get(new_strategy, ""))

    new_symbols = st.text_input(
        "Symbols (comma-separated)",
        value=cfg.get("symbols", ""),
        help="Example: AAPL,MSFT,GOOGL",
    )

    st.divider()

    if new_strategy == "rsi":
        st.markdown("### 🎯 RSI 파라미터")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_period    = st.number_input("RSI 기간",       2,    50, value=int(cfg.get("rsi_period",    14)))
        with col2:
            new_oversold  = st.number_input("과매도 기준 (매수)", 10.0, 50.0, value=float(cfg.get("rsi_oversold",  30)), step=1.0)
        with col3:
            new_overbought = st.number_input("과매수 기준 (매도)", 50.0, 90.0, value=float(cfg.get("rsi_overbought", 70)), step=1.0)

    elif new_strategy == "macd":
        st.markdown("### 🎯 MACD 파라미터")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_macd_fast   = st.number_input("단기 기간 (Fast)",   2,  50, value=int(cfg.get("macd_fast",   12)))
        with col2:
            new_macd_slow   = st.number_input("장기 기간 (Slow)",   5, 100, value=int(cfg.get("macd_slow",   26)))
        with col3:
            new_macd_signal = st.number_input("시그널 기간 (Signal)", 2, 50, value=int(cfg.get("macd_signal",  9)))

    elif new_strategy == "bollinger":
        st.markdown("### 🎯 볼린저 밴드 파라미터")
        col1, col2 = st.columns(2)
        with col1:
            new_bb_window = st.number_input("이동평균 기간",  5, 100, value=int(cfg.get("bb_window",  20)))
        with col2:
            new_bb_std    = st.number_input("표준편차 배수", 0.5, 5.0, value=float(cfg.get("bb_std", 2.0)), step=0.5)

    elif new_strategy == "ema_crossover":
        st.markdown("### 🎯 EMA 크로스오버 파라미터")
        col1, col2 = st.columns(2)
        with col1:
            new_ema_fast = st.number_input("단기 EMA 기간",  2,  50, value=int(cfg.get("ema_fast",  9)))
        with col2:
            new_ema_slow = st.number_input("장기 EMA 기간",  5, 200, value=int(cfg.get("ema_slow", 21)))

    st.divider()

    # ── Risk limits ──
    st.markdown("### 🛡️ Risk Limits")
    col1, col2 = st.columns(2)
    with col1:
        new_pos_pct    = st.number_input("Position size (% of equity)", 0.5, 25.0,
                                          value=float(cfg.get("position_pct", 5.0)), step=0.5)
        new_daily_loss = st.number_input("Daily loss limit (%)", 0.5, 20.0,
                                          value=float(cfg.get("daily_loss_limit_pct", 2.0)), step=0.5)
    with col2:
        new_max_positions = st.number_input("Max concurrent positions", 1, 20,
                                             value=int(cfg.get("max_positions", 4)))
        new_max_dd        = st.number_input("Max drawdown (%)", 1.0, 50.0,
                                             value=float(cfg.get("max_drawdown_pct", 10.0)), step=1.0)

    new_max_per_min = st.number_input("Max trades per minute (runaway detection)", 1, 50,
                                       value=int(cfg.get("max_trades_per_minute", 5)))
    new_slippage    = st.number_input("Slippage (basis points, 5 = 0.05%)", 0, 100,
                                       value=int(cfg.get("slippage_bps", 5)))

    if st.button("💾 저장", type="primary", use_container_width=True):
        db.set_config("active_strategy", new_strategy)
        db.set_config("symbols",         new_symbols)
        if new_strategy == "rsi":
            db.set_config("rsi_period",    str(new_period))
            db.set_config("rsi_oversold",  str(new_oversold))
            db.set_config("rsi_overbought",str(new_overbought))
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
        db.set_config("max_positions",         str(new_max_positions))
        db.set_config("daily_loss_limit_pct",  str(new_daily_loss))
        db.set_config("max_drawdown_pct",      str(new_max_dd))
        db.set_config("max_trades_per_minute", str(new_max_per_min))
        db.set_config("slippage_bps",          str(new_slippage))
        st.success("✅ 저장 완료. 봇이 다음 사이클에서 변경 사항을 반영합니다.")
