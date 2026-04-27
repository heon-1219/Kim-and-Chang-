"""
Alpaca API wrapper with rate limit tracking and slippage simulation.
All Alpaca calls go through this module — never call clients directly elsewhere.
"""

import os
import time
from functools import wraps

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.common.exceptions import APIError

import config
import db

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise SystemExit(
        "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY. "
        "Copy .env.example to .env and fill in your paper trading keys."
    )

# paper=True is HARDCODED. Never read from config. Never change to False.
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
crypto_client = CryptoHistoricalDataClient(API_KEY, SECRET_KEY)


def track_api_call(endpoint_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                db.record_api_call(endpoint_name, success=True)
                return result
            except Exception as e:
                db.record_api_call(endpoint_name, success=False)
                raise
        return wrapper
    return decorator


# Module-level TTL caches for read-only endpoints. Shared by every importer
# (bot.py, dashboard.py, pages/positions.py) so account/positions/clock fetches
# coalesce across the whole process — the rate-limit counter is global so a
# dashboard hit blocks bot trades, and vice versa.
#
# TTLs are deliberately long: account / positions barely move tick-to-tick
# under paper trading, the clock state changes twice a day, and portfolio
# history is essentially immutable for the historical buckets and only the
# last bar moves. Aggressive caching here is the floor that survives even a
# `st.cache_data.clear()` on the dashboard.
_ACCOUNT_CACHE_TTL   = 90.0
_POSITIONS_CACHE_TTL = 90.0
_CLOCK_CACHE_TTL     = 120.0
_PORTFOLIO_CACHE_TTL = 600.0

_account_cache:    tuple[float, object] | None = None
_positions_cache:  tuple[float, object] | None = None
_clock_cache:      tuple[float, object] | None = None
_portfolio_cache:  dict[tuple[str, str], tuple[float, object]] = {}


@track_api_call("get_account")
def _get_account_uncached():
    return trading_client.get_account()


def get_account(force: bool = False):
    """Return a recent account snapshot, TTL-cached for 90s.

    Account equity/cash/buying-power barely move tick-to-tick, so a short
    stale window is fine and saves duplicate calls — both the bot loop and
    the Streamlit dashboard re-enter this every few seconds.
    """
    global _account_cache
    now = time.time()
    if not force and _account_cache is not None and (now - _account_cache[0]) < _ACCOUNT_CACHE_TTL:
        return _account_cache[1]
    account = _get_account_uncached()
    _account_cache = (now, account)
    return account


@track_api_call("get_open_position")
def get_open_position(symbol: str):
    try:
        return trading_client.get_open_position(symbol)
    except APIError as e:
        if "position does not exist" in str(e).lower():
            return None
        raise


@track_api_call("get_all_positions")
def _get_all_positions_uncached():
    return trading_client.get_all_positions()


def get_all_positions(force: bool = False):
    """Return the position list, TTL-cached for 90s.

    The dashboard rerenders this on every Streamlit interaction and the
    positions analytics page does too — without a broker-level cache, each
    rerun was a fresh Alpaca hit. Pass force=True to bypass the cache when
    you actually need ground truth (e.g. immediately after submitting a fill).
    """
    global _positions_cache
    now = time.time()
    if not force and _positions_cache is not None and (now - _positions_cache[0]) < _POSITIONS_CACHE_TTL:
        return _positions_cache[1]
    positions = _get_all_positions_uncached()
    _positions_cache = (now, positions)
    return positions


@track_api_call("get_clock")
def _get_clock_uncached():
    return trading_client.get_clock()


def get_clock():
    """Return a recent market clock, TTL-cached for 120s.

    The clock state changes twice a day (open/close), so a 2-minute stale
    window is harmless and saves duplicate calls — bot.run_one_cycle and
    _compute_sleep_seconds previously fetched it twice per cycle.
    """
    global _clock_cache
    now = time.time()
    if _clock_cache is not None and (now - _clock_cache[0]) < _CLOCK_CACHE_TTL:
        return _clock_cache[1]
    clock = _get_clock_uncached()
    _clock_cache = (now, clock)
    return clock


def invalidate_caches() -> None:
    """Drop the read-only caches. Call after a known mutation (e.g. submit_order)
    so the next read sees fresh state."""
    global _account_cache, _positions_cache, _clock_cache
    _account_cache = None
    _positions_cache = None
    _clock_cache = None
    _portfolio_cache.clear()


@track_api_call("submit_order")
def submit_order(order_data):
    result = trading_client.submit_order(order_data=order_data)
    # A fill changes positions and (cash) account state — drop the read caches
    # so the next caller doesn't see a 45s-stale snapshot.
    invalidate_caches()
    return result


@track_api_call("get_stock_bars")
def get_stock_bars(request):
    return data_client.get_stock_bars(request)


@track_api_call("get_crypto_bars")
def get_crypto_bars(request):
    return crypto_client.get_crypto_bars(request)


@track_api_call("get_portfolio_history")
def _get_portfolio_history_uncached(period: str, timeframe: str):
    from alpaca.trading.requests import GetPortfolioHistoryRequest
    return trading_client.get_portfolio_history(
        history_filter=GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
    )


def get_portfolio_history(period: str = "1M", timeframe: str = "1D"):
    """Return a portfolio history snapshot, TTL-cached for 600s per
    (period, timeframe) pair.

    The dashboard's Period dropdown has 11 distinct (period, tf) combos and
    Streamlit reruns the script on every interaction — without a broker-level
    cache, period-shopping could fire a fresh Alpaca call per click. Past
    bars are immutable; only the last bar updates intraday, so a 10-minute
    stale window on the chart is fine.
    """
    key = (period, timeframe)
    now = time.time()
    cached = _portfolio_cache.get(key)
    if cached is not None and (now - cached[0]) < _PORTFOLIO_CACHE_TTL:
        return cached[1]
    result = _get_portfolio_history_uncached(period, timeframe)
    _portfolio_cache[key] = (now, result)
    return result


def is_rate_limited(threshold: int = None) -> bool:
    if threshold is None:
        threshold = config.RATE_LIMIT_THRESHOLD
    return db.count_recent_api_calls(seconds=60) > threshold


def apply_slippage(price: float, side: str, bps: int) -> float:
    """
    Simulate execution slippage — bps moves price against you.
    Buy: higher fill. Sell: lower fill.
    """
    factor = bps / 10000.0
    if side.lower() == "buy":
        return price * (1.0 + factor)
    elif side.lower() == "sell":
        return price * (1.0 - factor)
    else:
        raise ValueError(f"Invalid side: {side}")
