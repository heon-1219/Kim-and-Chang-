"""
Kill switch and risk limit enforcement. Called before every potential order.
"""

from datetime import datetime, timedelta

import db
import notifications


def check_can_trade(account, recent_trades: list[dict]) -> tuple[bool, str]:
    # Check 1: Master kill switch
    if db.get_config("trading_enabled", "true").lower() != "true":
        return (False, "Trading disabled by kill switch")

    # Check 2: Daily loss limit
    limit_pct = float(db.get_config("daily_loss_limit_pct", "2.0"))
    last_equity = float(account.last_equity)
    current_equity = float(account.equity)
    if last_equity > 0:
        daily_pnl_pct = ((current_equity - last_equity) / last_equity) * 100
        if daily_pnl_pct <= -limit_pct:
            db.set_config("trading_enabled", "false")
            msg = f"Daily loss limit hit: {daily_pnl_pct:.2f}% (limit: -{limit_pct}%)"
            db.record_safety_event("daily_loss_hit", msg, triggered_stop=True)
            notifications.send_alert(msg, "critical")
            return (False, msg)

    # Check 3: Max drawdown
    peak = float(db.get_config("peak_equity", "0") or 0)
    current = float(account.equity)
    if current > peak:
        db.set_config("peak_equity", str(current))
        peak = current
    if peak > 0:
        drawdown_pct = ((current - peak) / peak) * 100
        limit = float(db.get_config("max_drawdown_pct", "10.0"))
        if drawdown_pct <= -limit:
            db.set_config("trading_enabled", "false")
            msg = f"Max drawdown hit: {drawdown_pct:.2f}% (limit: -{limit}%)"
            db.record_safety_event("max_drawdown_hit", msg, triggered_stop=True)
            notifications.send_alert(msg, "critical")
            return (False, msg)

    # Check 4: Trade rate limit (runaway loop detection)
    cutoff = datetime.utcnow() - timedelta(seconds=60)
    recent_count = sum(
        1 for t in recent_trades
        if datetime.fromisoformat(t["timestamp"]) > cutoff
    )
    limit = int(db.get_config("max_trades_per_minute", "5"))
    if recent_count > limit:
        db.set_config("trading_enabled", "false")
        msg = f"Trade rate limit hit: {recent_count} trades in last 60s (limit: {limit})"
        db.record_safety_event("rate_limit_hit", msg, triggered_stop=True)
        notifications.send_alert(msg, "critical")
        return (False, msg)

    return (True, "")
