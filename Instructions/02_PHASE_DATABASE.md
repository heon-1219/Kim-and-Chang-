# Phase 2 — Database Layer (`db.py`)

> **Prerequisite**: Phase 1 complete. Read `00_OVERALL_PLAN.md`.

## Goal
Build the SQLite layer first, because every other module depends on it.

## Tasks

### 1. Implement `db.py`

Required exports:
- `init_db()` — creates all tables, sets WAL mode, seeds default config
- `get_conn()` — context manager for connections
- Trade functions: `log_trade()`, `get_recent_trades()`
- Log functions: `log()`, `get_recent_logs()`
- Config functions: `get_config()`, `set_config()`, `get_all_config()`
- Heartbeat functions: `update_heartbeat()`, `get_heartbeat()`
- API tracking: `record_api_call()`, `count_recent_api_calls()`
- Safety tracking: `record_safety_event()`, `get_recent_safety_events()`

### 2. Tables to create

```sql
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,                 -- 'buy' or 'sell'
    quantity REAL NOT NULL,
    actual_price REAL NOT NULL,         -- Alpaca fill price
    simulated_price REAL NOT NULL,      -- price after slippage applied
    alpaca_order_id TEXT,
    strategy TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(timestamp DESC);

CREATE TABLE IF NOT EXISTS bot_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    level TEXT NOT NULL,                -- 'INFO', 'WARN', 'ERROR'
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_time ON bot_log(timestamp DESC);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_beat DATETIME NOT NULL,
    status TEXT NOT NULL                -- 'alive' or 'error'
);

CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    endpoint TEXT NOT NULL,
    success INTEGER NOT NULL            -- 1 or 0
);
CREATE INDEX IF NOT EXISTS idx_api_calls_time ON api_calls(timestamp DESC);

CREATE TABLE IF NOT EXISTS safety_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    event_type TEXT NOT NULL,           -- 'kill_switch', 'daily_loss_hit', etc.
    message TEXT NOT NULL,
    triggered_stop INTEGER NOT NULL     -- 1 or 0
);
CREATE INDEX IF NOT EXISTS idx_safety_time ON safety_events(timestamp DESC);
```

### 3. WAL mode setup
On every connection (or at minimum during `init_db()`):
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
```

### 4. Seed default config on first init
The `bot_config` table must be populated on first `init_db()` call with these keys (use `INSERT OR IGNORE` so re-runs don't overwrite user changes):

| Key | Default value (string) |
|---|---|
| `symbols` | `"AAPL,MSFT,GOOGL,TSLA"` |
| `rsi_period` | `"14"` |
| `rsi_oversold` | `"30"` |
| `rsi_overbought` | `"70"` |
| `position_pct` | `"5.0"` |
| `max_positions` | `"4"` |
| `trading_enabled` | `"true"` |
| `daily_loss_limit_pct` | `"2.0"` |
| `max_drawdown_pct` | `"10.0"` |
| `max_trades_per_minute` | `"5"` |
| `slippage_bps` | `"5"` |
| `active_strategy` | `"rsi"` |

Pull these defaults from `config.py` constants (e.g., `str(config.DEFAULT_RSI_PERIOD)`).

### 5. Pattern reference
See `PATTERNS.md > DB Access` for the connection pattern.

### 6. Function signatures

```python
def init_db() -> None: ...

@contextmanager
def get_conn(): ...

def log_trade(symbol: str, side: str, quantity: float,
              actual_price: float, simulated_price: float,
              order_id: str = None, strategy: str = None,
              notes: str = None) -> None: ...

def get_recent_trades(limit: int = 50) -> list[dict]: ...

def log(level: str, message: str) -> None: ...   # also prints to console
def get_recent_logs(limit: int = 100) -> list[dict]: ...

def get_config(key: str, default: str = None) -> str | None: ...
def set_config(key: str, value: str) -> None: ...
def get_all_config() -> dict[str, str]: ...

def update_heartbeat(status: str = "alive") -> None: ...
def get_heartbeat() -> dict | None: ...

def record_api_call(endpoint: str, success: bool) -> None: ...
def count_recent_api_calls(seconds: int = 60) -> int: ...

def record_safety_event(event_type: str, message: str, triggered_stop: bool) -> None: ...
def get_recent_safety_events(limit: int = 50) -> list[dict]: ...
```

---

## Verification

```bash
# 1. Init creates DB and all tables
uv run python -c "import db; db.init_db(); print('OK')"
# Expected: OK (no errors)

# 2. All 6 tables exist
sqlite3 trading.db ".tables"
# Expected: api_calls bot_config bot_log heartbeat safety_events trades

# 3. Default config seeded
uv run python -c "import db; print(len(db.get_all_config()))"
# Expected: 12

# 4. WAL mode enabled
sqlite3 trading.db "PRAGMA journal_mode;"
# Expected: wal

# 5. Heartbeat write/read works
uv run python -c "
import db
db.update_heartbeat('alive')
print(db.get_heartbeat())
"
# Expected: dict with id=1, last_beat=<timestamp>, status='alive'

# 6. Re-running init_db doesn't overwrite changes
uv run python -c "
import db
db.set_config('symbols', 'TSLA,NVDA')
db.init_db()  # should NOT reset to defaults
print(db.get_config('symbols'))
"
# Expected: TSLA,NVDA
```

If all 6 checks pass, Phase 2 is complete. Proceed to `03_PHASE_NOTIFICATIONS.md`.
