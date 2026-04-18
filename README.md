# Kim and Chang Trading Technologies

Alpaca paper trading bot with a tactical Streamlit dashboard. Single-user, runs 24/7 on a Vultr VPS.

> ⚠️ **Paper trading only.** `paper=True` is hardcoded in `broker.py`. Real money is impossible by design.

**Live dashboard:** [kctrading.xyz](http://kctrading.xyz)

---

## Quick Start (Local)

**Requirements:** [UV](https://docs.astral.sh/uv/) · Alpaca paper trading account · (Optional) Telegram bot

```bash
git clone <your-repo-url> trading-bot
cd trading-bot
uv sync                    # installs Python 3.12 + all dependencies
cp .env.example .env       # fill in your Alpaca API keys
```

```bash
# Copy secrets and run
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml with your credentials
uv run streamlit run dashboard.py
```

---

## Production Deployment (Vultr VPS)

### One-time server setup

```bash
# 1. Install official UV
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 2. Clone and configure
git clone <your-repo-url> ~/trading-bot
cd ~/trading-bot
uv sync
cp .env.example .env && nano .env

# 3. Copy secrets (gitignored — must be done manually)
# From your local machine:
scp .streamlit/secrets.toml trader@<server-ip>:~/trading-bot/.streamlit/secrets.toml

# 4. Open firewall ports
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp

# 5. Install and start services
bash deploy/install.sh
```

### Routine updates

```bash
cd ~/trading-bot
git pull
sudo systemctl restart trading-bot trading-dashboard
```

Only when `deploy/*.service` files change:
```bash
sudo cp deploy/trading-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart trading-dashboard
```

---

## Dashboard

The dashboard is publicly accessible at **kctrading.xyz** (port 80, login required).

Features:
- **Portfolio equity chart** — 1W / 1M / 3M / 1Y from Alpaca portfolio history
- **Server status** — live CPU, RAM, disk, uptime via psutil
- **Open positions** — color-coded P&L
- **Trade log + bot logs** — side by side with color coding
- **Backtesting engine** — run any strategy on any symbol/date range, see equity curve with buy/sell markers
- **Kill switch** — toggle trading on/off without SSH
- **Strategy config** — switch between RSI, MACD, Bollinger Bands, EMA Crossover

For domain setup details, see `Instructions/DOMAIN.md`.

---

## Strategies

| Strategy | Style | Signal |
|---|---|---|
| RSI | Mean-reversion | RSI < oversold → buy, RSI > overbought → sell |
| MACD | Trend-following | MACD crosses above signal → buy, below → sell |
| Bollinger Bands | Mean-reversion | Price below lower band → buy, above upper band → sell |
| EMA Crossover | Trend-following | Fast EMA crosses above slow EMA → buy (golden cross), below → sell (death cross) |

### Adding a new strategy

1. Create `strategies/your_strategy.py` inheriting `BaseStrategy`
2. Add it to `STRATEGIES` in `strategies/__init__.py`
3. Add default params to `config.py`
4. Push and deploy — it appears automatically in the dashboard

---

## Common Operations

| Action | Command |
|---|---|
| Check bot status | `sudo systemctl status trading-bot` |
| Check dashboard status | `sudo systemctl status trading-dashboard` |
| Tail bot logs (live) | `journalctl -u trading-bot -f` |
| Tail bot logs (file) | `tail -f ~/trading-bot/logs/bot.log` |
| Restart both services | `sudo systemctl restart trading-bot trading-dashboard` |
| Database backup | `cp ~/trading-bot/trading.db ~/backups/trading-$(date +%F).db` |

---

## Kill Switch

1. **Dashboard** — Config section → toggle "Trading enabled" OFF. Applies on next bot cycle (≤ 1 hour).
2. **Immediate** — `sudo systemctl stop trading-bot`

Auto-safety triggers (daily loss limit, max drawdown, runaway detection) also flip the kill switch and require manual re-enable.

---

## Project Structure

```
trading-bot/
├── bot.py                  # main trading loop
├── dashboard.py            # Streamlit UI (single-page tactical layout)
├── backtest.py             # backtesting engine
├── db.py                   # SQLite layer
├── config.py               # default constants
├── safety.py               # kill switch + risk limits
├── broker.py               # Alpaca wrapper (rate limit + slippage)
├── notifications.py        # Telegram alerts
├── strategies/             # pluggable strategy modules
│   ├── rsi_strategy.py
│   ├── macd_strategy.py
│   ├── bollinger_strategy.py
│   └── ema_crossover_strategy.py
├── .streamlit/
│   ├── config.toml         # theme + server config (port 80)
│   └── secrets.toml        # login credentials (gitignored)
├── deploy/                 # systemd service files + install scripts
└── Instructions/           # build documentation + session logs
    └── sessions/           # per-session change logs
```

---

## Troubleshooting

**`203/EXEC` error on service start** — `uv` not found at expected path. Run `which uv` on the server, then update the path in the service file via `sudo nano /etc/systemd/system/trading-dashboard.service`.

**Dashboard shows "Stale"** — Bot hasn't sent a heartbeat in 70+ minutes. Check `sudo systemctl status trading-bot`.

**Can't reach kctrading.xyz** — Check UFW allows port 80 (`sudo ufw status`) and the service is running (`sudo systemctl status trading-dashboard`).

**Bot won't start** — Check `.env` has `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Run `uv run python bot.py` directly to see the error.

**Telegram alerts not arriving** — Send a message to your bot first. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

**Trading keeps turning off** — A safety check tripped. Check the Safety Events section on the dashboard.
