"""
Event-driven backtester. Uses yfinance for historical data — free, no subscription needed.
Supports single or multiple symbols and multiple bar intervals (daily down to 1-minute
for high-frequency backtests). For multi-symbol runs capital is split evenly;
strategy results are summed and a buy-and-hold baseline (also summed) is returned.
"""

from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

import broker
from strategies import STRATEGIES


# yfinance per-interval lookback caps (calendar days).
# Fetching beyond these raises an empty response, so we surface a clean error.
_INTERVAL_MAX_DAYS = {
    "1m":  7,
    "2m":  59,
    "5m":  59,
    "15m": 59,
    "30m": 59,
    "60m": 729,
    "90m": 59,
    "1h":  729,
    "1d":  None,
    "5d":  None,
    "1wk": None,
    "1mo": None,
}

# Approximate bars-per-day used when sizing the lookback window for intraday.
# A US trading session is 6.5h = 390 minutes.
_BARS_PER_DAY = {
    "1m":  390, "2m": 195, "5m":  78, "15m": 26, "30m": 13,
    "60m":  7, "90m":   5, "1h":   7, "1d":   1, "5d":  0.2,
    "1wk": 0.2, "1mo": 0.05,
}


def _validate_interval(interval: str, start: date, end: date) -> None:
    if interval not in _INTERVAL_MAX_DAYS:
        raise ValueError(f"Unsupported interval: {interval}")
    max_days = _INTERVAL_MAX_DAYS[interval]
    if max_days is None:
        return
    span = (end - start).days
    if span > max_days:
        raise ValueError(
            f"Interval '{interval}' only supports up to {max_days} days of history "
            f"from yfinance (requested {span}). Shorten the date range or use a "
            f"coarser interval."
        )


def _fetch_closes(symbol: str, fetch_start: datetime, end: date,
                  interval: str = "1d") -> pd.Series:
    end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
    ticker = yf.Ticker(symbol)
    raw = ticker.history(
        start=fetch_start.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        interval=interval,
        auto_adjust=True,
    )
    if raw.empty:
        raise ValueError(
            f"No price data for {symbol} at {interval}. "
            f"Check the ticker symbol, date range, and interval limits."
        )
    closes = raw["Close"].dropna()
    # Normalise to tz-naive timestamps; keep intraday resolution when present.
    if interval in ("1d", "5d", "1wk", "1mo"):
        closes.index = pd.to_datetime([d.date() for d in closes.index])
    else:
        closes.index = pd.to_datetime(
            [d.tz_localize(None) if d.tzinfo else d for d in closes.index]
        )
    return closes


