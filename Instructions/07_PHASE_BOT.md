# Phase 7 — Main Bot (`bot.py`)

> **Prerequisite**: Phases 1–6 complete.

## Goal
Main loop that ties everything together. Orchestration only — no business logic in this file beyond the loop.

## Tasks

### 1. Implement `bot.py`

Required behavior:
- Load `.env`, init DB, send startup alert
- Run forever (`while True`)
- Each cycle: heartbeat → safety checks → for each symbol → signal → maybe trade → sleep
- Catch all exceptions per-cycle (don't crash the loop)

### 2. Implementation outline

```python
"""
Main trading bot loop. Runs forever, executes trading strategy on schedule.
Paper trading only — real money is impossible by design (paper=True hardcoded in broker.py).
"""
import time
import traceback
from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

import broker
import config
import db
import notifications
import safety
from strategies import STRATEGIES


def get_recent_prices(symbol: str, days: int) -> pd.Series:
    """Fetch recent daily close prices for a symbol."""
    end = datetime.utcnow()
    start = end - timedelta(days=days + 5)  # buffer for weekends
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = broker.get_stock_bars(request)
    if symbol not in bars.data:
        return pd.Series(dtype=float)
    closes = [bar.close for bar in bars.data[symbol]]
    return pd.Series(closes)


def calculate_quantity(equity: float, price: float, position_pct: float) -> int:
    """Position sizing: integer shares fitting within position_pct of equity."""
    target_value = equity * (position_pct / 100.0)
    return max(int(target_value / price), 0)


def place_buy(symbol: str, current_price: float, settings: dict, account):
    """Submit buy order with slippage simulation. All side effects logged."""
    pos_pct = float(settings["position_pct"])
    qty = calculate_quantity(float(account.equity), current_price, pos_pct)
    if qty < 1:
        db.log("WARN", f"{symbol}: calculated qty=0, skipping buy")
        return

    slippage_bps = int(settings.get("slippage_bps", "5"))
    simulated_price = broker.apply_slippage(current_price, "buy", slippage_bps)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        db.log_trade(
            symbol=symbol, side="buy", quantity=qty,
            actual_price=current_price, simulated_price=simulated_price,
            order_id=str(order.id), strategy=settings.get("active_strategy", "rsi"),
            notes="signal: buy",
        )
        msg = f"BUY {qty} {symbol} @ ${current_price:.2f} (sim: ${simulated_price:.2f})"
        db.log("INFO", msg)
        notifications.send_alert(msg, "trade")
    except Exception as e:
        db.log("ERROR", f"BUY {symbol} failed: {e}")
        notifications.send_alert(f"BUY {symbol} failed: {e}", "error")


def place_sell(symbol: str, position, current_price: float, settings: dict):
    """Submit sell-all order with slippage simulation."""
    qty = float(position.qty)
    slippage_bps = int(settings.get("slippage_bps", "5"))
    simulated_price = broker.apply_slippage(current_price, "sell", slippage_bps)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        ))
        db.log_trade(
            symbol=symbol, side="sell", quantity=qty,
            actual_price=current_price, simulated_price=simulated_price,
            order_id=str(order.id), strategy=settings.get("active_strategy", "rsi"),
            notes="signal: sell",
        )
        msg = f"SELL {qty} {symbol} @ ${current_price:.2f} (sim: ${simulated_price:.2f})"
        db.log("INFO", msg)
        notifications.send_alert(msg, "trade")
    except Exception as e:
        db.log("ERROR", f"SELL {symbol} failed: {e}")
        notifications.send_alert(f"SELL {symbol} failed: {e}", "error")


def process_symbol(symbol: str, settings: dict, account):
    """Run strategy on one symbol and act on signal."""
    strategy_name = settings.get("active_strategy", "rsi")
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        db.log("ERROR", f"Unknown strategy: {strategy_name}")
        return

    lookback = strategy.required_lookback_days(settings)
    prices = get_recent_prices(symbol, lookback)
    if len(prices) < lookback - 5:  # tolerate small gaps (holidays)
        db.log("WARN", f"{symbol}: insufficient price data ({len(prices)} bars)")
        return

    current_price = float(prices.iloc[-1])
    sig = strategy.signal(prices, settings)
    db.log("INFO", f"{symbol}: price=${current_price:.2f}, signal={sig}")

    position = broker.get_open_position(symbol)
    has_position = position is not None

    if sig == "buy" and not has_position:
        place_buy(symbol, current_price, settings, account)
    elif sig == "sell" and has_position:
        place_sell(symbol, position, current_price, settings)


def run_one_cycle():
    """One full pass through all symbols."""
    settings = db.get_all_config()

    # Get account & recent trades for safety checks
    account = broker.get_account()
    recent_trades = db.get_recent_trades(limit=20)

    # Run all safety checks
    ok, reason = safety.check_can_trade(account, recent_trades)
    if not ok:
        db.log("WARN", f"Safety stop: {reason}")
        return

    # Check market clock
    clock = broker.get_clock()
    if not clock.is_open:
        db.log("INFO", f"Market closed. Next open: {clock.next_open}")
        return

    # Check rate limit
    if broker.is_rate_limited():
        db.log("WARN", f"Near API rate limit, sleeping {config.RATE_LIMIT_SLEEP_SECONDS}s")
        time.sleep(config.RATE_LIMIT_SLEEP_SECONDS)
        return

    # Process each symbol
    symbols = [s.strip() for s in settings["symbols"].split(",") if s.strip()]
    db.log("INFO", f"Cycle start. Strategy={settings.get('active_strategy')}, symbols={symbols}")
    for symbol in symbols:
        try:
            process_symbol(symbol, settings, account)
        except Exception as e:
            db.log("ERROR", f"{symbol} processing failed: {e}\n{traceback.format_exc()}")
    db.log("INFO", "Cycle complete.")


def main():
    db.init_db()
    db.log("INFO", "=== Bot starting (PAPER TRADING) ===")
    notifications.send_startup()

    while True:
        try:
            db.update_heartbeat("alive")
            run_one_cycle()
        except Exception as e:
            tb = traceback.format_exc()
            db.log("ERROR", f"Cycle failed: {e}\n{tb}")
            db.update_heartbeat("error")
            notifications.send_alert(f"Cycle exception: {e}", "error")

        db.log("INFO", f"Sleeping {config.LOOP_INTERVAL_SECONDS}s...")
        time.sleep(config.LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

### 3. Pattern reference
- See `PATTERNS.md > Trade Execution` for the canonical buy/sell flow.
- See `PATTERNS.md > Error Handling` for the per-cycle exception pattern.

---

## Verification

```bash
# 1. Bot starts cleanly with valid .env
uv run python bot.py
# Expected: logs "=== Bot starting (PAPER TRADING) ===" and proceeds.
# Either logs "Market closed" or runs through symbols.
# Press Ctrl+C after one cycle to stop.

# 2. Heartbeat updated
uv run python -c "
import db
print(db.get_heartbeat())
"
# Expected: dict with last_beat within last few minutes, status='alive'

# 3. Logs present
uv run python -c "
import db
for log in db.get_recent_logs(10):
    print(log['level'], log['message'])
"
# Expected: shows recent log entries

# 4. Kill switch respected mid-run
# Terminal 1: uv run python bot.py (let it run)
# Terminal 2:
uv run python -c "import db; db.set_config('trading_enabled', 'false')"
# Terminal 1: next cycle should log 'Safety stop: Trading disabled by kill switch'

# 5. Missing env vars cause clean exit (not crash)
uv run python -c "
import os
os.environ.pop('ALPACA_API_KEY', None)
os.environ.pop('ALPACA_SECRET_KEY', None)
import broker
"
# Expected: SystemExit with helpful message, no traceback dump
```

If all 5 checks pass, Phase 7 is complete. Proceed to `08_PHASE_DASHBOARD.md`.
