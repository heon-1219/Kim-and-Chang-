"""
Streamlit dashboard for the trading bot.
- Reads bot state from SQLite
- Reads account state from Alpaca (paper)
- Allows editing config (which bot.py picks up on its next cycle)
- Never places trades
"""

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import broker
import db
from strategies import STRATEGIES

db.init_db()  # safe to call repeatedly

st.set_page_config(page_title="Trading Bot", page_icon="🤖", layout="wide")
st.title("🤖 Trading Bot Dashboard")
st.caption("Paper trading mode — no real money involved")


# === Sidebar: bot status ===
with st.sidebar:
    st.header("Bot status")
    hb = db.get_heartbeat()
    if hb:
        last_beat = datetime.fromisoformat(hb["last_beat"])
        age = datetime.utcnow() - last_beat
        if age < timedelta(minutes=70):
            st.success(f"✅ Alive ({int(age.total_seconds() / 60)} min ago)")
        else:
            st.error(f"❌ Stale ({age})")
        st.caption(f"Status: {hb['status']}")
    else:
        st.warning("⏳ Bot has not run yet")

    st.divider()
    st.header("API usage")
    api_count = db.count_recent_api_calls(60)
    if api_count < 100:
        st.success(f"{api_count} / 200 per min")
    elif api_count < 180:
        st.warning(f"{api_count} / 200 per min")
    else:
        st.error(f"{api_count} / 200 per min ⚠️")

    st.divider()
    if st.button("🔄 Refresh"):
        st.rerun()


# === Top: account metrics ===
try:
    account = broker.get_account()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Equity", f"${float(account.equity):,.2f}")
    col2.metric("Cash", f"${float(account.cash):,.2f}")
    col3.metric("Buying Power", f"${float(account.buying_power):,.2f}")
    pnl = float(account.equity) - float(account.last_equity)
    col4.metric("Today P&L", f"${pnl:,.2f}", delta=f"{pnl:+.2f}")
except Exception as e:
    st.error(f"Failed to load account: {e}")
    account = None


# === Tabs ===
tab_pos, tab_trades, tab_logs, tab_safety, tab_config = st.tabs(
    ["📊 Positions", "💱 Trades", "📋 Logs", "🚨 Safety", "⚙️ Config"]
)


with tab_pos:
    st.subheader("Open positions (live from Alpaca)")
    try:
        positions = broker.get_all_positions()
        if positions:
            rows = [{
                "Symbol": p.symbol,
                "Qty": float(p.qty),
                "Avg Entry": f"${float(p.avg_entry_price):.2f}",
                "Current": f"${float(p.current_price):.2f}",
                "Market Value": f"${float(p.market_value):.2f}",
                "P&L": f"${float(p.unrealized_pl):.2f}",
                "P&L %": f"{float(p.unrealized_plpc) * 100:.2f}%",
            } for p in positions]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No open positions")
    except Exception as e:
        st.error(f"Failed to load positions: {e}")


with tab_trades:
    st.subheader("Recent trades (from DB)")
    trades = db.get_recent_trades(limit=100)
    if trades:
        df = pd.DataFrame(trades)
        df["slippage"] = df["simulated_price"] - df["actual_price"]
        cols = ["timestamp", "symbol", "side", "quantity",
                "actual_price", "simulated_price", "slippage", "strategy", "notes"]
        df = df[[c for c in cols if c in df.columns]]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No trades yet")


with tab_logs:
    st.subheader("Recent bot logs")
    level_filter = st.multiselect(
        "Filter by level",
        options=["INFO", "WARN", "ERROR"],
        default=["INFO", "WARN", "ERROR"],
    )
    logs = db.get_recent_logs(limit=200)
    if logs:
        df = pd.DataFrame(logs)
        df = df[df["level"].isin(level_filter)]
        df = df[["timestamp", "level", "message"]]
        st.dataframe(df, use_container_width=True, hide_index=True, height=400)
    else:
        st.info("No logs yet")


