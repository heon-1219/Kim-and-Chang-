"""
Event-driven backtester. Uses yfinance for historical data — free, no subscription needed.
Supports single or multiple symbols. For multi-symbol runs capital is split evenly;
strategy results are summed and a buy-and-hold baseline (also summed) is returned.
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


def _run_single(
    symbol: str,
    strategy_name: str,
    start: date,
    end: date,
    starting_capital: float,
    settings: dict,
) -> dict:
    """Run a backtest on a single symbol. Internal helper."""
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
    hold_rows   = []
    hold_shares = None  # shares bought on first in-range bar for buy-and-hold baseline

    for i in range(len(closes)):
        ts    = closes.index[i]
        close = float(closes.iloc[i])

        if ts < trade_start:
            continue

        if hold_shares is None and close > 0:
            hold_shares = starting_capital / close

        equity = capital + position * close
        equity_rows.append({"date": ts, "equity": equity, "symbol": symbol})
        if hold_shares is not None:
            hold_rows.append({"date": ts, "equity": hold_shares * close, "symbol": symbol})

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
                "date": ts.strftime("%Y-%m-%d"), "symbol": symbol, "side": "buy",
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
                "date": ts.strftime("%Y-%m-%d"), "symbol": symbol, "side": "sell",
                "price": round(sell_price, 2), "shares": round(position, 4),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            })
            position    = 0.0
            entry_price = 0.0

    if equity_rows and position > 0.0:
        equity_rows[-1]["equity"] = capital + position * float(closes.iloc[-1])

    equity_df = (pd.DataFrame(equity_rows) if equity_rows
                 else pd.DataFrame(columns=["date", "equity", "symbol"]))
    hold_df   = (pd.DataFrame(hold_rows) if hold_rows
                 else pd.DataFrame(columns=["date", "equity", "symbol"]))

    return {
        "symbol": symbol,
        "equity_curve": equity_df,
        "buy_and_hold_curve": hold_df,
        "trades": trades,
    }


def _metrics(equity_df: pd.DataFrame, starting_capital: float,
             sell_trades: list[dict]) -> dict:
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
        "starting_capital": starting_capital,
        "final_equity":     round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "sharpe_ratio":     round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct":     round(win_rate, 1),
        "profit_factor":    round(pf, 2) if pf is not None else "∞",
        "total_trades":     len(sell_trades),
    }


def run_backtest(
    symbols,
    strategy_name: str,
    start: date,
    end: date,
    starting_capital: float,
    settings: dict,
) -> dict:
    """
    Run a backtest on one or more symbols.

    `symbols` may be a string (single symbol) or a list[str]. For lists, the
    starting capital is split evenly. The returned equity curve and buy-and-hold
    baseline are summed across symbols so the two are directly comparable.

    Returns dict with keys:
        equity_curve         pd.DataFrame(date, equity)  — summed strategy curve
        buy_and_hold_curve   pd.DataFrame(date, equity)  — summed passive baseline
        per_symbol           list[dict] — raw per-symbol results
        trades               list[dict] — all trades, oldest first
        metrics              dict       — summed-curve performance stats
    """
    if isinstance(symbols, str):
        symbols = [symbols]
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("No symbols provided.")

    per_symbol_capital = float(starting_capital) / len(symbols)
    per_symbol: list[dict] = []
    errors: list[str] = []
    for sym in symbols:
        try:
            per_symbol.append(
                _run_single(sym, strategy_name, start, end,
                            per_symbol_capital, settings)
            )
        except Exception as e:
            errors.append(f"{sym}: {e}")

    if not per_symbol:
        raise ValueError("; ".join(errors) or "Backtest produced no results.")

    # Sum equity curves by date across all symbols
    def _sum_curve(key: str) -> pd.DataFrame:
        frames = [r[key] for r in per_symbol if not r[key].empty]
        if not frames:
            return pd.DataFrame(columns=["date", "equity"])
        big = pd.concat(frames, ignore_index=True)
        out = (big.groupby("date", as_index=False)["equity"].sum()
                  .sort_values("date").reset_index(drop=True))
        return out

    equity_df = _sum_curve("equity_curve")
    hold_df   = _sum_curve("buy_and_hold_curve")

    all_trades: list[dict] = []
    for r in per_symbol:
        all_trades.extend(r["trades"])
    all_trades.sort(key=lambda t: t["date"])
    sell_trades = [t for t in all_trades if t["side"] == "sell"]

    return {
        "equity_curve":       equity_df,
        "buy_and_hold_curve": hold_df,
        "per_symbol":         per_symbol,
        "trades":             all_trades,
        "metrics":            _metrics(equity_df, float(starting_capital), sell_trades),
        "symbols":            symbols,
        "errors":             errors,
    }
