"""
Event-driven backtester. Uses yfinance for historical data — free, no subscription needed.
"""

from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

import broker
from strategies import STRATEGIES


def _fetch_closes(symbol: str, fetch_start: datetime, end: date) -> pd.Series:
    end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
    ticker = yf.Ticker(symbol)
    raw = ticker.history(
        start=fetch_start.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        auto_adjust=True,
    )
    if raw.empty:
        raise ValueError(
            f"No price data for {symbol}. Check the ticker symbol and date range."
        )
    closes = raw["Close"].dropna()
    # Strip timezone — use .date to keep the calendar date regardless of offset
    closes.index = pd.to_datetime([d.date() for d in closes.index])
    return closes


def run_backtest(
    symbol: str,
    strategy_name: str,
    start: date,
    end: date,
    starting_capital: float,
    settings: dict,
) -> dict:
    """
    Run a backtest on a single symbol.

    Returns dict with keys:
        equity_curve  — pd.DataFrame(date, equity)
        trades        — list[dict]
        metrics       — dict of performance stats
    """
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    lookback    = strategy.required_lookback_days(settings) + 5
    fetch_start = datetime(start.year, start.month, start.day) - timedelta(days=lookback)
    closes      = _fetch_closes(symbol, fetch_start, end)

    trade_start  = pd.Timestamp(start)
    slippage_bps = int(settings.get("slippage_bps", 5))

    capital     = float(starting_capital)
    position    = 0.0
    entry_price = 0.0
    trades      = []
    equity_rows = []

    for i in range(len(closes)):
        ts    = closes.index[i]
        close = float(closes.iloc[i])

        if ts < trade_start:
            continue

        equity = capital + position * close
        equity_rows.append({"date": ts, "equity": equity})

        if i == 0:
            continue

        # Signal uses prices BEFORE current bar — no look-ahead bias
        signal = strategy.signal(closes.iloc[:i], settings)

        if signal == "buy" and position == 0.0 and capital > 0:
            buy_price   = broker.apply_slippage(close, "buy", slippage_bps)
            shares      = capital / buy_price
            capital     = 0.0
            position    = shares
            entry_price = buy_price
            trades.append({
                "date": ts.strftime("%Y-%m-%d"), "side": "buy",
                "price": round(buy_price, 2), "shares": round(shares, 4),
                "pnl": None, "pnl_pct": None,
            })

        elif signal == "sell" and position > 0.0:
            sell_price = broker.apply_slippage(close, "sell", slippage_bps)
            proceeds   = position * sell_price
            pnl        = proceeds - position * entry_price
            pnl_pct    = pnl / (position * entry_price) * 100
            capital    = proceeds
            trades.append({
                "date": ts.strftime("%Y-%m-%d"), "side": "sell",
                "price": round(sell_price, 2), "shares": round(position, 4),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            })
            position    = 0.0
            entry_price = 0.0

    if equity_rows and position > 0.0:
        equity_rows[-1]["equity"] = capital + position * float(closes.iloc[-1])

    equity_df = (pd.DataFrame(equity_rows) if equity_rows
                 else pd.DataFrame(columns=["date", "equity"]))

    # ── Performance metrics ──────────────────────────────────────────────────
    sell_trades = [t for t in trades if t["side"] == "sell"]

    if len(equity_df) > 1:
        final_equity = float(equity_df["equity"].iloc[-1])
        total_return = (final_equity - starting_capital) / starting_capital * 100
        daily_ret    = equity_df["equity"].pct_change().dropna()
        sharpe       = (float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5))
                        if daily_ret.std() > 0 else 0.0)
        roll_max     = equity_df["equity"].cummax()
        max_dd       = float(((equity_df["equity"] - roll_max) / roll_max * 100).min())
        wins         = [t for t in sell_trades if (t["pnl"] or 0) > 0]
        win_rate     = len(wins) / len(sell_trades) * 100 if sell_trades else 0.0
        gross_profit = sum((t["pnl"] or 0) for t in sell_trades if (t["pnl"] or 0) > 0)
        gross_loss   = abs(sum((t["pnl"] or 0) for t in sell_trades if (t["pnl"] or 0) < 0))
        pf           = gross_profit / gross_loss if gross_loss > 0 else None
    else:
        final_equity = starting_capital
        total_return = sharpe = max_dd = win_rate = 0.0
        pf = None

    return {
        "equity_curve": equity_df,
        "trades": trades,
        "metrics": {
            "starting_capital": starting_capital,
            "final_equity":     round(final_equity, 2),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio":     round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct":     round(win_rate, 1),
            "profit_factor":    round(pf, 2) if pf is not None else "∞",
            "total_trades":     len(sell_trades),
        },
    }