with tab_safety:
    st.subheader("Safety events")
    st.caption("Auto-triggered kill switches stay off until manually re-enabled in Config.")
    events = db.get_recent_safety_events(limit=50)
    if events:
        df = pd.DataFrame(events)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No safety events recorded — that's good!")


with tab_config:
    st.subheader("⚙️ Configuration")
    st.caption("Changes apply on the bot's next cycle (within an hour).")

    cfg = db.get_all_config()

    st.markdown("### 🛑 Master kill switch")
    enabled = cfg.get("trading_enabled", "true").lower() == "true"
    new_enabled = st.toggle("Trading enabled", value=enabled,
                             help="Turn OFF to immediately halt all trading on next cycle.")
    if new_enabled != enabled:
        db.set_config("trading_enabled", "true" if new_enabled else "false")
        st.success(f"Trading {'enabled' if new_enabled else 'disabled'}")
        st.rerun()

    st.divider()

    st.markdown("### 📊 Strategy")
    available = list(STRATEGIES.keys())
    current_strategy = cfg.get("active_strategy", "rsi")
    strategy_idx = available.index(current_strategy) if current_strategy in available else 0
    new_strategy = st.selectbox("Active strategy", available, index=strategy_idx)

    new_symbols = st.text_input(
        "Symbols (comma-separated)",
        value=cfg.get("symbols", ""),
        help="Example: AAPL,MSFT,GOOGL",
    )

    st.divider()

    st.markdown("### 🎯 RSI parameters")
    col1, col2, col3 = st.columns(3)
    with col1:
        new_period = st.number_input("RSI period", 2, 50,
                                      value=int(cfg.get("rsi_period", 14)))
    with col2:
        new_oversold = st.number_input("Oversold (buy)", 10.0, 50.0,
                                        value=float(cfg.get("rsi_oversold", 30)), step=1.0)
    with col3:
        new_overbought = st.number_input("Overbought (sell)", 50.0, 90.0,
                                          value=float(cfg.get("rsi_overbought", 70)), step=1.0)

    st.divider()

    st.markdown("### 🛡️ Risk limits")
    col1, col2 = st.columns(2)
    with col1:
        new_pos_pct = st.number_input("Position size (% of equity)", 0.5, 25.0,
                                       value=float(cfg.get("position_pct", 5.0)), step=0.5)
        new_daily_loss = st.number_input("Daily loss limit (%)", 0.5, 20.0,
                                          value=float(cfg.get("daily_loss_limit_pct", 2.0)), step=0.5)
    with col2:
        new_max_positions = st.number_input("Max concurrent positions", 1, 20,
                                             value=int(cfg.get("max_positions", 4)))
        new_max_dd = st.number_input("Max drawdown (%)", 1.0, 50.0,
                                      value=float(cfg.get("max_drawdown_pct", 10.0)), step=1.0)

    new_max_per_min = st.number_input("Max trades per minute (runaway detection)", 1, 50,
                                       value=int(cfg.get("max_trades_per_minute", 5)))
    new_slippage = st.number_input("Slippage (basis points, 5 = 0.05%)", 0, 100,
                                    value=int(cfg.get("slippage_bps", 5)))

    if st.button("💾 Save settings", type="primary"):
        db.set_config("active_strategy", new_strategy)
        db.set_config("symbols", new_symbols)
        db.set_config("rsi_period", str(new_period))
        db.set_config("rsi_oversold", str(new_oversold))
        db.set_config("rsi_overbought", str(new_overbought))
        db.set_config("position_pct", str(new_pos_pct))
        db.set_config("max_positions", str(new_max_positions))
        db.set_config("daily_loss_limit_pct", str(new_daily_loss))
        db.set_config("max_drawdown_pct", str(new_max_dd))
        db.set_config("max_trades_per_minute", str(new_max_per_min))
        db.set_config("slippage_bps", str(new_slippage))
        st.success("✅ Saved. Bot will pick up changes on next cycle.")
