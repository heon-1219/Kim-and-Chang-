"""
Main trading bot loop. Runs all enabled strategies in parallel (sequentially within one cycle).
Paper trading only — real money is impossible by design (paper=True hardcoded in broker.py).
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

import broker
import config
import db
import notifications
import safety
from strategies import STRATEGIES
from universe import get_sp500_symbols

# 15-minute bars feed the live signals; daily bars drive the once-a-day picker
_INTRADAY_TF = TimeFrame(15, TimeFrameUnit.Minute)
_BARS_PER_TRADING_DAY = 26  # 6.5 hours * 4 fifteen-minute bars

# (date, {strategy_name: [symbols...]}) — rebuilt at most once per calendar day
_PICKED_SYMBOLS: dict[str, tuple[date, list[str]]] = {}


def get_recent_prices(symbol: str, bars_needed: int) -> pd.Series:
    """Fetch recent 15-min close prices for a symbol."""
    end = datetime.utcnow()
    # Pull a generous window — intraday bars only cover market hours
    trading_days = max(int(bars_needed / _BARS_PER_TRADING_DAY) + 3, 3)
    start = end - timedelta(days=trading_days * 2 + 5)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=_INTRADAY_TF,
        start=start,
        end=end,
    )
    bars = broker.get_stock_bars(request)
    if symbol not in bars.data:
        return pd.Series(dtype=float)
    closes = [bar.close for bar in bars.data[symbol]]
    return pd.Series(closes[-bars_needed:]) if len(closes) > bars_needed else pd.Series(closes)


def _daily_closes_yf(symbol: str, days: int = 180) -> pd.Series:
    """Fetch daily closes via yfinance — used by the picker to rank the universe."""
    try:
        hist = yf.Ticker(symbol).history(period=f"{days}d", auto_adjust=True)
        if hist.empty:
            return pd.Series(dtype=float)
        return hist["Close"].dropna().reset_index(drop=True)
    except Exception:
        return pd.Series(dtype=float)


def calculate_quantity(equity: float, price: float, position_pct: float) -> int:
    """Integer shares that fit within position_pct of the given equity slice."""
    return max(int(equity * (position_pct / 100.0) / price), 0)


def _current_prices_for(strategy_name: str) -> dict[str, float]:
    """Latest known price per symbol held by this strategy, used to value open positions."""
    open_pos = db.get_strategy_open_positions(strategy_name)
    prices: dict[str, float] = {}
    for sym in open_pos:
        try:
            series = get_recent_prices(sym, bars_needed=1)
            if not series.empty:
                prices[sym] = float(series.iloc[-1])
        except Exception:
            continue
    return prices


def _notify_trade(strategy_name: str, symbol: str, side: str, qty: float,
                  price: float, alloc_usd: float) -> None:
    """Compute per-strategy total asset then ship the rich Telegram alert."""
    try:
        # Include the just-filled trade's symbol in the price map so the freshly-
        # opened (or freshly-closed) position values correctly.
        prices = _current_prices_for(strategy_name)
        prices[symbol] = price
        total = db.get_strategy_equity(strategy_name, alloc_usd, prices)
    except Exception as e:
        db.log("WARN", f"Failed to compute {strategy_name} equity: {e}")
        total = alloc_usd
    notifications.send_trade_alert(strategy_name, symbol, side, qty, price, total)


def place_buy(symbol: str, current_price: float, settings: dict,
              strategy_name: str, alloc_pct: float, alloc_usd: float, account) -> None:
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
        _notify_trade(strategy_name, symbol, "buy", qty, current_price, alloc_usd)
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] BUY {symbol} failed: {e}")
        notifications.send_alert(f"BUY {symbol} failed: {e}", "error")


def place_sell(symbol: str, held_qty: float, current_price: float,
               settings: dict, strategy_name: str, alloc_usd: float) -> None:
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
        _notify_trade(strategy_name, symbol, "sell", qty, current_price, alloc_usd)
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] SELL {symbol} failed: {e}")
        notifications.send_alert(f"SELL {symbol} failed: {e}", "error")


def process_symbol(symbol: str, settings: dict,
                   strategy_name: str, alloc_pct: float, alloc_usd: float,
                   account) -> None:
    """Run one strategy on one symbol and act on its signal."""
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        db.log("ERROR", f"Unknown strategy: {strategy_name}")
        return

    # Strategy-defined lookback is in "days"; convert to intraday bars
    lookback_days = strategy.required_lookback_days(settings)
    bars_needed   = lookback_days * _BARS_PER_TRADING_DAY
    prices        = get_recent_prices(symbol, bars_needed=bars_needed)
    if len(prices) < max(lookback_days, 30):
        db.log("WARN", f"{strategy_name}/{symbol}: only {len(prices)} bars, need ~{bars_needed}")
        return

    current_price = float(prices.iloc[-1])
    sig           = strategy.signal(prices, settings)
    db.log("INFO", f"{strategy_name}/{symbol}: ${current_price:.2f} → {sig}")

    # Per-strategy position tracking via DB — each strategy owns only what it bought
    held_qty     = db.get_strategy_holding(symbol, strategy_name)
    has_position = held_qty > 0

    if sig == "buy" and not has_position:
        place_buy(symbol, current_price, settings, strategy_name, alloc_pct, alloc_usd, account)
    elif sig == "sell" and has_position:
        place_sell(symbol, held_qty, current_price, settings, strategy_name, alloc_usd)


def _load_active_strategies(settings: dict, account_equity: float) -> list[tuple[str, float, float]]:
    """Return [(strategy_name, alloc_pct, alloc_usd), ...] from strategy_allocation config.

    Supports both alloc_usd (new, dashboard converts to pct using live equity)
    and legacy alloc_pct. Falls back to (active_strategy, 100%, account_equity)
    if unconfigured.
    """
    try:
        alloc: dict = json.loads(settings.get("strategy_allocation", "{}"))
    except (json.JSONDecodeError, TypeError):
        alloc = {}

    result: list[tuple[str, float, float]] = []
    for k, v in alloc.items():
        if not v.get("enabled") or k not in STRATEGIES:
            continue
        if "alloc_usd" in v:
            usd = float(v.get("alloc_usd", 0))
            if usd > 0 and account_equity > 0:
                result.append((k, (usd / account_equity) * 100, usd))
        elif "alloc_pct" in v:  # legacy fallback
            pct = float(v.get("alloc_pct", 0))
            if pct > 0:
                result.append((k, pct, account_equity * pct / 100))

    if result:
        return result

    fallback = settings.get("active_strategy", "rsi")
    if fallback in STRATEGIES:
        return [(fallback, 100.0, account_equity)]
    return []


def _picks_for(strategy_name: str, settings: dict) -> list[str]:
    """Cached daily picks for a strategy. Rebuilt once per calendar day."""
    top_n = int(settings.get("picker_top_n", str(config.DEFAULT_PICKER_TOP_N)))
    today = date.today()
    cached = _PICKED_SYMBOLS.get(strategy_name)
    if cached and cached[0] == today:
        return cached[1]

    strategy = STRATEGIES[strategy_name]
    universe = get_sp500_symbols()
    db.log("INFO", f"[{strategy_name.upper()}] picking top {top_n} from {len(universe)} symbols…")
    try:
        picks = strategy.pick_symbols(universe, top_n, _daily_closes_yf, settings)
    except Exception as e:
        db.log("ERROR", f"{strategy_name} pick_symbols failed: {e}")
        picks = universe[:top_n]
    _PICKED_SYMBOLS[strategy_name] = (today, picks)
    db.log("INFO", f"[{strategy_name.upper()}] picks: {picks}")
    return picks


def run_one_cycle() -> None:
    """Run every enabled strategy across its own picked symbols."""
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

    # The optional manual symbol list is always traded in addition to picks
    manual_symbols = [s.strip() for s in settings.get("symbols", "").split(",") if s.strip()]

    db.log("INFO",
           f"Cycle start. strategies={[n for n, _, _ in active_strategies]}, "
           f"manual_symbols={manual_symbols}")

    for strategy_name, alloc_pct, alloc_usd in active_strategies:
        picks = _picks_for(strategy_name, settings)
        # Union of picks + manual, preserving picks first
        seen: set[str] = set()
        symbols: list[str] = []
        for s in list(picks) + manual_symbols:
            if s not in seen:
                symbols.append(s)
                seen.add(s)

        db.log("INFO",
               f"--- {strategy_name.upper()} ({alloc_pct:.1f}% of equity, "
               f"${alloc_usd:,.0f}) on {len(symbols)} symbols ---")
        for symbol in symbols:
            try:
                process_symbol(symbol, settings, strategy_name,
                               alloc_pct, alloc_usd, account)
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
