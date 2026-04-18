"""
Main trading bot loop. Runs all enabled strategies in parallel (sequentially within one cycle).
Paper trading only — real money is impossible by design (paper=True hardcoded in broker.py).
"""

from __future__ import annotations

import json
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
    end   = datetime.utcnow()
    start = end - timedelta(days=days + 5)  # buffer for weekends/holidays
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = broker.get_stock_bars(request)
    if symbol not in bars.data:
        return pd.Series(dtype=float)
    return pd.Series([bar.close for bar in bars.data[symbol]])


def calculate_quantity(equity: float, price: float, position_pct: float) -> int:
    """Integer shares that fit within position_pct of the given equity slice."""
    return max(int(equity * (position_pct / 100.0) / price), 0)


def place_buy(symbol: str, current_price: float, settings: dict,
              strategy_name: str, alloc_pct: float, account) -> None:
    """Submit a buy sized to this strategy's allocated capital fraction."""
    pos_pct          = float(settings["position_pct"])
    allocated_equity = float(account.equity) * (alloc_pct / 100.0)
    qty              = calculate_quantity(allocated_equity, current_price, pos_pct)
    if qty < 1:
        db.log("WARN", f"[{strategy_name.upper()}] {symbol}: qty=0, skipping buy")
        return

    slippage_bps    = int(settings.get("slippage_bps", "5"))
    simulated_price = broker.apply_slippage(current_price, "buy", slippage_bps)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        ))
        db.log_trade(
            symbol=symbol, side="buy", quantity=qty,
            actual_price=current_price, simulated_price=simulated_price,
            order_id=str(order.id), strategy=strategy_name, notes="signal: buy",
        )
        msg = f"[{strategy_name.upper()}] BUY {qty} {symbol} @ ${current_price:.2f} (sim ${simulated_price:.2f})"
        db.log("INFO", msg)
        notifications.send_alert(msg, "trade")
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] BUY {symbol} failed: {e}")
        notifications.send_alert(f"BUY {symbol} failed: {e}", "error")


def place_sell(symbol: str, held_qty: float, current_price: float,
               settings: dict, strategy_name: str) -> None:
    """Sell exactly the qty this strategy holds, capped by actual Alpaca position."""
    actual_pos = broker.get_open_position(symbol)
    if actual_pos is None:
        db.log("WARN", f"[{strategy_name.upper()}] {symbol}: position gone before sell")
        return
    # Cap against real position to handle any manual sells that reduced it
    qty = min(held_qty, float(actual_pos.qty))
    if qty < 1:
        db.log("WARN", f"[{strategy_name.upper()}] {symbol}: effective qty<1, skipping sell")
        return

    slippage_bps    = int(settings.get("slippage_bps", "5"))
    simulated_price = broker.apply_slippage(current_price, "sell", slippage_bps)

    try:
        order = broker.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        ))
        db.log_trade(
            symbol=symbol, side="sell", quantity=qty,
            actual_price=current_price, simulated_price=simulated_price,
            order_id=str(order.id), strategy=strategy_name, notes="signal: sell",
        )
        msg = f"[{strategy_name.upper()}] SELL {qty} {symbol} @ ${current_price:.2f} (sim ${simulated_price:.2f})"
        db.log("INFO", msg)
        notifications.send_alert(msg, "trade")
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] SELL {symbol} failed: {e}")
        notifications.send_alert(f"SELL {symbol} failed: {e}", "error")


def process_symbol(symbol: str, settings: dict,
                   strategy_name: str, alloc_pct: float, account) -> None:
    """Run one strategy on one symbol and act on its signal."""
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        db.log("ERROR", f"Unknown strategy: {strategy_name}")
        return

    lookback = strategy.required_lookback_days(settings)
    prices   = get_recent_prices(symbol, lookback)
    if len(prices) < lookback - 5:
        db.log("WARN", f"{strategy_name}/{symbol}: only {len(prices)} bars, need ~{lookback}")
        return

    current_price = float(prices.iloc[-1])
    sig           = strategy.signal(prices, settings)
    db.log("INFO", f"{strategy_name}/{symbol}: ${current_price:.2f} → {sig}")

    # Per-strategy position tracking via DB — each strategy owns only what it bought
    held_qty     = db.get_strategy_holding(symbol, strategy_name)
    has_position = held_qty > 0

    if sig == "buy" and not has_position:
        place_buy(symbol, current_price, settings, strategy_name, alloc_pct, account)
    elif sig == "sell" and has_position:
        place_sell(symbol, held_qty, current_price, settings, strategy_name)


