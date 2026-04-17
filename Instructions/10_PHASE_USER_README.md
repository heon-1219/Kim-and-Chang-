# Phase 10 — User-Facing README

> **Prerequisite**: Phases 1–9 complete.

## Goal
Write the project's `README.md` that the human user (project owner) reads to set up, run, and maintain the bot.

This is different from the build guide (these `docs/` files). The build guide is for Claude Code; the README is for the human.

## Tasks

### 1. Write `README.md` at the project root

Use the template below. Replace `<server-ip>` with the actual server IP if known, otherwise leave as a placeholder.

```markdown
# 🤖 Trading Bot

Alpaca paper trading bot with a Streamlit dashboard. Single-user, runs 24/7 on a small VPS.

> ⚠️ **Paper trading only.** This software uses Alpaca's paper trading endpoint. Real money is impossible by code design.

---

## Quick start (local)

### Requirements
- [UV](https://docs.astral.sh/uv/) installed
- Alpaca paper trading account ([sign up free](https://alpaca.markets))
- (Optional) Telegram bot for alerts

### Setup
```bash
git clone <your-repo-url> trading-bot
cd trading-bot
uv sync                    # installs Python 3.12 + all dependencies
cp .env.example .env       # then edit .env with your API keys
```

### Run locally (two terminals)
```bash
# Terminal 1
uv run python bot.py

# Terminal 2
uv run streamlit run dashboard.py
```
Dashboard: http://localhost:8501

---

## Production deployment (Vultr server)

### One-time server setup
On the server (as user `trader`):
```bash
# Install UV if not already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repo
git clone <your-repo-url> ~/trading-bot
cd ~/trading-bot
uv sync

# Configure .env
cp .env.example .env
nano .env   # paste your API keys

# Install systemd services and start
bash deploy/install.sh
```

### Access the dashboard
The dashboard binds to `127.0.0.1` only — not exposed to the internet. Open an SSH tunnel from your laptop:
```bash
ssh -L 8501:localhost:8501 trader@<server-ip>
```
Then open http://localhost:8501 in your laptop's browser.

### Updating
```bash
ssh trader@<server-ip>
cd trading-bot
bash deploy/update.sh
```

---

## Common operations

| Action | Command |
|---|---|
| Check bot status | `sudo systemctl status trading-bot` |
| Check dashboard status | `sudo systemctl status trading-dashboard` |
| Tail bot logs (live) | `journalctl -u trading-bot -f` |
| Tail bot logs (file) | `tail -f ~/trading-bot/logs/bot.log` |
| Restart bot | `sudo systemctl restart trading-bot` |
| Stop bot | `sudo systemctl stop trading-bot` |
| Database backup | `cp ~/trading-bot/trading.db ~/backups/trading-$(date +%F).db` |

---

## 🛑 Kill switch

If anything looks wrong:

1. **Quick stop** — open the dashboard, go to Config tab, toggle "Trading enabled" OFF. Bot stops on next cycle (within 1 hour).
2. **Immediate stop** — `sudo systemctl stop trading-bot` (server) or `Ctrl+C` (local).

The bot's auto-safety triggers (daily loss limit, max drawdown, runaway trade detection) will also flip the kill switch and require manual re-enable. This is intentional.

---

## Project structure

```
trading-bot/
├── bot.py            # main loop
├── dashboard.py      # Streamlit UI
├── db.py             # SQLite layer
├── config.py         # default constants
├── safety.py         # kill switch + risk limits
├── broker.py         # Alpaca wrapper (rate limit + slippage)
├── notifications.py  # Telegram alerts
├── strategies/       # pluggable strategies
├── deploy/           # systemd files + install scripts
└── docs/             # build documentation
```

---

## Adding a new strategy

1. Create `strategies/your_strategy.py` with a class inheriting `BaseStrategy`.
2. Add it to `STRATEGIES` dict in `strategies/__init__.py`.
3. Commit, push, deploy. Pick it from the dashboard's strategy selector.

See `strategies/rsi_strategy.py` for a reference implementation.

---

## Important notes

- The bot reads its config from the database on every cycle, so dashboard changes apply within an hour without restart.
- `paper=True` is hardcoded in `broker.py`. Do NOT change it. The whole project is built around the assumption that no real money is at risk.
- API keys live in `.env` — never commit this file.
- The default RSI strategy is for learning, not for making money.

---

## Troubleshooting

**Bot won't start**: Check `.env` has both `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Run `uv run python bot.py` directly to see the error.

**Dashboard shows "Stale"**: Bot hasn't sent a heartbeat in 70+ minutes. Check `sudo systemctl status trading-bot`.

**Telegram alerts not arriving**: First, you need to send a message to your bot before it can DM you. Then verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

**Trading enabled keeps turning off**: A safety check tripped. Look at the Safety tab in the dashboard for the reason.
```

### 2. Move build docs to keep repo clean
The `docs/` folder (these phase files) can stay in the repo as a reference for future Claude Code sessions, or you can move them out. Either is fine — they're not loaded at runtime.

---

## Verification

After writing the README:

```bash
# 1. README exists at root
ls README.md
# Expected: README.md

# 2. README mentions paper trading prominently
grep -i "paper" README.md | head -5
# Expected: multiple matches

# 3. README does NOT mention real money trading instructions
grep -i "real money" README.md
# Expected: only in disclaimers/warnings, never in setup instructions

# 4. README links to UV
grep "uv" README.md | head -3
# Expected: matches

# 5. README has SSH tunnel instructions
grep -i "ssh -L" README.md
# Expected: at least one match
```

If all 5 checks pass, Phase 10 is complete.

**Now run the final verification in `CHECKLIST.md`.**
