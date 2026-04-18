# Session 0418 — Internet Exposure, Auth, UI Redesign, Backtesting

**Date:** 2026-04-18  
**Domain:** The project is now publicly accessible at **kctrading.xyz** (GoDaddy domain, A record pointing to the Vultr VPS public IP). For setup details, see `Instructions/DOMAIN.md`.

---

## What We Did

### 1. Exposed the Dashboard to the Internet

The original design bound Streamlit to `127.0.0.1` (localhost only), accessible only via SSH tunnel. We changed this to allow public access with authentication.

**Approach chosen:** Streamlit's session-state login form with `bcrypt` password hashing and credentials stored in `.streamlit/secrets.toml` (gitignored).

- Added `bcrypt` dependency (`uv add bcrypt`)
- Created `.streamlit/secrets.toml` with hashed credentials (gitignored)
- Created `.streamlit/secrets.toml.example` as a template for server deployment
- Updated `dashboard.py` to gate all content behind `_check_login()`
- Changed `deploy/trading-dashboard.service` to bind on `0.0.0.0`
- Updated `CLAUDE.md` to document the new security model

**Login credentials:**
- Username: `kimandchang`
- Password: stored as bcrypt hash in `.streamlit/secrets.toml` on the server

**To deploy secrets to a new server:**
```bash
scp .streamlit/secrets.toml trader@<vps-ip>:~/trading-bot/.streamlit/secrets.toml
```

---

### 2. Switched UV from Snap to Official Installer

The VPS had `uv` installed via snap (`/snap/bin/uv`), but the service files expected it at `/home/trader/.local/bin/uv`. This caused `status=203/EXEC` errors.

**Fix:**
```bash
sudo snap remove astral-uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

The service files already reference `/home/trader/.local/bin/uv` — no changes needed after reinstall.

---

### 3. Port 80 — Direct Domain Access

Instead of running on port 8501 and using a reverse proxy, we chose to bind Streamlit directly to port 80.

- Moved server config (`port`, `address`, `headless`) into `.streamlit/config.toml`
- Added `AmbientCapabilities=CAP_NET_BIND_SERVICE` to the systemd service so the `trader` user can bind to port 80 without running as root
- Opened port 80 in UFW: `sudo ufw allow 80/tcp`

**When the service file changes**, copy it to systemd manually:
```bash
sudo cp deploy/trading-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart trading-dashboard
```
This is only needed when the service file itself changes — not on every code update.

---

### 4. Added Three New Trading Strategies

All strategies inherit from `BaseStrategy` and live in `strategies/`.

| File | Strategy | Style | Signal Logic |
|---|---|---|---|
| `macd_strategy.py` | MACD | Trend-following | Buy when MACD crosses above signal line, sell when it crosses below |
| `bollinger_strategy.py` | Bollinger Bands | Mean-reversion | Buy below lower band, sell above upper band |
| `ema_crossover_strategy.py` | EMA Crossover | Trend-following | Buy on golden cross (fast EMA > slow EMA), sell on death cross |

Registered in `strategies/__init__.py`. Selectable from the dashboard's Config section with Korean descriptions.

Default parameters added to `config.py`:
- MACD: fast=12, slow=26, signal=9
- Bollinger: window=20, std=2.0
- EMA Crossover: fast=9, slow=21

---

### 5. Full Dashboard Redesign — Single Page, Tactical

Replaced the tabbed layout with a single scrollable page styled after professional trading terminals (TradingView / Bloomberg aesthetic).

**Added dependencies:** `plotly`, `psutil`

**Layout (top to bottom):**
1. **Header** — "KIM AND CHANG / TRADING TECHNOLOGIES" + live status bar (bot alive/stale, trading on/off, active strategy, timestamp) + Refresh / Logout buttons
2. **Account Metrics** — 4 cards: Equity, Cash, Buying Power, Today P&L (with % delta)
3. **Portfolio Equity Chart** (from Alpaca `get_portfolio_history`) with 1W/1M/3M/1Y period selector, color changes green/red based on performance
4. **System Status panel** — live CPU/RAM/Disk bar charts via `psutil`, server uptime, API call counter, kill switch toggle
5. **Open Positions** — color-coded P&L columns
6. **Recent Trades | Bot Logs** — side by side; trades color buy/sell, logs color ERROR/WARN/INFO
7. **Backtesting Engine** — see section below
8. **Safety Events** — compact
9. **Configuration** — collapsible expander with kill switch, strategy selector + Korean descriptions, per-strategy parameters, risk limits

**CSS highlights:**
- Left-accent metric cards (`border-left: 3px solid #00d4aa`)
- Plotly charts with `paper_bgcolor="#0a0e1a"`, teal/red fill depending on P&L direction
- Monospace font for all numeric values
- Mobile: 4 metric columns collapse to 2×2 grid via CSS media query
- Sidebar hidden — everything on the main page

**Theme** (`.streamlit/config.toml`):
```toml
primaryColor = "#00d4aa"
backgroundColor = "#0a0e1a"
secondaryBackgroundColor = "#111827"
```

---

### 6. Backtesting Engine

New file: `backtest.py`

