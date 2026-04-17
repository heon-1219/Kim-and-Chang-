"""
SQLite database layer. All database access goes through this module.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config

DB_PATH = config.DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                actual_price REAL NOT NULL,
                simulated_price REAL NOT NULL,
                alpaca_order_id TEXT,
                strategy TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(timestamp DESC);

            CREATE TABLE IF NOT EXISTS bot_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                level TEXT NOT NULL,
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
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                endpoint TEXT NOT NULL,
                success INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_api_calls_time ON api_calls(timestamp DESC);

            CREATE TABLE IF NOT EXISTS safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                triggered_stop INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_safety_time ON safety_events(timestamp DESC);
        """)

        now = datetime.utcnow().isoformat()
        defaults = [
            ("symbols", ",".join(config.DEFAULT_SYMBOLS)),
            ("rsi_period", str(config.DEFAULT_RSI_PERIOD)),
            ("rsi_oversold", str(config.DEFAULT_RSI_OVERSOLD)),
            ("rsi_overbought", str(config.DEFAULT_RSI_OVERBOUGHT)),
            ("position_pct", str(config.DEFAULT_POSITION_PCT)),
            ("max_positions", str(config.DEFAULT_MAX_POSITIONS)),
            ("trading_enabled", "true"),
            ("daily_loss_limit_pct", str(config.DEFAULT_DAILY_LOSS_LIMIT_PCT)),
            ("max_drawdown_pct", str(config.DEFAULT_MAX_DRAWDOWN_PCT)),
            ("max_trades_per_minute", str(config.DEFAULT_MAX_TRADES_PER_MINUTE)),
            ("slippage_bps", str(config.DEFAULT_SLIPPAGE_BPS)),
            ("active_strategy", config.DEFAULT_ACTIVE_STRATEGY),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO bot_config (key, value, updated_at) VALUES (?, ?, ?)",
            [(k, v, now) for k, v in defaults],
        )
        conn.commit()


# --- Trades ---

def log_trade(symbol: str, side: str, quantity: float,
              actual_price: float, simulated_price: float,
              order_id: str = None, strategy: str = None,
              notes: str = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trades
               (timestamp, symbol, side, quantity, actual_price, simulated_price,
                alpaca_order_id, strategy, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), symbol, side, quantity,
             actual_price, simulated_price, order_id, strategy, notes),
        )
        conn.commit()


def get_recent_trades(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Logs ---

def log(level: str, message: str) -> None:
    print(f"[{level}] {message}")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_log (timestamp, level, message) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), level, message),
        )
        conn.commit()


def get_recent_logs(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bot_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Config ---

def get_config(key: str, default: str = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM bot_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_config(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bot_config (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
               updated_at = excluded.updated_at""",
            (key, value, datetime.utcnow().isoformat()),
        )
        conn.commit()


def get_all_config() -> dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM bot_config").fetchall()
        return {r["key"]: r["value"] for r in rows}


# --- Heartbeat ---

def update_heartbeat(status: str = "alive") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO heartbeat (id, last_beat, status) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET last_beat = excluded.last_beat,
               status = excluded.status""",
            (datetime.utcnow().isoformat(), status),
        )
        conn.commit()


def get_heartbeat() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM heartbeat WHERE id = 1").fetchone()
        return dict(row) if row else None


# --- API call tracking ---

def record_api_call(endpoint: str, success: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_calls (timestamp, endpoint, success) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), endpoint, 1 if success else 0),
        )
        conn.commit()


def count_recent_api_calls(seconds: int = 60) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM api_calls
               WHERE timestamp >= datetime('now', ? || ' seconds')""",
            (f"-{seconds}",),
        ).fetchone()
        return row["cnt"]


# --- Safety events ---

def record_safety_event(event_type: str, message: str, triggered_stop: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO safety_events
               (timestamp, event_type, message, triggered_stop)
               VALUES (?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), event_type, message,
             1 if triggered_stop else 0),
        )
        conn.commit()


def get_recent_safety_events(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM safety_events ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
