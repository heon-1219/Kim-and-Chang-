# Phase 4 — Safety Layer (`safety.py`)

> **Prerequisite**: Phases 1–3 complete.

## Goal
Centralize all kill switch and risk limit logic. Bot calls these BEFORE every order.

## Tasks

### 1. Implement `safety.py`

Required exports:
- `check_can_trade(account, recent_trades) -> tuple[bool, str]`

Where:
- `account` is an Alpaca `TradeAccount` object
- `recent_trades` is a list of dicts from `db.get_recent_trades()`

Returns:
- `(True, "")` if all checks pass
- `(False, reason_string)` if any check fails

### 2. Checks to perform (in order)

Run checks in this order so the most fundamental check fails first:

#### Check 1: Master kill switch
```python
if db.get_config("trading_enabled", "true").lower() != "true":
    return (False, "Trading disabled by kill switch")
```

#### Check 2: Daily loss limit
```python
limit_pct = float(db.get_config("daily_loss_limit_pct", "2.0"))
last_equity = float(account.last_equity)
current_equity = float(account.equity)
if last_equity > 0:
    daily_pnl_pct = ((current_equity - last_equity) / last_equity) * 100
    if daily_pnl_pct <= -limit_pct:
        # Auto-trigger kill switch
        db.set_config("trading_enabled", "false")
        msg = f"Daily loss limit hit: {daily_pnl_pct:.2f}% (limit: -{limit_pct}%)"
        db.record_safety_event("daily_loss_hit", msg, triggered_stop=True)
        notifications.send_alert(msg, "critical")
        return (False, msg)
```

#### Check 3: Max drawdown
- Compute peak equity from `account.equity` history. For Phase 4, use a simpler proxy: compare `account.equity` against the highest equity ever seen (track this in a new `bot_config` key `peak_equity` — update it whenever current equity exceeds the stored value).
- If drawdown from peak exceeds `max_drawdown_pct`, trigger kill switch like above.

```python
peak = float(db.get_config("peak_equity", "0") or 0)
current = float(account.equity)
if current > peak:
    db.set_config("peak_equity", str(current))
    peak = current
if peak > 0:
    drawdown_pct = ((current - peak) / peak) * 100
    limit = float(db.get_config("max_drawdown_pct", "10.0"))
    if drawdown_pct <= -limit:
        db.set_config("trading_enabled", "false")
        msg = f"Max drawdown hit: {drawdown_pct:.2f}% (limit: -{limit}%)"
        db.record_safety_event("max_drawdown_hit", msg, triggered_stop=True)
        notifications.send_alert(msg, "critical")
        return (False, msg)
```

#### Check 4: Trade rate limit (runaway loop detection)
- Count trades in `recent_trades` whose timestamp is within the last 60 seconds.
- If count exceeds `max_trades_per_minute`, trigger kill switch.

```python
from datetime import datetime, timedelta

cutoff = datetime.utcnow() - timedelta(seconds=60)
recent_count = sum(
    1 for t in recent_trades
    if datetime.fromisoformat(t["timestamp"]) > cutoff
)
limit = int(db.get_config("max_trades_per_minute", "5"))
if recent_count > limit:
    db.set_config("trading_enabled", "false")
    msg = f"Trade rate limit hit: {recent_count} trades in last 60s (limit: {limit})"
    db.record_safety_event("rate_limit_hit", msg, triggered_stop=True)
    notifications.send_alert(msg, "critical")
    return (False, msg)
```

### 3. Important behavior notes
- Auto-triggered kill switches must **stay triggered** until the user manually re-enables via the dashboard. This is intentional — we want human review before resuming.
- Every safety event must be logged to `safety_events` AND alerted via Telegram with level `"critical"`.
- The function should be **fast** (< 50ms typical) — it runs before every potential trade.

### 4. Imports
```python
from datetime import datetime, timedelta
import db
import notifications
```

---

## Verification

```bash
# 1. Manual kill switch
uv run python -c "
import db
db.init_db()
db.set_config('trading_enabled', 'false')
import safety
class FakeAccount:
    equity = '100000'
    last_equity = '100000'
ok, reason = safety.check_can_trade(FakeAccount(), [])
print(ok, '|', reason)
"
# Expected: False | Trading disabled by kill switch

# 2. Daily loss trigger
uv run python -c "
import db
db.init_db()
db.set_config('trading_enabled', 'true')
db.set_config('daily_loss_limit_pct', '2.0')
import safety
class FakeAccount:
    equity = '97000'
    last_equity = '100000'  # -3%, should trigger
ok, reason = safety.check_can_trade(FakeAccount(), [])
print(ok, '|', reason)
print('Switch is now:', db.get_config('trading_enabled'))
"
# Expected: False | Daily loss limit hit: -3.00% (limit: -2.0%)
#           Switch is now: false

# 3. Normal case passes
uv run python -c "
import db
db.init_db()
db.set_config('trading_enabled', 'true')
db.set_config('daily_loss_limit_pct', '2.0')
db.set_config('peak_equity', '100000')
import safety
class FakeAccount:
    equity = '100500'
    last_equity = '100000'  # +0.5%
ok, reason = safety.check_can_trade(FakeAccount(), [])
print(ok, '|', reason)
"
# Expected: True |
```

If all 3 checks pass, Phase 4 is complete. Proceed to `05_PHASE_BROKER.md`.
