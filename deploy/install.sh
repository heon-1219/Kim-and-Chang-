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
