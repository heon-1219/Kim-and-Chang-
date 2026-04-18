# Kim and Chang Trading Technologies

Alpaca paper trading bot with a single-page tactical Streamlit dashboard. Single-user, runs 24/7 on a Vultr VPS.

> ⚠️ **Paper trading only.** `paper=True` is hardcoded in `broker.py`. Real money is impossible by design.

**Live dashboard:** [kctrading.xyz](http://kctrading.xyz) · Port 80 · Login required

---

## Demo Access

A read-only demo account is available to preview the UI without exposing any real trading data or API credentials.

| | Credentials |
|---|---|
| **Demo** | username: `test` · password: `1234` |
| **Admin** | username: `kimandchang` · password: *(private)* |

The demo account shows realistic placeholder data (positions, trades, logs, equity curve). All action buttons (Backtest, Config, Safety) are disabled. No real API calls are made.

---

## Quick Start (Local)

**Requirements:** [UV](https://docs.astral.sh/uv/) · Alpaca paper trading account · (Optional) Telegram bot

```bash
git clone <your-repo-url> trading-bot
cd trading-bot
uv sync
cp .env.example .env
nano .env   # add ALPACA_API_KEY and ALPACA_SECRET_KEY
```

Copy and configure secrets:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
nano .streamlit/secrets.toml   # set username + bcrypt hash of password
```

Generate a bcrypt hash for your password:
```bash
uv run python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt(12)).decode())"
```

Run locally:
```bash
uv run streamlit run dashboard.py   # dashboard at http://localhost:80
uv run python bot.py                # trading bot (separate terminal)
```

---

## Production Deployment (Vultr VPS)

### One-time server setup

```bash
# 1. Install official UV (puts it at ~/.local/bin/uv)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 2. Clone and configure
git clone <your-repo-url> ~/trading-bot
cd ~/trading-bot
uv sync
cp .env.example .env && nano .env

# 3. Copy secrets file (gitignored — must be transferred manually)
#    Run this from your LOCAL machine:
scp .streamlit/secrets.toml trader@<server-ip>:~/trading-bot/.streamlit/secrets.toml

# 4. Open firewall ports
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # Dashboard (HTTP)

