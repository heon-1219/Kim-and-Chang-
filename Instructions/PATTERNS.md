# Code Patterns

> Referenced from multiple phase files. Apply these patterns consistently throughout the codebase.

---

## DB Access

```python
# GOOD — context manager handles connection lifecycle
from db import get_conn

with get_conn() as conn:
    rows = conn.execute(
        "SELECT * FROM trades WHERE symbol = ?", (symbol,)
    ).fetchall()
    return [dict(r) for r in rows]

# GOOD — write with explicit commit
with get_conn() as conn:
    conn.execute(
        "INSERT INTO trades (...) VALUES (?, ?, ?)",
        (a, b, c)
    )
    conn.commit()

# BAD — manual connection, no cleanup on error
conn = sqlite3.connect("trading.db")
rows = conn.execute(...).fetchall()
# (forgot to close — connection leak)
```

### Always use parameterized queries
```python
# GOOD — placeholder for value
conn.execute("SELECT * FROM trades WHERE symbol = ?", (symbol,))

# BAD — string formatting (SQL injection risk, even from internal data)
conn.execute(f"SELECT * FROM trades WHERE symbol = '{symbol}'")
```

---

## Error Handling

### Catch specific exceptions
```python
# GOOD
from alpaca.common.exceptions import APIError

try:
    order = broker.submit_order(...)
except APIError as e:
    db.log("ERROR", f"Order failed for {symbol}: {e}")
    notifications.send_alert(f"Order failed: {e}", "error")
    return
except Exception as e:
    # Last-resort catch — log full traceback for debugging
    import traceback
    db.log("ERROR", f"Unexpected error: {e}\n{traceback.format_exc()}")
    return

# BAD — bare except swallows KeyboardInterrupt, SystemExit, etc.
try:
    order = broker.submit_order(...)
except:
    pass
```

### Per-cycle isolation in long-running loops
```python
# GOOD — one bad symbol doesn't break the cycle
for symbol in symbols:
    try:
        process_symbol(symbol)
    except Exception as e:
        db.log("ERROR", f"{symbol} failed: {e}")
        # continue to next symbol

# BAD — first failure kills the cycle
for symbol in symbols:
    process_symbol(symbol)  # if this raises, loop exits
```

---

## Configuration

### Read from DB, not constants
```python
# GOOD — picks up dashboard changes without restart
settings = db.get_all_config()
threshold = float(settings["rsi_oversold"])

# OK — for genuinely static values that should never change at runtime
TIMEOUT_SECONDS = 30  # constant in code

# BAD — hardcoded business logic value, can't be tuned without code edit
threshold = 30  # in strategy or trading logic
```

### Always provide defaults
```python
# GOOD — code keeps working if a config row is missing
period = int(settings.get("rsi_period", "14"))

# BAD — KeyError crashes the bot
period = int(settings["rsi_period"])
```

### Cast types explicitly (everything in DB is string)
```python
# GOOD
enabled = settings["trading_enabled"].lower() == "true"
period = int(settings["rsi_period"])
threshold = float(settings["rsi_oversold"])

# BAD — comparing string to bool, comparing string to int
if settings["trading_enabled"]:  # "false" is truthy!
    ...
```

---

## Trade Execution

### Standard flow: safety → execute → log → alert
```python
# GOOD
def place_buy(symbol, price, settings, account):
    # 1. Safety check happens BEFORE this function (in main loop)
    # 2. Compute order details
    qty = calculate_quantity(...)
    if qty < 1:
        db.log("WARN", f"{symbol}: qty=0, skipping")
        return

    # 3. Apply slippage to track expected vs actual
    sim_price = broker.apply_slippage(price, "buy", slippage_bps)

    # 4. Submit
    try:
        order = broker.submit_order(MarketOrderRequest(...))
    except APIError as e:
        db.log("ERROR", f"BUY {symbol} failed: {e}")
        notifications.send_alert(f"BUY {symbol} failed: {e}", "error")
        return

    # 5. Log to DB
    db.log_trade(symbol, "buy", qty, price, sim_price, str(order.id), ...)

    # 6. Alert user
    msg = f"BUY {qty} {symbol} @ ${price:.2f}"
    db.log("INFO", msg)
    notifications.send_alert(msg, "trade")
```

---

## Logging Levels

| Level | When to use | Example |
|---|---|---|
| `INFO` | Normal operation | "Cycle start", "Sleeping 3600s" |
| `WARN` | Unexpected but recoverable | "qty=0, skipping", "Insufficient price data" |
| `ERROR` | Caught exceptions | "Order failed: timeout", "API error" |

Notifications via Telegram should use `info` level **sparingly** (only startup/shutdown). For trades use `trade`. For errors use `error`. For safety stops use `critical`.

---

## File Headers

Every Python file starts with a triple-quoted docstring:
```python
"""
Brief one-line description.

Optional longer description if behavior isn't obvious from imports.
"""
```

Don't write boilerplate copyright headers. Don't add type-of-file markers like `# -*- coding: utf-8 -*-` (Python 3 is UTF-8 by default).

---

## Imports

Order: stdlib → third-party → local. Each group separated by a blank line.

```python
# GOOD
import os
import time
from datetime import datetime

import pandas as pd
from alpaca.trading.client import TradingClient

import broker
import db
```

---

## Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE`
- Private (rare): `_leading_underscore`

Trading-specific:
- `qty` for quantity (matches Alpaca SDK)
- `symbol` for ticker
- `bps` for basis points (1 bp = 0.01%)
- `pct` for percent (5.0 = 5%, NOT 0.05)
