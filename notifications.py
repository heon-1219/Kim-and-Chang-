"""
Telegram alert sender. Optional — bot continues without it if unconfigured.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

import db

load_dotenv()

_ET = ZoneInfo("America/New_York")

_PREFIXES = {
    "info": "ℹ️",
    "trade": "💰",
    "warning": "⚠️",
    "error": "🔴",
    "critical": "🚨",
}


def send_alert(message: str, level: str = "info") -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print(f"[NOTIFICATIONS] Skipping (no Telegram config): {message}")
        return False

    prefix = _PREFIXES.get(level, "ℹ️")
    text = f"{prefix} {message}"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        db.log("ERROR", f"Telegram alert failed: {e}")
        return False


def send_trade_alert(strategy: str, symbol: str, side: str, qty: float,
                     price: float, strategy_total: float) -> bool:
    """Rich multi-line trade alert with strategy, qty, price, ET time, total asset."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    notional = qty * price
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    side_emoji = "🟢" if side.lower() == "buy" else "🔴"
    qty_str = f"{qty:g}"

    text = (
        f"💰 [{strategy.upper()}] {side_emoji} {side.upper()} {qty_str} {symbol} @ ${price:,.2f}\n"
        f"💵 Notional: ${notional:,.2f}\n"
        f"🕒 {now_et}\n"
        f"📊 {strategy.upper()} strategy total: ${strategy_total:,.2f}"
    )

    if not token or not chat_id:
        print(f"[NOTIFICATIONS] Skipping (no Telegram config):\n{text}")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        db.log("ERROR", f"Telegram trade alert failed: {e}")
        return False


def send_startup() -> bool:
    return send_alert("Bot started in PAPER TRADING mode", "info")


def send_shutdown() -> bool:
    return send_alert("Bot shutting down", "info")
