# Phase 9 — Deployment (`deploy/`)

> **Prerequisite**: Phases 1–8 complete and tested locally.

## Goal
systemd service files for production deployment on the Vultr server.

## Tasks

### 1. Create `deploy/trading-bot.service`

```ini
[Unit]
Description=Alpaca Paper Trading Bot
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/trading-bot
EnvironmentFile=/home/trader/trading-bot/.env
ExecStart=/home/trader/.local/bin/uv run python bot.py
Restart=always
RestartSec=10
StandardOutput=append:/home/trader/trading-bot/logs/bot.log
StandardError=append:/home/trader/trading-bot/logs/bot.log

[Install]
WantedBy=multi-user.target
```

### 2. Create `deploy/trading-dashboard.service`

```ini
[Unit]
Description=Trading Bot Dashboard (Streamlit)
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/trading-bot
EnvironmentFile=/home/trader/trading-bot/.env
ExecStart=/home/trader/.local/bin/uv run streamlit run dashboard.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
Restart=always
RestartSec=10
StandardOutput=append:/home/trader/trading-bot/logs/dashboard.log
StandardError=append:/home/trader/trading-bot/logs/dashboard.log

[Install]
WantedBy=multi-user.target
```

### 3. Critical security note
The dashboard binds to `127.0.0.1` (localhost only) — **NEVER `0.0.0.0`**. The user accesses it via SSH tunnel from their laptop:
```bash
ssh -L 8501:localhost:8501 trader@<server-ip>
```
Then opens http://localhost:8501 on their laptop.

This avoids exposing the dashboard to the public internet.

### 4. Create `deploy/install.sh` — installation script

```bash
#!/usr/bin/env bash
# Installs and starts the systemd services. Run as a user with sudo on the server.
# Usage: bash deploy/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Installing systemd services from $SCRIPT_DIR..."

# Make sure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Copy service files
sudo cp "$SCRIPT_DIR/trading-bot.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/trading-dashboard.service" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable trading-bot trading-dashboard
sudo systemctl restart trading-bot trading-dashboard

echo "Services installed and started."
echo
echo "Useful commands:"
echo "  sudo systemctl status trading-bot"
echo "  sudo systemctl status trading-dashboard"
echo "  journalctl -u trading-bot -f"
echo "  tail -f $PROJECT_DIR/logs/bot.log"
```

### 5. Create `deploy/update.sh` — manual deploy script

```bash
#!/usr/bin/env bash
# Pull latest code and restart services. Run on the server.
# Usage: bash deploy/update.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Pulling latest code..."
git pull

echo "Syncing dependencies..."
uv sync

echo "Restarting services..."
sudo systemctl restart trading-bot trading-dashboard

echo "Done. Tailing bot logs (Ctrl+C to exit):"
journalctl -u trading-bot -f --since "1 minute ago"
```

### 6. Make scripts executable
The user will run:
```bash
chmod +x deploy/install.sh deploy/update.sh
```

---

## Verification

```bash
# 1. Service files are valid systemd syntax
systemd-analyze verify deploy/trading-bot.service deploy/trading-dashboard.service
# Expected: no errors (warnings about non-existent paths are OK in dev environment)

# 2. Scripts are executable
ls -l deploy/*.sh
# Expected: -rwxr-xr-x

# 3. Dashboard does NOT bind to 0.0.0.0
grep -r "0.0.0.0" deploy/
# Expected: no matches

# 4. Bot service uses correct user
grep "User=" deploy/trading-bot.service
# Expected: User=trader

# 5. Both services have Restart=always
grep "Restart=" deploy/*.service
# Expected: both files show Restart=always
```

If all 5 checks pass, Phase 9 is complete. Proceed to `10_PHASE_USER_README.md`.
