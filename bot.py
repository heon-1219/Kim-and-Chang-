"""
Main trading bot loop. Runs all enabled strategies in parallel (sequentially within one cycle).
Paper trading only — real money is impossible by design (paper=True hardcoded in broker.py).
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import date, datetime, timedelta, timezone

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

# Day-level flags so we send the premarket / open pings exactly once per session
_WARMUP_DONE_FOR: date | None = None
_OPEN_PING_DONE_FOR: date | None = None

# Wake this many minutes before the opening bell to pick stocks and ping Telegram
PREMARKET_WARMUP_MIN = 30


def _fetch_bars_batch(symbols: list[str], bars_needed: int) -> dict[str, pd.Series]:
    """Fetch recent 15-min closes for many symbols in a single Alpaca call.

    Alpaca's StockBarsRequest accepts a list of symbols and returns one
    response keyed by ticker — so N symbols cost 1 API call, not N.
    Symbols with no data are returned as empty Series so callers can
    handle them uniformly.
    """
    if not symbols:
        return {}
    end = datetime.utcnow()
    trading_days = max(int(bars_needed / _BARS_PER_TRADING_DAY) + 3, 3)
    start = end - timedelta(days=trading_days * 2 + 5)
    request = StockBarsRequest(
        symbol_or_symbols=list(symbols),
        timeframe=_INTRADAY_TF,
        start=start,
        end=end,
    )
    bars = broker.get_stock_bars(request)
    out: dict[str, pd.Series] = {}
    for sym in symbols:
        sym_bars = bars.data.get(sym, [])
        closes = [b.close for b in sym_bars]
        if len(closes) > bars_needed:
            out[sym] = pd.Series(closes[-bars_needed:])
        else:
            out[sym] = pd.Series(closes, dtype=float)
    return out


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
    open_pos = list(db.get_strategy_open_positions(strategy_name))
    if not open_pos:
        return {}
    try:
        bars_by_sym = _fetch_bars_batch(open_pos, bars_needed=1)
    except Exception:
        return {}
    return {sym: float(s.iloc[-1]) for sym, s in bars_by_sym.items() if not s.empty}


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


def process_symbol(symbol: str, prices: pd.Series, settings: dict,
                   strategy_name: str, alloc_pct: float, alloc_usd: float,
                   account) -> None:
    """Run one strategy on one symbol and act on its signal.

    `prices` is the pre-fetched 15-min close series for `symbol` (shared
    across strategies in a single batched fetch — see run_one_cycle).
    """
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        db.log("ERROR", f"Unknown strategy: {strategy_name}")
        return

    lookback_days = strategy.required_lookback_days(settings)
    if len(prices) < max(lookback_days, 30):
        db.log("WARN", f"{strategy_name}/{symbol}: only {len(prices)} bars, "
                       f"need ~{lookback_days * _BARS_PER_TRADING_DAY}")
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc_aware(ts: datetime) -> datetime:
    """Coerce Alpaca's clock timestamps to tz-aware UTC for safe arithmetic."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def run_premarket_warmup(settings: dict) -> None:
    """
    30 min before the opening bell: warm the daily picker for every active
    strategy and ship a Telegram message listing today's picks. Safe to call
    multiple times in a day — the picker cache guarantees one execution per
    strategy per calendar day.
    """
    global _WARMUP_DONE_FOR
    today = date.today()
    if _WARMUP_DONE_FOR == today:
        return

    try:
        account = broker.get_account()
        equity  = float(account.equity)
    except Exception as e:
        db.log("WARN", f"Warmup: failed to fetch account ({e}); using $0 equity")
        equity = 0.0

    active = _load_active_strategies(settings, equity)
    picks_by_strat: dict[str, list[str]] = {}
    for strategy_name, _alloc_pct, _alloc_usd in active:
        try:
            picks_by_strat[strategy_name] = _picks_for(strategy_name, settings)
        except Exception as e:
            db.log("ERROR", f"Warmup pick failed for {strategy_name}: {e}")
            picks_by_strat[strategy_name] = []

    try:
        clock = broker.get_clock()
        mins  = max(
            int((_to_utc_aware(clock.next_open) - _now_utc()).total_seconds() // 60),
            0,
        )
    except Exception:
        mins = PREMARKET_WARMUP_MIN

    db.log("INFO", f"Pre-market warmup complete: picks={picks_by_strat}")
    notifications.send_premarket_picks(picks_by_strat, mins)
    _WARMUP_DONE_FOR = today


def _send_open_ping_once(settings: dict) -> None:
    """Telegram 'market open — trading live' ping, exactly once per session."""
    global _OPEN_PING_DONE_FOR
    today = date.today()
    if _OPEN_PING_DONE_FOR == today:
        return
    try:
        account = broker.get_account()
        equity  = float(account.equity)
    except Exception:
        equity = 0.0
    active_names = [n for n, _, _ in _load_active_strategies(settings, equity)]
    notifications.send_market_open(active_names)
    _OPEN_PING_DONE_FOR = today


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

    # First cycle after the bell → send Telegram "trading live" ping
    _send_open_ping_once(settings)

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

    # Build per-strategy symbol lists and the union across strategies, plus
    # the largest lookback any active strategy needs. This lets us do a
    # single batched bar fetch instead of one Alpaca call per (strategy, symbol).
    per_strategy_symbols: dict[str, list[str]] = {}
    union_symbols: list[str] = []
    union_seen: set[str] = set()
    max_bars_needed = 0
    for strategy_name, _alloc_pct, _alloc_usd in active_strategies:
        picks = _picks_for(strategy_name, settings)
        seen: set[str] = set()
        symbols: list[str] = []
        for s in list(picks) + manual_symbols:
            if s not in seen:
                symbols.append(s)
                seen.add(s)
            if s not in union_seen:
                union_symbols.append(s)
                union_seen.add(s)
        per_strategy_symbols[strategy_name] = symbols
        bars_needed = STRATEGIES[strategy_name].required_lookback_days(settings) * _BARS_PER_TRADING_DAY
        if bars_needed > max_bars_needed:
            max_bars_needed = bars_needed

    try:
        bars_by_symbol = _fetch_bars_batch(union_symbols, max_bars_needed)
    except Exception as e:
        db.log("ERROR", f"Batched bar fetch failed: {e}\n{traceback.format_exc()}")
        return

    for strategy_name, alloc_pct, alloc_usd in active_strategies:
        symbols = per_strategy_symbols[strategy_name]
        db.log("INFO",
               f"--- {strategy_name.upper()} ({alloc_pct:.1f}% of equity, "
               f"${alloc_usd:,.0f}) on {len(symbols)} symbols ---")
        for symbol in symbols:
            prices = bars_by_symbol.get(symbol, pd.Series(dtype=float))
            try:
                process_symbol(symbol, prices, settings, strategy_name,
                               alloc_pct, alloc_usd, account)
            except Exception as e:
                db.log("ERROR", f"{strategy_name}/{symbol}: {e}\n{traceback.format_exc()}")

    db.log("INFO", "Cycle complete.")


def _compute_sleep_seconds() -> tuple[int, str]:
    """
    Return (sleep_seconds, reason) based on the current market clock.

    Scheduling model:
      · Market open  → trade normally on LOOP_INTERVAL_SECONDS cadence.
      · Closed, >30m to open  → long sleep, capped so we re-check each hour.
      · Closed, ≤30m to open  → pre-market warmup now, then sleep to open − 1s
                                so the first trading cycle lands at the bell.
    """
    try:
        clock = broker.get_clock()
    except Exception as e:
        db.log("WARN", f"Clock fetch failed: {e}; defaulting to {config.LOOP_INTERVAL_SECONDS}s sleep")
        return config.LOOP_INTERVAL_SECONDS, "clock-error"

    if clock.is_open:
        return config.LOOP_INTERVAL_SECONDS, "open-cadence"

    nxt_open = _to_utc_aware(clock.next_open)
    delta    = (nxt_open - _now_utc()).total_seconds()
    warmup_s = PREMARKET_WARMUP_MIN * 60

    if delta > warmup_s:
        # Cap long sleeps at 1 hour so a mid-closure config change (or a
        # manually-set Alpaca "next open") is picked up promptly.
        sleep_s = int(min(delta - warmup_s, 3600))
        return max(sleep_s, 10), f"closed·{int(delta/60)}m-to-open"

    if delta > 0:
        # Inside the warmup window → run picker now, sleep to the bell.
        try:
            run_premarket_warmup(db.get_all_config())
        except Exception as e:
            db.log("ERROR", f"Warmup failed: {e}\n{traceback.format_exc()}")
        # Sleep until exactly the bell (tiny −1s buffer so we're already awake)
        return max(int(delta) - 1, 5), "pre-open-warmup"

    # delta ≤ 0 but clock says closed — likely a race around the bell.
    # Loop again in 5 s to pick up the transition.
    return 5, "bell-race"


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

        sleep_s, reason = _compute_sleep_seconds()
        db.log("INFO", f"Sleeping {sleep_s}s ({reason})...")
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