def _run_single(
    symbol: str,
    strategy_name: str,
    start: date,
    end: date,
    starting_capital: float,
    settings: dict,
    interval: str = "1d",
) -> dict:
    """Run a backtest on a single symbol. Internal helper."""
    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    lookback_days = strategy.required_lookback_days(settings) + 5
    # For intraday intervals, the strategy needs N "bars" of history, but N days
    # of intraday data is overkill. Scale lookback so we fetch at least a
    # healthy margin of bars without blowing past yfinance's window.
    bars_per_day = _BARS_PER_DAY.get(interval, 1)
    if bars_per_day > 1:
        # Convert required bars back to calendar days, with a floor of 5.
        needed_cal_days = max(5, int(lookback_days / bars_per_day) + 2)
        max_days = _INTERVAL_MAX_DAYS.get(interval)
        if max_days is not None:
            needed_cal_days = min(needed_cal_days, max_days)
        lookback_days = needed_cal_days

    fetch_start = datetime(start.year, start.month, start.day) - timedelta(days=lookback_days)
    closes      = _fetch_closes(symbol, fetch_start, end, interval=interval)

    if interval in ("1d", "5d", "1wk", "1mo"):
        trade_start = pd.Timestamp(start)
    else:
        trade_start = pd.Timestamp(datetime(start.year, start.month, start.day))
    slippage_bps = int(settings.get("slippage_bps", 5))

    capital     = float(starting_capital)
    position    = 0.0
    entry_price = 0.0
    trades      = []
    equity_rows = []
    hold_rows   = []
    hold_shares = None

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

        signal = strategy.signal(closes.iloc[:i], settings)

        if signal == "buy" and position == 0.0 and capital > 0:
            buy_price   = broker.apply_slippage(close, "buy", slippage_bps)
            shares      = capital / buy_price
            capital     = 0.0
            position    = shares
            entry_price = buy_price
            trades.append({
                "date":    ts.strftime("%Y-%m-%d %H:%M" if bars_per_day > 1
                                       else "%Y-%m-%d"),
                "symbol":  symbol, "side": "buy",
                "price":   round(buy_price, 2),
                "shares":  round(shares, 4),
                "pnl":     None, "pnl_pct": None,
            })

        elif signal == "sell" and position > 0.0:
            sell_price = broker.apply_slippage(close, "sell", slippage_bps)
            proceeds   = position * sell_price
            pnl        = proceeds - position * entry_price
            pnl_pct    = pnl / (position * entry_price) * 100
            capital    = proceeds
            trades.append({
                "date":    ts.strftime("%Y-%m-%d %H:%M" if bars_per_day > 1
                                       else "%Y-%m-%d"),
                "symbol":  symbol, "side": "sell",
                "price":   round(sell_price, 2),
                "shares":  round(position, 4),
                "pnl":     round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
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
             sell_trades: list[dict], interval: str = "1d") -> dict:
    if len(equity_df) > 1:
        final_equity = float(equity_df["equity"].iloc[-1])
        total_return = (final_equity - starting_capital) / starting_capital * 100
        # Annualise Sharpe based on interval. 252 trading days * bars_per_day.
        bars_per_day = _BARS_PER_DAY.get(interval, 1)
        periods_per_year = 252 * bars_per_day if bars_per_day >= 1 else 252
        per_bar_ret = equity_df["equity"].pct_change().dropna()
        sharpe      = (float(per_bar_ret.mean() / per_bar_ret.std()
                             * (periods_per_year ** 0.5))
                       if per_bar_ret.std() > 0 else 0.0)
        roll_max    = equity_df["equity"].cummax()
        max_dd      = float(((equity_df["equity"] - roll_max) / roll_max * 100).min())
        wins        = [t for t in sell_trades if (t["pnl"] or 0) > 0]
        win_rate    = len(wins) / len(sell_trades) * 100 if sell_trades else 0.0
        gross_profit = sum((t["pnl"] or 0) for t in sell_trades if (t["pnl"] or 0) > 0)
        gross_loss   = abs(sum((t["pnl"] or 0) for t in sell_trades if (t["pnl"] or 0) < 0))
        pf          = gross_profit / gross_loss if gross_loss > 0 else None
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
    interval: str = "1d",
) -> dict:
    """
    Run a backtest on one or more symbols.

    `symbols` may be a string (single symbol) or a list[str]. For lists, the
    starting capital is split evenly. The returned equity curve and buy-and-hold
    baseline are summed across symbols so the two are directly comparable.

    `interval` controls the bar granularity. Supported values:
        "1m", "2m", "5m", "15m", "30m", "60m", "1h", "1d", "5d", "1wk", "1mo"
    yfinance imposes per-interval history caps (1m = 7d, 5m/15m/30m = 60d,
    1h = 730d); this function validates the date range accordingly.

    Returns dict with keys:
        equity_curve         pd.DataFrame(date, equity)  — summed strategy curve
        buy_and_hold_curve   pd.DataFrame(date, equity)  — summed passive baseline
        per_symbol           list[dict] — raw per-symbol results
        trades               list[dict] — all trades, oldest first
        metrics              dict       — summed-curve performance stats
        interval             str        — echoed bar interval used
    """
    if isinstance(symbols, str):
        symbols = [symbols]
    symbols = [str(s).strip().upper() for s in symbols
               if s is not None and str(s).strip()]
    if not symbols:
        raise ValueError("No symbols provided.")

    _validate_interval(interval, start, end)

    per_symbol_capital = float(starting_capital) / len(symbols)
    per_symbol: list[dict] = []
    errors: list[str] = []
    for sym in symbols:
        try:
            per_symbol.append(
                _run_single(sym, strategy_name, start, end,
                            per_symbol_capital, settings, interval=interval)
            )
        except Exception as e:
            errors.append(f"{sym}: {e}")

    if not per_symbol:
        raise ValueError("; ".join(errors) or "Backtest produced no results.")

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
        "metrics":            _metrics(equity_df, float(starting_capital),
                                       sell_trades, interval=interval),
        "symbols":            symbols,
        "errors":             errors,
        "interval":           interval,
    }