**How it works:**
1. User inputs: symbol, strategy, date range, starting capital
2. Fetches daily OHLCV bars from Alpaca (`StockBarsRequest`, `adjustment="all"`)
3. Fetches extra lookback days before `start` for indicator warm-up (no look-ahead bias — signal computed from prices *before* each bar)
4. Simulates all-in/all-out trades with slippage applied
5. Calculates metrics: Total Return, Sharpe Ratio, Max Drawdown, Win Rate, Profit Factor, Trade Count
6. Returns equity curve DataFrame + trades list + metrics dict

**Dashboard integration:**
- Results stored in `st.session_state["bt_result"]` (persist across reruns)
- Plotly equity curve with ▲ buy / ▼ sell markers overlaid
- Dashed reference line at starting capital
- Trade log table below the chart
- Color of chart fill changes based on overall return (green/red)

**`broker.py` addition:** `get_portfolio_history(period, timeframe)` wrapping Alpaca's `GetPortfolioHistoryRequest`

---

## Files Changed

| File | Change |
|---|---|
| `dashboard.py` | Full rewrite — single page, tactical UI, backtesting section, server status |
| `backtest.py` | New — backtesting engine |
| `broker.py` | Added `get_portfolio_history()` |
| `config.py` | Added MACD, Bollinger, EMA Crossover default params |
| `strategies/__init__.py` | Registered 3 new strategies |
| `strategies/macd_strategy.py` | New |
| `strategies/bollinger_strategy.py` | New |
| `strategies/ema_crossover_strategy.py` | New |
| `.streamlit/config.toml` | New — dark theme + port 80 server config |
| `.streamlit/secrets.toml` | New (gitignored) — login credentials |
| `.streamlit/secrets.toml.example` | New — template for server deployment |
| `deploy/trading-dashboard.service` | Port 80, AmbientCapabilities, simplified ExecStart |
| `pyproject.toml` | Added bcrypt, plotly, psutil |
| `CLAUDE.md` | Updated internet exposure constraint |
| `.gitignore` | Added `.streamlit/secrets.toml` |

---

## Dashboard v8.0 — Additional Changes (same session, continued)

### 7. Header Fix
Restructured header as `st.columns([7, 3])`. Right side uses `st.columns([3, 1, 1])` so user info, ↺ refresh button, and ⏻ logout button all render in the same visual row as the title — previously they were being pushed below the header by Streamlit's layout engine.

### 8. Bot Logs Relocation
Moved Bot Logs container into the main right column, between Server+Safety and the bottom divider (`height=120`). The bottom section now contains only Backtest and Configuration.

### 9. Strategy Capital Allocation UI
Added to the Configuration panel:
- Per-strategy rows with checkbox (enable/disable) + `st.number_input` for allocation %
- Total allocated metric shown in real time; warns if > 100 %
- Saved as `json.dumps(new_alloc)` under db key `"strategy_allocation"`, where `new_alloc` is `{strat_key: {"enabled": bool, "alloc_pct": int}}`
- On save, `active_strategy` is set to the first enabled strategy (for the current single-strategy bot.py)
- **Parallel bot execution not yet implemented** — the UI is complete but bot.py still runs a single strategy

### 10. Portfolio Equity — Strategy Trade Markers & Comparison
- `_equity_fig()` accepts `show_strats: list[str]` and overlays coloured dots at trade timestamps using `pd.Series.interpolate("time")` to find the equity value at each trade time
- Multiselect widget above the chart lets the user pick which strategies to overlay
- Backtest comparison: "＋ Compare" button saves result to `st.session_state["bt_compare"]`; all stored curves are overlaid on one Plotly chart with distinct colours

### 11. Manual Trade Panel ("No Strategy")
New container below Backtest Engine:
- Symbol text input + quantity + Buy/Sell radio → **Submit Paper Order** button
- Uses `MarketOrderRequest` / `broker.submit_order()` — paper only
- Disabled in demo mode

### 12. ? Help Popovers
`_panel_header(title, help_md)` helper: when `help_md` is provided, renders a `st.popover("?")` button at the top-right of the panel header via an 11:1 column split.
Applied to: Portfolio Equity, Trade Activity, Open Positions, Bot Logs, Backtest Engine, Manual Trade, Configuration.

### 13. `hovermode` Duplicate-Keyword Bug Fix
`_CHART` dict already contained `hovermode="x unified"`. The `_trades_fig()` bar chart needed `"closest"` instead. Fixed by building `chart_cfg = {**_CHART, "hovermode": "closest"}` and spreading that, rather than passing `hovermode` as an explicit kwarg alongside `**_CHART`.

---

## Files Changed (v8.0 additions)

| File | Change |
|---|---|
| `dashboard.py` | v8.0 rewrite — header fix, bot logs relocation, strategy allocation, equity overlays, backtest compare, manual trade panel, ? popovers, hovermode fix |

---

## VPS Deploy Checklist (after each push)

```bash
# On the VPS
cd ~/trading-bot
git pull
sudo systemctl restart trading-bot trading-dashboard
```

Only needed when service files change:
```bash
sudo cp deploy/trading-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Only needed once (already done):
```bash
sudo ufw allow 80/tcp
sudo ufw allow 22/tcp
```
