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

# Cap on bars per symbol per cycle. The widest indicator window across active
# strategies (MACD slow+signal+buffer) is <50, so 80 gives slack without
# triggering Alpaca's bar-pagination amplifier — at >10k bars/request Alpaca
# splits the response into multiple HTTP hits that each count against the
# 200/min cap even though the SDK surface returns one value.
_BARS_FETCH_CAP = 80

# Hard floor on bot loop interval so even a wedged loop can't burst-call Alpaca.
# A halted/closed bot should sleep way longer than this anyway; this is the
# ceiling on call rate, not a target cadence.
_MIN_LOOP_SECONDS = 60

# (period, timeframe) combos the dashboard exposes via its Period dropdown.
# The bot pre-fetches all of them each healthy cycle so the dashboard can
# render the equity chart without touching Alpaca itself.
_PORTFOLIO_PERIODS: list[tuple[str, str]] = [
    ("1D",  "1Min"),
    ("1D",  "5Min"),
    ("5D",  "15Min"),
    ("1W",  "15Min"),
    ("1W",  "1H"),
    ("1M",  "1H"),
    ("1M",  "1D"),
    ("1A",  "1D"),
    ("5A",  "1D"),
]

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
    # Pull a tight calendar window around `bars_needed`. Old math (×2 + 5) was
    # paranoid and pushed responses past Alpaca's ~10k-bars-per-page threshold,
    # which the SDK silently splits into multiple HTTP hits — each counted by
    # Alpaca's 200/min limiter even though our tracker only sees one call.
    # +3 calendar days covers a normal weekend; bars_needed itself is already
    # capped well above any active strategy's actual indicator window.
    trading_days = max((bars_needed // _BARS_PER_TRADING_DAY) + 1, 2)
    start = end - timedelta(days=trading_days + 3)
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


def _current_prices_for(strategy_name: str,
                        bars_by_symbol: dict[str, pd.Series] | None = None) -> dict[str, float]:
    """Latest known price per symbol held by this strategy, used to value open positions.

    When `bars_by_symbol` is provided (the cycle's already-fetched batch), we
    serve prices from it and skip the Alpaca call entirely — saving one data
    call per fill on busy days. Symbols held but not in the batch (e.g. a
    legacy holding that's no longer in any picker) are simply omitted;
    `db.get_strategy_equity` tolerates a missing price.
    """
    open_pos = list(db.get_strategy_open_positions(strategy_name))
    if not open_pos:
        return {}
    if bars_by_symbol is not None:
        out: dict[str, float] = {}
        for sym in open_pos:
            s = bars_by_symbol.get(sym)
            if s is not None and not s.empty:
                out[sym] = float(s.iloc[-1])
        return out
    try:
        bars_by_sym = _fetch_bars_batch(open_pos, bars_needed=1)
    except Exception:
        return {}
    return {sym: float(s.iloc[-1]) for sym, s in bars_by_sym.items() if not s.empty}


def _notify_trade(strategy_name: str, symbol: str, side: str, qty: float,
                  price: float, alloc_usd: float,
                  bars_by_symbol: dict[str, pd.Series] | None = None) -> None:
    """Compute per-strategy total asset then ship the rich Telegram alert."""
    try:
        # Include the just-filled trade's symbol in the price map so the freshly-
        # opened (or freshly-closed) position values correctly.
        prices = _current_prices_for(strategy_name, bars_by_symbol)
        prices[symbol] = price
        total = db.get_strategy_equity(strategy_name, alloc_usd, prices)
    except Exception as e:
        db.log("WARN", f"Failed to compute {strategy_name} equity: {e}")
        total = alloc_usd
    notifications.send_trade_alert(strategy_name, symbol, side, qty, price, total)


def _serialize_account(account) -> dict:
    """Pull the few fields the dashboard reads. Stringified to survive any
    Decimal vs float quirks in alpaca-py — the dashboard re-parses to float."""
    return {
        "equity":       str(getattr(account, "equity", "0")),
        "cash":         str(getattr(account, "cash", "0")),
        "buying_power": str(getattr(account, "buying_power", "0")),
        "last_equity":  str(getattr(account, "last_equity", "0")),
    }


def _serialize_positions(positions) -> list[dict]:
    return [
        {
            "symbol":           p.symbol,
            "qty":              str(p.qty),
            "avg_entry_price":  str(p.avg_entry_price),
            "current_price":    str(p.current_price),
            "market_value":     str(p.market_value),
            "unrealized_pl":    str(p.unrealized_pl),
            "unrealized_plpc":  str(p.unrealized_plpc),
        }
        for p in positions
    ]


def _update_dashboard_snapshots(account) -> None:
    """Persist account + positions + portfolio history to the snapshots table.

    The dashboard reads from these instead of calling Alpaca directly, so
    the only process making Alpaca read calls is the bot during a healthy
    trading cycle. Per-call exceptions are swallowed: a missing portfolio
    period just means the dashboard shows stale data for that period.
    """
    try:
        db.set_snapshot("account", _serialize_account(account))
    except Exception as e:
        db.log("WARN", f"snapshot[account] failed: {e}")

    try:
        positions = broker.get_all_positions()
        db.set_snapshot("positions", _serialize_positions(positions))
    except Exception as e:
        db.log("WARN", f"snapshot[positions] failed: {e}")

    for period, tf in _PORTFOLIO_PERIODS:
        try:
            ph = broker.get_portfolio_history(period=period, timeframe=tf)
            if not getattr(ph, "timestamp", None):
                continue
            db.set_snapshot(
                f"portfolio_{period}_{tf}",
                {"timestamp": list(ph.timestamp), "equity": list(ph.equity)},
            )
        except Exception:
            # Some (period, tf) combos are invalid for paper accounts; skip
            # silently so a flaky combo doesn't pollute the log.
            pass


def _make_position_resolver():
    """Lazy single-shot get_all_positions per cycle.

    Returns a function `resolve(symbol)` that fetches Alpaca's full position
    map on first call and serves all subsequent lookups from memory. Trades
    one `get_all_positions` for N `get_open_position` calls — net win whenever
    a cycle has ≥1 sell, neutral on cycles with no sells (the resolver is
    never invoked).
    """
    cache: dict[str, object] = {}
    fetched = [False]

    def resolve(symbol: str):
        if not fetched[0]:
            try:
                cache.update({p.symbol: p for p in broker.get_all_positions()})
            except Exception:
                pass
            fetched[0] = True
        return cache.get(symbol)

    return resolve


def place_buy(symbol: str, current_price: float, settings: dict,
              strategy_name: str, alloc_pct: float, alloc_usd: float, account,
              bars_by_symbol: dict[str, pd.Series] | None = None) -> None:
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
        _notify_trade(strategy_name, symbol, "buy", qty, current_price, alloc_usd, bars_by_symbol)
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] BUY {symbol} failed: {e}")
        notifications.send_alert(f"BUY {symbol} failed: {e}", "error")


def place_sell(symbol: str, held_qty: float, current_price: float,
               settings: dict, strategy_name: str, alloc_usd: float,
               bars_by_symbol: dict[str, pd.Series] | None = None,
               resolve_position=None) -> None:
    """Sell exactly the qty this strategy holds, capped by actual Alpaca position."""
    if resolve_position is not None:
        actual_pos = resolve_position(symbol)
    else:
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
        _notify_trade(strategy_name, symbol, "sell", qty, current_price, alloc_usd, bars_by_symbol)
    except Exception as e:
        db.log("ERROR", f"[{strategy_name.upper()}] SELL {symbol} failed: {e}")
        notifications.send_alert(f"SELL {symbol} failed: {e}", "error")


def process_symbol(symbol: str, prices: pd.Series, settings: dict,
                   strategy_name: str, alloc_pct: float, alloc_usd: float,
                   account,
                   bars_by_symbol: dict[str, pd.Series] | None = None,
                   resolve_position=None) -> None:
    """Run one strategy on one symbol and act on its signal.

    `prices` is the pre-fetched 15-min close series for `symbol` (shared
    across strategies in a single batched fetch — see run_one_cycle).
    """
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        db.log("ERROR", f"Unknown strategy: {strategy_name}")
        return

    lookback = strategy.required_lookback_days(settings)
    if len(prices) < max(lookback, 30):
        db.log("WARN", f"{strategy_name}/{symbol}: only {len(prices)} bars, "
                       f"need ~{max(lookback, 30)}")
        return

    current_price = float(prices.iloc[-1])
    sig           = strategy.signal(prices, settings)
    db.log("INFO", f"{strategy_name}/{symbol}: ${current_price:.2f} → {sig}")

    # Per-strategy position tracking via DB — each strategy owns only what it bought
    held_qty     = db.get_strategy_holding(symbol, strategy_name)
    has_position = held_qty > 0

    if sig == "buy" and not has_position:
        place_buy(symbol, current_price, settings, strategy_name, alloc_pct, alloc_usd,
                  account, bars_by_symbol)
    elif sig == "sell" and has_position:
        place_sell(symbol, held_qty, current_price, settings, strategy_name, alloc_usd,
                   bars_by_symbol, resolve_position)


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


def _send_open_ping_once(settings: dict, account=None) -> None:
    """Telegram 'market open — trading live' ping, exactly once per session.

    Caller passes the already-fetched account so we don't re-hit Alpaca just
    to read equity. The broker cache would absorb a duplicate anyway, but
    skipping the call keeps the rate-limit counter cleaner.
    """
    global _OPEN_PING_DONE_FOR
    today = date.today()
    if _OPEN_PING_DONE_FOR == today:
        return
    try:
        if account is None:
            account = broker.get_account()
        equity = float(account.equity)
    except Exception:
        equity = 0.0
    active_names = [n for n, _, _ in _load_active_strategies(settings, equity)]
    notifications.send_market_open(active_names)
    _OPEN_PING_DONE_FOR = today


def run_one_cycle() -> None:
    """Run every enabled strategy across its own picked symbols."""
    settings = db.get_all_config()

    # Bail before any API call when we're already near the cap — the original
    # check sat after get_account + get_clock and burned 2 calls per skip.
    if broker.is_rate_limited():
        db.log("WARN", f"Near API rate limit, sleeping {config.RATE_LIMIT_SLEEP_SECONDS}s")
        time.sleep(config.RATE_LIMIT_SLEEP_SECONDS)
        return

    # Kill-switch check up front — purely a DB read. When the user halts trading
    # the bot must make ZERO Alpaca calls; the original ordering still hit
    # get_account before the safety check, burning ~12 calls/hour of nothing.
    if settings.get("trading_enabled", "true").lower() != "true":
        db.log("INFO", "Trading disabled by kill switch — skipping cycle")
        return

    # Same for the market-closed check — try the cached clock first so the
    # idle-hours path stays at zero new Alpaca calls when the cache is warm.
    clock = broker.get_clock()
    if not clock.is_open:
        db.log("INFO", f"Market closed. Next open: {clock.next_open}")
        return

    account       = broker.get_account()
    recent_trades = db.get_recent_trades(limit=20)

    ok, reason = safety.check_can_trade(account, recent_trades)
    if not ok:
        db.log("WARN", f"Safety stop: {reason}")
        return

    # Refresh the dashboard's data layer. This is the only place the codebase
    # writes to the snapshots table — the dashboard reads from it, never calls
    # Alpaca directly. Halted / closed cycles return earlier and produce no
    # snapshot updates, which is the desired behavior (zero Alpaca calls when
    # not trading).
    _update_dashboard_snapshots(account)

    # First cycle after the bell → send Telegram "trading live" ping.
    # Reuse the account snapshot we just fetched.
    _send_open_ping_once(settings, account)

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
        # required_lookback_days returns the indicator window in *bars* (the
        # name is a legacy from when this codebase ran on daily data). Don't
        # convert to bars-per-day — process_symbol's gate is `len(prices) <
        # max(lookback, 30)` so 50–80 bars is more than enough.
        bars_needed = min(
            max(STRATEGIES[strategy_name].required_lookback_days(settings) + 5, 50),
            _BARS_FETCH_CAP,
        )
        if bars_needed > max_bars_needed:
            max_bars_needed = bars_needed

    try:
        bars_by_symbol = _fetch_bars_batch(union_symbols, max_bars_needed)
    except Exception as e:
        db.log("ERROR", f"Batched bar fetch failed: {e}\n{traceback.format_exc()}")
        return

    # Lazily fetched on the first sell of this cycle — collapses N per-sell
    # `get_open_position` calls into a single `get_all_positions`.
    resolve_position = _make_position_resolver()

    for strategy_name, alloc_pct, alloc_usd in active_strategies:
        symbols = per_strategy_symbols[strategy_name]
        db.log("INFO",
               f"--- {strategy_name.upper()} ({alloc_pct:.1f}% of equity, "
               f"${alloc_usd:,.0f}) on {len(symbols)} symbols ---")
        for symbol in symbols:
            prices = bars_by_symbol.get(symbol, pd.Series(dtype=float))
            try:
                process_symbol(symbol, prices, settings, strategy_name,
                               alloc_pct, alloc_usd, account,
                               bars_by_symbol, resolve_position)
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
        # Hard floor: even if every Alpaca call fails fast or the cycle short-
        # circuits, we never burn through the loop more than once per minute.
        # Caps API blast in any pathological state (multiple processes, crash
        # loops, clock-cache poisoning).
        sleep_s = max(sleep_s, _MIN_LOOP_SECONDS)
        db.log("INFO", f"Sleeping {sleep_s}s ({reason})...")
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