def _load_active_strategies(settings: dict, account_equity: float) -> list[tuple[str, float]]:
    """Return [(strategy_name, alloc_pct), ...] from strategy_allocation config.

    Supports both alloc_usd (new, dashboard converts to pct using live equity)
    and legacy alloc_pct. Falls back to (active_strategy, 100%) if unconfigured.
    """
    try:
        alloc: dict = json.loads(settings.get("strategy_allocation", "{}"))
    except (json.JSONDecodeError, TypeError):
        alloc = {}

    result = []
    for k, v in alloc.items():
        if not v.get("enabled") or k not in STRATEGIES:
            continue
        if "alloc_usd" in v:
            usd = float(v.get("alloc_usd", 0))
            if usd > 0 and account_equity > 0:
                result.append((k, (usd / account_equity) * 100))
        elif "alloc_pct" in v:  # legacy fallback
            pct = float(v.get("alloc_pct", 0))
            if pct > 0:
                result.append((k, pct))

    if result:
        return result

    fallback = settings.get("active_strategy", "rsi")
    if fallback in STRATEGIES:
        return [(fallback, 100.0)]
    return []


def run_one_cycle() -> None:
    """Run every enabled strategy across all configured symbols."""
    settings      = db.get_all_config()
    account       = broker.get_account()
    recent_trades = db.get_recent_trades(limit=20)

    ok, reason = safety.check_can_trade(account, recent_trades)
    if not ok:
        db.log("WARN", f"Safety stop: {reason}")
        return

    clock = broker.get_clock()
    if not clock.is_open:
        db.log("INFO", f"Market closed. Next open: {clock.next_open}")
        return

    if broker.is_rate_limited():
        db.log("WARN", f"Near API rate limit, sleeping {config.RATE_LIMIT_SLEEP_SECONDS}s")
        time.sleep(config.RATE_LIMIT_SLEEP_SECONDS)
        return

    active_strategies = _load_active_strategies(settings, float(account.equity))
    if not active_strategies:
        db.log("WARN", "No active strategies configured — nothing to do.")
        return

    symbols     = [s.strip() for s in settings["symbols"].split(",") if s.strip()]
    total_alloc = sum(p for _, p in active_strategies)
    db.log("INFO",
           f"Cycle start. strategies={[n for n, _ in active_strategies]}, "
           f"alloc_total={total_alloc:.0f}%, symbols={symbols}")

    for strategy_name, alloc_pct in active_strategies:
        db.log("INFO", f"--- {strategy_name.upper()} ({alloc_pct:.0f}% of equity) ---")
        for symbol in symbols:
            try:
                process_symbol(symbol, settings, strategy_name, alloc_pct, account)
            except Exception as e:
                db.log("ERROR", f"{strategy_name}/{symbol}: {e}\n{traceback.format_exc()}")

    db.log("INFO", "Cycle complete.")


def main() -> None:
    db.init_db()
    db.log("INFO", "=== Bot starting (PAPER TRADING — multi-strategy) ===")
    notifications.send_startup()

    while True:
        try:
            db.update_heartbeat("alive")
            run_one_cycle()
        except Exception as e:
            db.log("ERROR", f"Cycle failed: {e}\n{traceback.format_exc()}")
            db.update_heartbeat("error")
            notifications.send_alert(f"Cycle exception: {e}", "error")

        db.log("INFO", f"Sleeping {config.LOOP_INTERVAL_SECONDS}s...")
        time.sleep(config.LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
