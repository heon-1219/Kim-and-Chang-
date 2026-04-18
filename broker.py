"""
Alpaca API wrapper with rate limit tracking and slippage simulation.
All Alpaca calls go through this module — never call clients directly elsewhere.
"""

import os
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


@track_api_call("get_account")
def get_account():
    return trading_client.get_account()


@track_api_call("get_open_position")
def get_open_position(symbol: str):
    try:
        return trading_client.get_open_position(symbol)
    except APIError as e:
        if "position does not exist" in str(e).lower():
            return None
        raise


@track_api_call("get_all_positions")
def get_all_positions():
    return trading_client.get_all_positions()


@track_api_call("get_clock")
def get_clock():
    return trading_client.get_clock()


@track_api_call("submit_order")
def submit_order(order_data):
    return trading_client.submit_order(order_data=order_data)


@track_api_call("get_stock_bars")
def get_stock_bars(request):
    return data_client.get_stock_bars(request)


@track_api_call("get_crypto_bars")
def get_crypto_bars(request):
    return crypto_client.get_crypto_bars(request)


@track_api_call("get_portfolio_history")
def get_portfolio_history(period: str = "1M", timeframe: str = "1D"):
    from alpaca.trading.requests import GetPortfolioHistoryRequest
    return trading_client.get_portfolio_history(
        history_filter=GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
    )


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
