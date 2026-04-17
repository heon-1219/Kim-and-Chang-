# Phase 5 — Broker Wrapper (`broker.py`)

> **Prerequisite**: Phases 1–4 complete.

## Goal
Wrap Alpaca API to add rate limit tracking and slippage simulation.

## Tasks

### 1. Implement `broker.py`

Required exports:
- Initialized clients: `trading_client`, `data_client`, `crypto_client`
- Wrapped functions: `get_account()`, `get_open_position(symbol)`, `get_all_positions()`, `get_clock()`, `submit_order(...)`, `get_stock_bars(...)`, `get_crypto_bars(...)`
- Helpers: `is_rate_limited() -> bool`, `apply_slippage(price, side, bps) -> float`

### 2. Initialization (HARDCODED `paper=True`)

```python
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient

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
```

### 3. API call tracking decorator

```python
from functools import wraps
import db

def track_api_call(endpoint_name: str):
    """Decorator: records the call to the api_calls table, even on failure."""
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
```

### 4. Wrapped functions

```python
@track_api_call("get_account")
def get_account():
    return trading_client.get_account()

@track_api_call("get_open_position")
def get_open_position(symbol: str):
    try:
        return trading_client.get_open_position(symbol)
    except Exception:
        return None  # not held

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
```

### 5. Rate limit checker

```python
import config

def is_rate_limited(threshold: int = None) -> bool:
    """Returns True if recent API call count exceeds threshold."""
    if threshold is None:
        threshold = config.RATE_LIMIT_THRESHOLD
    return db.count_recent_api_calls(seconds=60) > threshold
```

### 6. Slippage simulation

```python
def apply_slippage(price: float, side: str, bps: int) -> float:
    """
    Simulate execution slippage.
    - bps = basis points = hundredths of a percent (5 bps = 0.05%)
    - Buy: price moves AGAINST you (higher fill)
    - Sell: price moves AGAINST you (lower fill)
    """
    factor = bps / 10000.0
    if side.lower() == "buy":
        return price * (1.0 + factor)
    elif side.lower() == "sell":
        return price * (1.0 - factor)
    else:
        raise ValueError(f"Invalid side: {side}")
```

### 7. Special behavior for `get_open_position`
The Alpaca SDK raises an exception if the position doesn't exist. The wrapped version above swallows that exception and returns `None` — but it still records the API call as `success=True` because the call itself succeeded (it just returned "not found"). To be strictly correct, you can check the exception type and only swallow `APIError` with status 404, re-raising anything else.

```python
from alpaca.common.exceptions import APIError

@track_api_call("get_open_position")
def get_open_position(symbol: str):
    try:
        return trading_client.get_open_position(symbol)
    except APIError as e:
        if "position does not exist" in str(e).lower():
            return None
        raise
```

### 8. Pattern reference
See `PATTERNS.md > Error Handling`.

---

## Verification

Requires valid `.env` with Alpaca paper keys.

```bash
# 1. Account fetch + tracking
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
import db; db.init_db()
import broker
acct = broker.get_account()
print('Equity:', acct.equity)
print('API calls in last 60s:', db.count_recent_api_calls(60))
"
# Expected: Equity: 100000.00 (or similar paper amount)
#           API calls in last 60s: 1

# 2. Slippage math
uv run python -c "
import broker
print('Buy 100 @ 5bps:', broker.apply_slippage(100.0, 'buy', 5))
print('Sell 100 @ 5bps:', broker.apply_slippage(100.0, 'sell', 5))
"
# Expected: Buy 100 @ 5bps: 100.05
#           Sell 100 @ 5bps: 99.95

# 3. Position lookup for symbol you don't hold returns None (no crash)
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
import db; db.init_db()
import broker
print(broker.get_open_position('NVDA'))
"
# Expected: None (assuming you don't hold NVDA in paper account)

# 4. Rate limit check
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
import db; db.init_db()
import broker
print('Rate limited?', broker.is_rate_limited())
"
# Expected: Rate limited? False
```

If all 4 checks pass, Phase 5 is complete. Proceed to `06_PHASE_STRATEGIES.md`.
