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


def _send(text: str, parse_mode: str | None = None) -> bool:
    """Low-level send to Telegram. Returns False silently if unconfigured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print(f"[NOTIFICATIONS] Skipping (no Telegram config):\n{text}")
        return False
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        try:
            db.log("ERROR", f"Telegram send failed: {e}")
        except Exception:
            pass
        return False


def send_alert(message: str, level: str = "info") -> bool:
    prefix = _PREFIXES.get(level, "ℹ️")
    return _send(f"{prefix} {message}", parse_mode="Markdown")


def send_trade_alert(strategy: str, symbol: str, side: str, qty: float,
                     price: float, strategy_total: float) -> bool:
    """Rich multi-line trade alert with strategy, qty, price, ET time, total asset."""
    notional   = qty * price
    now_et     = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    side_emoji = "🟢" if side.lower() == "buy" else "🔴"
    qty_str    = f"{qty:g}"
    text = (
        f"💰 [{strategy.upper()}] {side_emoji} {side.upper()} {qty_str} {symbol} @ ${price:,.2f}\n"
        f"💵 Notional: ${notional:,.2f}\n"
        f"🕒 {now_et}\n"
        f"📊 {strategy.upper()} strategy total: ${strategy_total:,.2f}"
    )
    return _send(text)


def send_premarket_picks(picks_by_strategy: dict[str, list[str]],
                         minutes_until_open: int) -> bool:
    """Sent ~30 min before the bell with each strategy's picks for the day."""
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    lines = [
        "🌅 Pre-market warmup",
        f"🕒 {now_et}  ·  opens in ~{minutes_until_open} min",
        "",
    ]
    if not picks_by_strategy:
        lines.append("No active strategies — nothing to pick.")
    else:
        for strat, picks in picks_by_strategy.items():
            syms = ", ".join(picks) if picks else "(none)"
            lines.append(f"• {strat.upper()} → {syms}")
    return _send("\n".join(lines))


def send_market_open(strategy_names: list[str]) -> bool:
    """Sent the moment the market opens — confirms the bot is actively trading."""
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    strat_txt = (", ".join(s.upper() for s in strategy_names)
                 if strategy_names else "(none enabled)")
    text = (
        "🔔 Market open — trading live\n"
        f"🕒 {now_et}\n"
        f"📈 Strategies active: {strat_txt}"
    )
    return _send(text)


def send_market_close(sells_today: int, pnl_today: float | None = None) -> bool:
    """Sent at the close bell — brief end-of-day recap."""
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    pnl_line = (f"\n💵 Today P&L: ${pnl_today:+,.2f}" if pnl_today is not None else "")
    text = (
        "🌇 Market closed\n"
        f"🕒 {now_et}\n"
        f"📊 Trades executed today: {sells_today} sells"
        f"{pnl_line}"
    )
    return _send(text)


def send_backtest_result(
    strategy: str,
    symbols: list[str],
    interval: str,
    start: str,
    end: str,
    metrics: dict,
    buy_and_hold_return_pct: float | None,
) -> bool:
    """
    Backtest summary: strategy stats + comparison vs buy-and-hold.
    `metrics` follows the dict returned by `backtest.run_backtest()["metrics"]`.
    """
    strat_return = float(metrics.get("total_return_pct", 0.0))
    verdict = ""
    if buy_and_hold_return_pct is not None:
        diff = strat_return - buy_and_hold_return_pct
        if diff > 0.01:
            verdict = (f"✅ Beats buy-and-hold by {diff:+.2f}pp "
                       f"({strat_return:+.2f}% vs {buy_and_hold_return_pct:+.2f}%)")
        elif diff < -0.01:
            verdict = (f"❌ Underperforms buy-and-hold by {diff:+.2f}pp "
                       f"({strat_return:+.2f}% vs {buy_and_hold_return_pct:+.2f}%) "
                       f"— would have been better to just hold.")
        else:
            verdict = (f"🟰 Matches buy-and-hold "
                       f"({strat_return:+.2f}% vs {buy_and_hold_return_pct:+.2f}%)")
    now_et  = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    sym_txt = ", ".join(symbols) if len(symbols) <= 6 else f"{len(symbols)} symbols"
    pf      = metrics.get("profit_factor", "∞")
    lines = [
        f"🔬 Backtest — {strategy.upper()}",
        f"📅 {start} → {end}  ·  bars: {interval}",
        f"🎯 Symbols: {sym_txt}",
        "",
        f"💰 Return: {strat_return:+.2f}%  "
        f"(${metrics.get('final_equity',0):,.2f} from "
        f"${metrics.get('starting_capital',0):,.2f})",
        f"📈 Sharpe: {metrics.get('sharpe_ratio',0):.2f}  ·  "
        f"Max DD: {metrics.get('max_drawdown_pct',0):.2f}%",
        f"🎲 Trades: {metrics.get('total_trades',0)}  ·  "
        f"Win: {metrics.get('win_rate_pct',0):.0f}%  ·  PF: {pf}",
    ]
    if verdict:
        lines += ["", verdict]
    lines += ["", f"🕒 {now_et}"]
    return _send("\n".join(lines))


def send_startup() -> bool:
    return send_alert("Bot started in PAPER TRADING mode", "info")


def send_shutdown() -> bool:
    return send_alert("Bot shutting down", "info")
