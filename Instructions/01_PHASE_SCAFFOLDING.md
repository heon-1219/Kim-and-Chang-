# Phase 1 — Project Scaffolding

> **Prerequisite**: Read `00_OVERALL_PLAN.md` first.

## Goal
Set up the project skeleton with UV and create empty stubs for all module files.

## Tasks

### 1. Create directory structure
```
trading-bot/
├── strategies/
├── deploy/
└── docs/
```

### 2. Write `pyproject.toml`
```toml
[project]
name = "trading-bot"
version = "0.1.0"
description = "Alpaca paper trading bot with Streamlit dashboard"
requires-python = ">=3.12"
dependencies = [
    "alpaca-py>=0.30.0",
    "pandas>=2.2.0",
    "streamlit>=1.40.0",
    "ta>=0.11.0",
    "python-dotenv>=1.0.0",
    "requests>=2.32.0",
]
```

### 3. Write `.python-version`
Single line: `3.12`

### 4. Write `.gitignore`
Must include at minimum:
```
.env
*.db
*.db-journal
*.db-wal
*.db-shm
__pycache__/
*.pyc
.venv/
*.log
.DS_Store
.uv/
```

### 5. Write `.env.example`
```
# Alpaca paper trading API keys
# Get from: https://app.alpaca.markets/paper/dashboard/overview
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here

# Telegram bot (optional but recommended)
# Create bot via @BotFather, get chat ID via @userinfobot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 6. Write `config.py`
Constants only — no logic. These are defaults; runtime values come from `bot_config` table.

```python
"""
Default configuration constants. Runtime values are stored in the bot_config DB table
and can be edited via the dashboard. These constants are used to seed the table on first init.
"""

# Trading targets
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA"]

# RSI strategy defaults
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 30
DEFAULT_RSI_OVERBOUGHT = 70

# Position sizing
DEFAULT_POSITION_PCT = 5.0       # % of equity per position
DEFAULT_MAX_POSITIONS = 4

# Safety limits
DEFAULT_DAILY_LOSS_LIMIT_PCT = 2.0   # auto-kill if today's loss exceeds this
DEFAULT_MAX_DRAWDOWN_PCT = 10.0      # auto-kill if drawdown exceeds this
DEFAULT_MAX_TRADES_PER_MINUTE = 5    # detect runaway loops

# Slippage simulation
DEFAULT_SLIPPAGE_BPS = 5             # 5 basis points = 0.05%

# Bot loop
LOOP_INTERVAL_SECONDS = 3600         # 1 hour
RATE_LIMIT_SLEEP_SECONDS = 30        # extra sleep when near rate limit
RATE_LIMIT_THRESHOLD = 180           # Alpaca limit is 200/min; leave 20 buffer

# Database
DB_PATH = "trading.db"

# Default active strategy
DEFAULT_ACTIVE_STRATEGY = "rsi"
```

### 7. Create empty stub files
Create these as empty files (just a docstring) so the directory structure is correct:
- `bot.py`
- `dashboard.py`
- `db.py`
- `safety.py`
- `broker.py`
- `notifications.py`
- `strategies/__init__.py`
- `strategies/base.py`
- `strategies/rsi_strategy.py`

Each empty file should contain only a one-line docstring describing its purpose.

### 8. Run `uv sync`
This creates `.venv` and installs all dependencies.

---

## Verification

Run these commands and confirm the expected output:

```bash
uv sync
# Expected: completes without errors

uv run python --version
# Expected: Python 3.12.x

ls trading-bot/
# Expected: pyproject.toml, .python-version, .env.example, .gitignore,
#           bot.py, dashboard.py, db.py, config.py, safety.py, broker.py,
#           notifications.py, strategies/, deploy/

uv run python -c "import config; print(config.DEFAULT_SYMBOLS)"
# Expected: ['AAPL', 'MSFT', 'GOOGL', 'TSLA']
```

If all four checks pass, Phase 1 is complete. Proceed to `02_PHASE_DATABASE.md`.
