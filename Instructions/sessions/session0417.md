# Session 2026-04-17 — Full Build (Phases 1–10 + Checklist)

## What was accomplished
All 10 phases completed in a single session. The project went from empty stubs to a fully working paper trading bot.

---

## Phase outcomes

### Phase 1 — Scaffolding (already done before session)
UV project, `pyproject.toml`, `.python-version`, `.env.example`, `.gitignore`, stub files all pre-existing.

### Phase 2 — Database (`db.py`)
- Implemented full SQLite layer with WAL mode
- 6 tables: `trades`, `bot_log`, `bot_config`, `heartbeat`, `api_calls`, `safety_events`
- All required exports: `init_db`, `get_conn`, `log_trade`, `get_recent_trades`, `log`, `get_recent_logs`, `get_config`, `set_config`, `get_all_config`, `update_heartbeat`, `get_heartbeat`, `record_api_call`, `count_recent_api_calls`, `record_safety_event`, `get_recent_safety_events`
- 12 default config keys seeded via `INSERT OR IGNORE`
- All 6 verification checks passed

### Phase 3 — Notifications (`notifications.py`)
- Telegram alert sender with 5 levels: `info`, `trade`, `warning`, `error`, `critical`
- Graceful skip (prints to console, returns `False`) when `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` missing
- `send_startup()`, `send_shutdown()` helpers
- `.env` has placeholder values so check 1 required explicit empty-string override to test skip path
- All 3 verification checks passed

### Phase 4 — Safety (`safety.py`)
- `check_can_trade(account, recent_trades) -> tuple[bool, str]`
- 4 ordered checks: kill switch → daily loss limit → max drawdown → trade rate limit
- Auto-triggered kill switches write `trading_enabled=false` and require manual re-enable
- Every trigger logs to `safety_events` and sends Telegram `critical` alert
- All 3 verification checks passed

### Phase 5 — Broker (`broker.py`)
- `paper=True` hardcoded, never configurable
- `TradingClient`, `StockHistoricalDataClient`, `CryptoHistoricalDataClient` initialized from `.env`
- `track_api_call` decorator wraps all Alpaca calls and records to `api_calls` table
- `get_open_position` swallows only 404-style `APIError`, re-raises others
- `is_rate_limited()`, `apply_slippage(price, side, bps)`
- **Dependency fix**: `pytz` was missing from environment — added via `uv add pytz`
- All 4 verification checks passed

### Phase 6 — Strategies (`strategies/`)
- `base.py`: `BaseStrategy` ABC with `required_lookback_days(settings)` and `signal(prices, settings)`
- `rsi_strategy.py`: `RSIStrategy` — buy on RSI < oversold, sell on RSI > overbought, hold otherwise
- `__init__.py`: `STRATEGIES = {"rsi": RSIStrategy()}` registry
- Strategies are stateless, never call Alpaca, never place orders
- All 5 verification checks passed

### Phase 7 — Bot (`bot.py`)
- Main loop: `init_db` → startup alert → `while True` → heartbeat → `run_one_cycle()` → sleep 3600s
- `run_one_cycle`: loads settings from DB → account + safety check → market clock check → rate limit check → process each symbol
- Per-symbol isolation: each symbol wrapped in `try/except` so one failure doesn't kill the cycle
- `place_buy` / `place_sell`: slippage simulation, order submission, DB log, Telegram alert
- `get_recent_prices`: fetches daily bars via `broker.get_stock_bars`
- `calculate_quantity`: integer shares from % of equity
- All 5 verification checks passed (check 1 confirmed via DB logs after timeout)

### Phase 8 — Dashboard (`dashboard.py`)
- Streamlit, wide layout
- Sidebar: bot heartbeat status (alive/stale/not-run), API call count with color thresholds, refresh button
- Top: 4 account metrics (equity, cash, buying power, today P&L)
- 5 tabs: Positions (live Alpaca) / Trades (DB) / Logs (DB, filterable) / Safety Events (DB) / Config
- Config tab: kill switch toggle (immediate write + rerun), strategy selector, symbols, RSI params, risk params, save button
- Dashboard **never calls `submit_order()`**
- HTTP 200 confirmed on healthz endpoint
- All 5 verification checks passed

### Phase 9 — Deploy (`deploy/`)
- `trading-bot.service`: systemd unit for `bot.py`, `Restart=always`, logs to `logs/bot.log`
- `trading-dashboard.service`: binds to `127.0.0.1:8501` only (never `0.0.0.0`)
- `install.sh`: creates `logs/`, copies service files, `systemctl enable + restart`
- `update.sh`: `git pull` → `uv sync` → `systemctl restart` → tail logs
- Both scripts chmod'd executable
- All 5 verification checks passed

### Phase 10 — README (`README.md`)
- User-facing doc at project root
- Covers: quick local start, production setup, common ops table, kill switch instructions, project structure, adding a strategy, troubleshooting
- SSH tunnel command documented: `ssh -L 8501:localhost:8501 trader@<server-ip>`
- Paper trading warning prominent at top
- All 5 verification checks passed

---

## Final checklist — all items passed

Key confirms:
- `paper=True` only, never `paper=False` in source
- No `0.0.0.0` in deploy
- No `eval()`/`exec()` in source
- No bare `except:` in source
- All Alpaca calls isolated to `broker.py`
- WAL mode confirmed
- 12 seeded config keys (+ `peak_equity` added at runtime by safety layer — expected)
- All service files use `User=trader`, `Restart=always`, `127.0.0.1`

---

## Notable issues encountered

| Issue | Resolution |
|---|---|
| `pytz` not installed | `uv add pytz` — alpaca-py data module requires it |
| Phase 5 check 1 output not captured on Windows | Confirmed via DB logs after run |
| Phase 3 check 1: `.env` placeholder values loaded by `dotenv` | Tested with explicit `os.environ['KEY'] = ''` override |
| Config key count 13 vs expected 12 | `peak_equity` is runtime-written by safety layer, not a seeded default — expected |

---

## Production deployment (not yet done)
The Vultr VPS is provisioned but the bot has not been deployed yet. Steps when ready:
```bash
ssh trader@<server-ip>
git clone <repo-url> ~/trading-bot
cd ~/trading-bot && uv sync
cp .env.example .env && nano .env
bash deploy/install.sh
```

## Questions asked during session
- **"When and where should I be putting my Alpaca API key?"** → `.env` file, copied from `.env.example`. Keys are read in Phase 5 (`broker.py`) via `python-dotenv`. Never commit `.env`.
- **"Will this chat log be saved?"** → No. Code files, DB, and `instructions/` are saved. New sessions re-read `CLAUDE.md` for context.
