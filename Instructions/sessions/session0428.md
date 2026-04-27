# Session 2026-04-28

## Summary

Worked on Streamlit dashboard correctness and observability for the Alpaca paper trading bot:

- Fixed top account/balance display so the dashboard can show the correct available balance.
- Clarified and partially removed confusing snapshot-age UI in the header.
- Verified multi-strategy behavior and current allocation state.
- Added submitted-order visibility separate from filled-position display.
- Added log date-window filtering.
- Added opt-in dashboard auto-refresh.
- Improved Portfolio Equity and Trade Activity expanded views.
- Fixed yfinance class-share ticker formatting noise.
- Improved post-order dashboard freshness and signal logging clarity.

## Account Balance / API Snapshot Fix

Problem:

- The top Streamlit metrics did not reliably show current available balance.
- The bot had only been storing four account fields in the `account` snapshot:
  `equity`, `cash`, `buying_power`, and `last_equity`.
- Alpaca has additional account fields such as `non_marginable_buying_power`,
  `daytrading_buying_power`, `regt_buying_power`, and `portfolio_value`.

Changes:

- Added `broker.account_to_snapshot(account)` in `broker.py`.
- The serializer preserves the full Alpaca SDK account payload when possible and guarantees:
  `equity`, `portfolio_value`, `cash`, `buying_power`,
  `non_marginable_buying_power`, `daytrading_buying_power`,
  `regt_buying_power`, and `last_equity`.
- `bot.py` now uses the shared serializer for account snapshots.
- `dashboard.py` now reads available balance from:
  `non_marginable_buying_power`, falling back to `cash`, then `buying_power`.
- Dashboard can refresh the account snapshot when missing/stale or when Refresh is clicked.

Important deploy note:

- If the dashboard logs `module 'broker' has no attribute 'account_to_snapshot'`,
  the VPS is running mismatched code. Run:

```bash
cd ~/trading-bot
git pull
sudo systemctl restart trading-dashboard trading-bot
uv run python -c "import broker; print(hasattr(broker, 'account_to_snapshot'))"
```

Expected output:

```text
True
```

## Header Snapshot Age Label

Problem:

- Header showed messages like `data 15m old`, which was confusing once account refresh was added.
- This label was only diagnostic snapshot age in the API badge, not required for trading.

Change:

- Removed the data-age suffix from the API header label.
- The API badge now focuses on `API n/200`.

## Multi-Strategy Verification

Question investigated:

- Whether the bot starts trading each enabled strategy with its own assigned capital.

Findings:

- The bot supports all enabled strategies each cycle.
- It processes them sequentially in one bot loop, not OS-thread-parallel, but functionally each enabled strategy evaluates its own picks and allocation.
- Current check at one point showed an empty `strategy_allocation`, so the bot fell back to legacy:

```text
active_strategy=rsi
rsi: 100% equity
```

- Later runtime logs showed all four strategies active:

```text
strategies=['rsi', 'macd', 'bollinger', 'ema_crossover']
```

Important behavior:

- Each strategy evaluates its own picked symbols plus manual symbols.
- Only RSI bought in the sample log because RSI had buy signals.
- MACD/Bollinger/EMA mostly held; sell signals without strategy-owned positions do not submit sells.

Change:

- Bot now logs ignored signals more clearly:
  `sell signal ignored; no strategy position`
  and
  `buy signal ignored; already held`.

## Bot Service / Manual Runs

Clarified:

- If `trading-bot.service` is installed and enabled, the bot runs continuously under systemd.
- The bot itself checks market open/closed state.
- Do not run `uv run bot.py` manually while systemd is also running, because duplicate bot instances could duplicate orders.

Useful commands:

```bash
sudo systemctl status trading-bot
sudo systemctl is-enabled trading-bot
pgrep -af "bot.py"
ps -ef | grep -E "python bot.py|uv run.*bot.py" | grep -v grep
```

Start/enable service if needed:

```bash
sudo systemctl enable --now trading-bot
```

Stop service:

```bash
sudo systemctl stop trading-bot
```

## yfinance BRK.B / BF.B Warnings

Problem:

- During daily picker ranking, yfinance printed warnings like:

```text
$BRK.B: possibly delisted; no price data found
$BF.B: possibly delisted; no price data found
```

Cause:

- Yahoo Finance uses dash class tickers such as `BRK-B` and `BF-B`.
- S&P universe uses dot tickers such as `BRK.B` and `BF.B`.

Change:

- `_daily_closes_yf()` now translates dots to dashes for yfinance lookups only:
  `symbol.replace(".", "-")`.
- Alpaca trading symbols remain unchanged.

## Open Positions / Submitted Orders

Problem:

- Open Positions needed to show submitted buy/sell requests, including requests not yet concluded or not yet visible as open positions.
- `trades` was being used as both submitted-order history and position ledger.

