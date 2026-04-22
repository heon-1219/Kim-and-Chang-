# Session 0423 — Active Intraday Trading, S&P 500 Picker, Multi-Symbol Backtest

**Date:** 2026-04-23

The bot appeared "not trading" even when fully configured. This session diagnosed the root causes, switched the bot to intraday bars with a 5-minute loop, added a per-strategy S&P 500 symbol picker, enriched Telegram trade alerts with per-strategy equity, added a summed buy-and-hold baseline to multi-symbol backtests, and fixed a Streamlit fullscreen crash in the Backtest panel.

---

## What We Did

### 1. Diagnosed "bot doesn't actually trade"

Two compounding causes:

- `config.LOOP_INTERVAL_SECONDS = 3600` plus `TimeFrame.Day` bars in `bot.py` meant the bot ran once an hour on identical daily closes — most cycles produced no new signal.
- `_load_active_strategies` in `bot.py` silently dropped any strategy whose `alloc_usd == 0`. Checking a strategy's box in the Config panel without typing a dollar amount left it disabled with no feedback, so the bot logged "No active strategies configured — nothing to do." and sat idle.

### 2. Made the bot trade actively

- `config.LOOP_INTERVAL_SECONDS = 300` (5 min) and `DEFAULT_MAX_TRADES_PER_MINUTE = 20` (from 5 — otherwise the rate-limit safety trips once multiple strategies × many symbols are active).
- `bot.py` — `get_recent_prices` switched to **15-minute bars** via `TimeFrame(15, TimeFrameUnit.Minute)` and a `bars_needed` count. `process_symbol` now converts `required_lookback_days × 26` (6.5 hours × 4 bars/hr) to the number of intraday bars to pull.
- Dashboard save handler now auto-splits idle cash across any strategy the user enabled but left at $0, and shows a warning so the behaviour is visible.

### 3. Added a per-strategy S&P 500 symbol picker

- New `universe.py` — `get_sp500_symbols()` fetches Wikipedia via `requests` + `BeautifulSoup` (yfinance pulls in bs4 already, so no new deps). Daily-cached with a 60-name fallback list for offline runs. Returned 503 symbols on first run.
- `strategies/base.py` — added `pick_symbols(universe, n, fetch_closes, settings)` with a trivial default.
- Each concrete strategy implements its own ranking:
  - **RSI** → most oversold first.
  - **MACD** → strongest positive histogram.
  - **Bollinger** → smallest %B (deepest below lower band).
  - **EMA Crossover** → largest positive `(fast_ema − slow_ema) / price`.
- `bot.py` — a module-level `_PICKED_SYMBOLS: dict[str, (date, list[str])]` cache rebuilds once per calendar day per strategy (daily closes via `yfinance` to avoid hammering Alpaca). The manual `symbols` config list is preserved and traded **in addition** to picks.
- New `picker_top_n` config key (default 10), seeded in `db.py` and editable from the Config panel.

### 4. Enriched Telegram trade alerts

- `db.py` — added `get_strategy_open_positions`, `get_strategy_realized_pnl`, `get_strategy_equity`. Cost basis is FIFO-matched in Python over the strategy's trade log (no schema change).
- `notifications.send_trade_alert(strategy, symbol, side, qty, price, strategy_total)` sends a four-line message:
  ```
  💰 [RSI] 🟢 BUY 12 AAPL @ $183.42
  💵 Notional: $2,201.04
  🕒 2026-04-23 14:37 ET
  📊 RSI strategy total: $5,247.18
  ```
- `bot.py` computes strategy total at alert time as `allocated_usd + realised P&L + unrealised P&L on open positions`, pulling latest prices for held symbols via `get_recent_prices(..., bars_needed=1)`.

### 5. Multi-symbol backtest with buy-and-hold baseline

- `backtest.py` — `run_backtest` now accepts `symbols: str | list[str]`. Capital is split evenly, each symbol is simulated independently, equity curves and buy-and-hold curves are summed by date, and summed-curve metrics are returned.
- Dashboard Backtest panel — the "Symbol" input became "Symbols (comma-separated)"; results get an extra dashed grey trace labelled "Buy & Hold" overlaid on the strategy equity curve. Help text updated. Errors on individual tickers are surfaced as warnings, not crashes.

### 6. Fixed the Streamlit fullscreen crash

`_panel_header` in `dashboard.py` created a button with `key=f"fs_{panel_key}"` and then wrote to `st.session_state[f"fs_{panel_key}"]` on click — Streamlit forbids mutating session state at a widget key after the widget is instantiated, so the first ⤢ click in the Backtest panel raised `StreamlitAPIException: st.session_state.fs_backtest cannot be modified…`. Split the state key to `_fsstate_{panel_key}` and left the widget key alone.

### 7. "Strategy: RSI" header removed

`dashboard.py` header line no longer reads `active_strategy`; it now shows `N strategies active` where `N` counts `enabled=true` entries in `strategy_allocation`. Reflects actual multi-strategy state.

---

## Files Changed

| File | Change |
|---|---|
| `bot.py` | Rewrote for 15-min bars, daily picker cache, union with manual symbols, rich trade alert integration |
| `backtest.py` | Multi-symbol support; per-symbol sim + summed strategy curve + summed buy-and-hold baseline |
| `dashboard.py` | Fullscreen bug fix, header badge update, multi-symbol backtest input + baseline trace, Top-N picker input, enable-with-$0 auto-split + warning, save handler persists `picker_top_n` |
| `config.py` | `LOOP_INTERVAL_SECONDS=300`, `DEFAULT_MAX_TRADES_PER_MINUTE=20`, new `DEFAULT_PICKER_TOP_N=10` |
| `db.py` | Seed `picker_top_n`; new `get_strategy_trades`, `get_strategy_open_positions`, `get_strategy_realized_pnl`, `get_strategy_equity` (FIFO) |
| `notifications.py` | New `send_trade_alert`; ET-zoned timestamp |
| `strategies/base.py` | Added `pick_symbols` with a trivial default |
| `strategies/rsi_strategy.py` | `pick_symbols` — rank by RSI ascending |
| `strategies/macd_strategy.py` | `pick_symbols` — rank by histogram descending |
| `strategies/bollinger_strategy.py` | `pick_symbols` — rank by %B ascending |
| `strategies/ema_crossover_strategy.py` | `pick_symbols` — rank by fast-over-slow spread |
| `universe.py` | **New** — S&P 500 fetch (Wikipedia via requests+bs4) with daily cache and fallback list |
| `README.md` | Sections updated (dashboard, strategies, kill switch, project tree) |

---

## Verification

- `uv run python -c "import universe; print(len(universe.get_sp500_symbols()))"` → 503 ✓
- Syntax / import smoke across all touched modules ✓
- Multi-symbol backtest (`AAPL, MSFT`, RSI, 2024-01-01 → 2024-03-01, $100k) returned summed equity (42 rows) and summed buy-and-hold (42 rows) ✓
- FIFO strategy equity math: 10@100 + 10@110 buys, 15@120 sell, alloc $5000, current $130 → realized $250, open 5 @ avg $110, unrealized $100, equity $5,350 ✓

---

## Still Needs Live Verification

- Telegram round-trip during a real trade (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` must be set).
- First live intraday cycle during US market hours — confirm 15-min bar fetch, per-strategy picks appear in logs, and `trades` table grows.
- Dashboard ⤢ toggle on Backtest panel post-fix.