# 5. Install and start systemd services
bash deploy/install.sh
```

The dashboard runs on **port 80** directly (no reverse proxy). Streamlit binds to `0.0.0.0:80` via `AmbientCapabilities=CAP_NET_BIND_SERVICE` in the service file, so the `trader` user can bind to port 80 without running as root.

---

## Updating After a Git Push

Run these commands on the VPS after every `git push` from your local machine:

```bash
cd ~/trading-bot
git pull
uv sync                                          # install any new dependencies
sudo systemctl restart trading-bot trading-dashboard
```

**Only needed when `deploy/*.service` files change** (e.g. port, user, uv path):
```bash
sudo cp deploy/trading-dashboard.service /etc/systemd/system/
sudo cp deploy/trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart trading-bot trading-dashboard
```

**Only needed when `.streamlit/secrets.toml` changes** (credentials, demo account):
```bash
# From your LOCAL machine:
scp .streamlit/secrets.toml trader@<server-ip>:~/trading-bot/.streamlit/secrets.toml
sudo systemctl restart trading-dashboard
```

---

## Dashboard

Accessible at **kctrading.xyz** (port 80). Single-page, no-scroll tactical layout.

**Main page panels (always visible):**
- Header + live status bar (bot alive/stale, trading on/off, active strategy, API usage, timestamp)
- Account metrics: Equity, Cash, Buying Power, Today P&L
- Portfolio equity chart (1W / 1M / 3M / 1Y from Alpaca portfolio history)
- Server status: CPU, RAM, Disk, Uptime (via psutil)
- Open positions table with color-coded P&L
- Recent trades + bot logs side by side

**Accessible via modal dialogs (bottom action bar):**
- `▶ Backtest` — run any strategy on any symbol/date range, see equity curve with buy/sell markers
- `⚙️ Config` — switch strategy, edit parameters, set risk limits
- `🚨 Safety` — view safety events and kill switch status

For domain setup details, see `Instructions/DOMAIN.md`.

---

## Strategies

| Key | Name | Style | Logic |
|---|---|---|---|
| `rsi` | RSI | Mean-reversion | RSI < oversold → buy · RSI > overbought → sell |
| `macd` | MACD | Trend-following | MACD crosses above signal → buy · below → sell |
| `bollinger` | Bollinger Bands | Mean-reversion | Price below lower band → buy · above upper band → sell |
| `ema_crossover` | EMA Crossover | Trend-following | Golden cross → buy · Death cross → sell |

### Adding a new strategy
1. Create `strategies/your_strategy.py` inheriting `BaseStrategy`
2. Add it to `STRATEGIES` in `strategies/__init__.py`
3. Add default params to `config.py`
4. Push → pull → restart. It appears in the Config dialog automatically.

---

## Common Operations

| Action | Command |
|---|---|
| Check bot status | `sudo systemctl status trading-bot` |
| Check dashboard status | `sudo systemctl status trading-dashboard` |
| Tail bot logs (live) | `journalctl -u trading-bot -f` |
| Tail bot logs (file) | `tail -f ~/trading-bot/logs/bot.log` |
| Restart both services | `sudo systemctl restart trading-bot trading-dashboard` |
| View UFW firewall rules | `sudo ufw status` |
| Database backup | `cp ~/trading-bot/trading.db ~/backups/trading-$(date +%F).db` |

---

## Kill Switch

1. **Dashboard** — Config dialog → toggle "Trading enabled" OFF. Applies on next bot cycle (≤ 1 hour).
2. **Immediate** — `sudo systemctl stop trading-bot`

Auto-safety triggers (daily loss limit, max drawdown, runaway detection) also flip the kill switch and require manual re-enable.

---

## Project Structure

```
trading-bot/
├── bot.py                      # main trading loop
├── dashboard.py                # Streamlit UI — single-page, no-scroll
├── backtest.py                 # backtesting engine (Alpaca historical data)
├── db.py                       # SQLite layer
├── config.py                   # default constants
├── safety.py                   # kill switch + risk limits
├── broker.py                   # Alpaca API wrapper (rate limit + slippage)
├── notifications.py            # Telegram alerts
├── strategies/
│   ├── __init__.py             # strategy registry
│   ├── base.py                 # BaseStrategy ABC
│   ├── rsi_strategy.py
│   ├── macd_strategy.py
│   ├── bollinger_strategy.py
│   └── ema_crossover_strategy.py
├── .streamlit/
│   ├── config.toml             # dark theme + port 80 server config
│   ├── secrets.toml            # login credentials (gitignored)
│   └── secrets.toml.example   # template for server setup
├── deploy/
│   ├── trading-bot.service     # systemd service for the bot
│   ├── trading-dashboard.service  # systemd service for the dashboard
│   ├── install.sh              # one-time setup script
│   └── update.sh               # update script
└── Instructions/
    ├── DOMAIN.md               # GoDaddy → Vultr domain setup
    └── sessions/               # per-session change logs
```

---

## Troubleshooting

**`203/EXEC` on service start** — `uv` not found at `/home/trader/.local/bin/uv`. Run `which uv` on the server and edit the service file: `sudo nano /etc/systemd/system/trading-dashboard.service`.

**Can't reach kctrading.xyz** — Check `sudo ufw status` (port 80 must be allowed) and `sudo systemctl status trading-dashboard`.

**Dashboard shows stale bot** — Bot hasn't sent a heartbeat in 70+ minutes. Check `sudo systemctl status trading-bot`.

**Bot won't start** — Run `uv run python bot.py` directly to see the error. Usually a missing or malformed `.env`.

**Login says "Access denied"** — Check `secrets.toml` exists on the server at `~/trading-bot/.streamlit/secrets.toml`. Resend it with `scp` if missing.

**Telegram alerts not arriving** — Send a message to your bot first (Telegram requirement). Then verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

**Trading keeps turning off** — A safety check tripped. Check the Safety dialog on the dashboard for the reason.
