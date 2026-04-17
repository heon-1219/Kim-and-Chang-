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
