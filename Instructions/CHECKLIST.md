# Final Checklist

> Run after Phase 10 is complete. Every box must be checked before declaring the project done.

---

## Setup integrity

- [ ] `uv sync` completes cleanly on a fresh clone
- [ ] `.env.example` has all required keys with placeholder values
- [ ] `.gitignore` includes `.env`, `*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm`, `__pycache__/`, `.venv/`, `*.log`
- [ ] `git status` on a fresh setup shows `.env` and `trading.db` as untracked (or ignored)
- [ ] All 6 module files present: `bot.py`, `dashboard.py`, `db.py`, `config.py`, `safety.py`, `broker.py`, `notifications.py`
- [ ] `strategies/` contains `__init__.py`, `base.py`, `rsi_strategy.py`
- [ ] `deploy/` contains both `.service` files plus `install.sh` and `update.sh`

## Safety guarantees

- [ ] `grep -r "paper=" .` returns ONLY `paper=True`, never `paper=False`
- [ ] `grep -r "0.0.0.0" deploy/` returns no matches
- [ ] No use of `eval()` or `exec()` anywhere in the codebase
- [ ] No bare `except:` clauses (verify with `grep -rn "except:" .`)
- [ ] `.env` is never read or referenced in any committed file except `.env.example`

## Functionality — bot

- [ ] Bot starts cleanly with valid `.env` and prints "PAPER TRADING" on startup
- [ ] Bot sends Telegram startup alert (or skips silently if Telegram not configured)
- [ ] Bot updates heartbeat on every cycle
- [ ] Bot logs cycle start and end
- [ ] Bot respects market clock (logs "Market closed" outside hours)
- [ ] Bot respects `trading_enabled = false` (logs safety stop)
- [ ] Bot survives a network error mid-cycle (caught + logged + continues)
- [ ] Bot exits cleanly with helpful message when `.env` is missing required keys

## Functionality — dashboard

- [ ] `streamlit run dashboard.py` starts without errors
- [ ] All 5 tabs render with empty DB (no trades, no logs)
- [ ] All 5 tabs render after a few trades have been made
- [ ] Sidebar shows correct bot status (alive/stale based on heartbeat age)
- [ ] Sidebar shows correct API call count with color thresholds
- [ ] Toggling kill switch in Config tab persists in DB and reflects on reload
- [ ] Saving settings updates `bot_config` table for ALL fields
- [ ] Strategy selector populates from `STRATEGIES` registry (currently shows `rsi`)
- [ ] Account metrics display correctly when Alpaca is reachable

## Safety system

- [ ] Setting `trading_enabled = false` halts trading on next cycle
- [ ] Daily loss exceeding limit triggers kill switch + Telegram alert
- [ ] Drawdown exceeding limit triggers kill switch + Telegram alert
- [ ] Excessive trades-per-minute triggers kill switch + Telegram alert
- [ ] Each safety event creates a row in `safety_events` table
- [ ] Auto-triggered kill switches do NOT auto-recover (require manual re-enable)

## Database

- [ ] All 6 tables exist after `init_db()`: `trades`, `bot_log`, `bot_config`, `heartbeat`, `api_calls`, `safety_events`
- [ ] WAL mode is enabled (`PRAGMA journal_mode;` returns `wal`)
- [ ] Default config has all 12 keys
- [ ] Re-running `init_db()` does NOT overwrite user changes to `bot_config`
- [ ] Indexes exist on timestamp columns

## Strategy system

- [ ] `STRATEGIES` registry contains at least `rsi`
- [ ] `RSIStrategy.signal()` returns `'buy'` on oversold, `'sell'` on overbought, `'hold'` otherwise
- [ ] `RSIStrategy.required_lookback_days()` accounts for the period setting
- [ ] Adding a new strategy requires only: new file + add to registry (verify by mentally walking through it)

## Broker wrapper

- [ ] All Alpaca calls go through `broker.py` (search for `trading_client.` or `data_client.` outside `broker.py` should return nothing)
- [ ] Every wrapped call records to `api_calls` table
- [ ] `is_rate_limited()` returns `True` when count exceeds threshold
- [ ] `apply_slippage()` returns higher price for buy, lower for sell
- [ ] `get_open_position(symbol)` returns `None` (not raises) when symbol isn't held

## Deployment files

- [ ] Both `.service` files reference `/home/trader/trading-bot` paths
- [ ] Both `.service` files use `User=trader`
- [ ] Both `.service` files have `Restart=always`
- [ ] Dashboard service uses `--server.address 127.0.0.1` (not `0.0.0.0`)
- [ ] `install.sh` and `update.sh` are executable
- [ ] `install.sh` creates `logs/` directory
- [ ] README documents the SSH tunnel command for accessing the dashboard

## Documentation

- [ ] `README.md` at project root is the user-facing readme (Phase 10 output)
- [ ] `README.md` mentions paper trading prominently
- [ ] `README.md` has setup instructions for both local and production
- [ ] `README.md` has SSH tunnel command
- [ ] `README.md` has kill switch instructions
- [ ] `docs/` folder is preserved (or removed) — either is acceptable

## Telegram (if configured)

- [ ] Startup sends an alert
- [ ] Each trade sends an alert with `trade` level
- [ ] Each safety event sends an alert with `critical` level
- [ ] Errors send alerts with `error` level
- [ ] Missing Telegram config does NOT crash the bot (silent skip)

---

## Final smoke test

Run this end-to-end sequence to verify everything works together:

```bash
# 1. Start bot in terminal 1
uv run python bot.py
# Should: log startup, send Telegram alert, run a cycle

# 2. Start dashboard in terminal 2
uv run streamlit run dashboard.py
# Should: open browser, show metrics

# 3. In dashboard, go to Config, toggle "Trading enabled" OFF
# Watch terminal 1 — within 1 cycle, bot should log "Safety stop"

# 4. Toggle it back ON in dashboard
# Watch terminal 1 — bot should resume normally on next cycle

# 5. Stop bot with Ctrl+C
# Should NOT corrupt the database
sqlite3 trading.db "SELECT COUNT(*) FROM trades;"
# Should run without errors
```

If all of the above pass, the project is ready for production deployment to the Vultr server.