Changes:

- Added new SQLite table `order_requests`.
- Added `db.log_order_request(...)`.
- Added `db.get_recent_order_requests(...)`.
- Bot logs submitted buy/sell requests to `order_requests`.
- Manual dashboard orders also log to `order_requests`.
- Open Positions panel now includes a `Submitted Orders` table.
- Full positions page also includes submitted orders.
- `get_recent_order_requests()` falls back to legacy `trades` rows when no new order rows exist, so older submitted trades remain visible.

Position freshness:

- Bot now refreshes account and positions again at the end of a cycle after potential order submissions.
- This helps prevent the dashboard showing stale positions right after buys/sells.

Open-position display correction:

- Strategy-specific rows no longer show `$0.00` price/value when there is no matching Alpaca open position snapshot.
- They skip rows that are only in strategy trade history but not currently in the broker position snapshot.

Note for future work:

- Order status is currently recorded at submission time only.
- Live status updates would require polling Alpaca orders, which adds API calls. Ask before implementing.

## Logs Date Filtering

Problem:

- Logs were growing too long, and the dashboard loaded a generic recent list.

Changes:

- Added `db.get_logs_for_window(start, end, limit=...)`.
- Dashboard Logs panel now has `Log date (UTC)` and displays that date's 24-hour window.
- Full logs page also has `Log date (UTC)` and loads that day's 24-hour window.

## Auto Refresh

Question:

- Whether Streamlit can stay up to date automatically without breaking things.

Decision:

- Added opt-in dashboard auto-refresh toggle rather than forcing it.
- Interval is 60 seconds.
- Implemented with a small `components.html()` script.

Reason:

- Keeps dashboard current when monitoring.
- Avoids unexpected reruns wiping in-progress config/manual-order inputs when the user is editing.
- 60 seconds should be light enough for server load, especially because most expensive reads are cached or snapshot-based.

## Portfolio Equity Expand Improvements

Problem:

- Expand previously only made the chart taller.
- Strategy trade marker overlay was not helpful for comparing performance.

Changes:

- Removed the trade-marker overlay workflow.
- Portfolio Equity panel now has selectable curves:
  - `Total Balance`
  - enabled strategy curves
- Added metric selector:
  - `$ Value`
  - `Return %`
- Expanded view now shows a comparison table:
  - Curve
  - Start
  - Latest
  - P&L
  - Return

Implementation detail:

- Added `_strategy_equity_curves(...)`.
- Curves start from each strategy's assigned USD value.
- Curves update when that strategy logs buy/sell fills.
- Between fills, the app carries positions at the latest trade price stored for that symbol.
- This is intentionally conservative because the app does not currently store historical mark-to-market valuations per strategy.

Future possible improvement:

- Store periodic per-strategy mark-to-market snapshots during the bot cycle.
- This would make strategy curves more accurate between trades, but it should be discussed before adding more data writes and price lookups.

## Trade Activity Expand Improvements

Problem:

- Expand previously only made the chart taller.

Changes:

- Compact Trade Activity now also shows:
  - Shown Trades
  - Gross Notional
  - Active Symbols
- Expanded view now adds:
  - strategy/side breakdown table
  - recent submitted order statuses

Kept layout:

- No large page restructuring.
- Details remain inside the existing Trade Activity cell.

## Verification Commands Used

Syntax checks:

```powershell
$env:UV_CACHE_DIR = '.uv-cache'
uv run python -m py_compile broker.py bot.py dashboard.py db.py pages\positions.py pages\log.py
```

DB smoke test:

```powershell
$env:UV_CACHE_DIR = '.uv-cache'
@'
import os, tempfile
import db
fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
try:
    db.DB_PATH = path
    db.init_db()
    db.log_order_request(
        'AAPL', 'buy', 2,
        requested_price=100.0,
        simulated_price=100.05,
        order_id='test',
        status='accepted',
        strategy='rsi',
        notes='smoke',
    )
    rows = db.get_recent_order_requests(limit=5)
    assert len(rows) == 1
    assert rows[0]['symbol'] == 'AAPL'
    assert rows[0]['estimated_value'] == 200.0
    print('db smoke ok')
finally:
    os.remove(path)
'@ | uv run python -
```

## Files Changed Today

- `broker.py`
- `bot.py`
- `dashboard.py`
- `db.py`
- `pages/log.py`
- `pages/positions.py`
- `Instructions/sessions/session0428.md`

## Deployment Reminder

After pushing/pulling on the VPS:

```bash
cd ~/trading-bot
git pull
sudo systemctl restart trading-bot trading-dashboard
```

Check for duplicate bot instances:

```bash
pgrep -af "bot.py"
sudo systemctl status trading-bot
```

If both a manual `uv run bot.py` and systemd service are running, stop the manual process.

