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
            ("picker_top_n", str(config.DEFAULT_PICKER_TOP_N)),
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


def get_strategy_holding(symbol: str, strategy: str) -> float:
    """Net qty held by a strategy in a symbol: sum(buys) - sum(sells) from trade log."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(
                CASE WHEN side='buy' THEN quantity ELSE -quantity END
               ), 0) AS net_qty
               FROM trades WHERE symbol=? AND strategy=?""",
            (symbol, strategy),
        ).fetchone()
        return max(float(row["net_qty"]), 0.0)


def get_strategy_trades(strategy: str) -> list[dict]:
    """All trades for a strategy, oldest first — used for FIFO cost basis math."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE strategy=? ORDER BY timestamp ASC",
            (strategy,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_strategy_open_positions(strategy: str) -> dict[str, dict]:
    """
    Reconstruct open positions per symbol for one strategy from the trade log.
    Returns {symbol: {"qty": float, "avg_cost": float}}.
    FIFO-matched: sells reduce the oldest remaining buy lots first.
    """
    lots: dict[str, list[list[float]]] = {}  # symbol -> [[qty, price], ...]
    for t in get_strategy_trades(strategy):
        sym = t["symbol"]
        qty = float(t["quantity"])
        price = float(t["simulated_price"])
        lots.setdefault(sym, [])
        if t["side"] == "buy":
            lots[sym].append([qty, price])
        elif t["side"] == "sell":
            remaining = qty
            while remaining > 1e-9 and lots[sym]:
                lot_qty, _ = lots[sym][0]
                if lot_qty <= remaining + 1e-9:
                    remaining -= lot_qty
                    lots[sym].pop(0)
                else:
                    lots[sym][0][0] = lot_qty - remaining
                    remaining = 0
    out: dict[str, dict] = {}
    for sym, sym_lots in lots.items():
        qty = sum(l[0] for l in sym_lots)
        if qty <= 1e-9:
            continue
        cost = sum(l[0] * l[1] for l in sym_lots)
        out[sym] = {"qty": qty, "avg_cost": cost / qty}
    return out


def get_strategy_realized_pnl(strategy: str) -> float:
    """FIFO-matched realised P&L from completed sell trades for one strategy."""
    lots: dict[str, list[list[float]]] = {}
    realized = 0.0
    for t in get_strategy_trades(strategy):
        sym = t["symbol"]
        qty = float(t["quantity"])
        price = float(t["simulated_price"])
        lots.setdefault(sym, [])
        if t["side"] == "buy":
            lots[sym].append([qty, price])
        elif t["side"] == "sell":
            remaining = qty
            while remaining > 1e-9 and lots[sym]:
                lot_qty, lot_price = lots[sym][0]
                matched = min(lot_qty, remaining)
                realized += matched * (price - lot_price)
                if matched >= lot_qty - 1e-9:
                    lots[sym].pop(0)
                else:
                    lots[sym][0][0] = lot_qty - matched
                remaining -= matched
    return realized


def get_strategy_equity(strategy: str, allocated_usd: float,
                        current_prices: dict[str, float]) -> float:
    """
    Total value managed by this strategy:
      allocated_usd + realised P&L + unrealised P&L on open positions.
    `current_prices` maps {symbol: latest_price} for the strategy's open positions.
    """
    realized = get_strategy_realized_pnl(strategy)
    open_pos = get_strategy_open_positions(strategy)
    unrealized = 0.0
    for sym, p in open_pos.items():
        mkt = current_prices.get(sym)
        if mkt is None:
            continue
        unrealized += p["qty"] * (mkt - p["avg_cost"])
    return float(allocated_usd) + realized + unrealized


def get_all_traded_symbols() -> list[str]:
    """Return all distinct symbols that appear in the trade log."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
        ).fetchall()
        return [r["symbol"] for r in rows]


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
