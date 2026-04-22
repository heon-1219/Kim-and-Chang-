"""
RSI (Relative Strength Index) mean-reversion strategy.
- RSI < oversold  -> 'buy'
- RSI > overbought -> 'sell'
- otherwise        -> 'hold'
"""

from typing import Callable

import pandas as pd
from ta.momentum import RSIIndicator

from strategies.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    name = "rsi"

    def required_lookback_days(self, settings: dict) -> int:
        period = int(settings.get("rsi_period", "14"))
        # Need period+1 minimum; buffer covers weekends/holidays
        return period + 10

    def signal(self, prices: pd.Series, settings: dict) -> str:
        period = int(settings.get("rsi_period", "14"))
        oversold = float(settings.get("rsi_oversold", "30"))
        overbought = float(settings.get("rsi_overbought", "70"))

        if len(prices) < period + 1:
            return "hold"

        rsi_series = RSIIndicator(close=prices, window=period).rsi()
        latest_rsi = float(rsi_series.iloc[-1])

        if pd.isna(latest_rsi):
            return "hold"
        if latest_rsi < oversold:
            return "buy"
        if latest_rsi > overbought:
            return "sell"
        return "hold"

    def pick_symbols(self, universe, n, fetch_closes, settings):
        period = int(settings.get("rsi_period", "14"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < period + 1:
                    continue
                rsi = RSIIndicator(close=closes, window=period).rsi().iloc[-1]
                if pd.isna(rsi):
                    continue
                # Most oversold first (lowest RSI best for a mean-reversion buy)
                scored.append((float(rsi), sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
