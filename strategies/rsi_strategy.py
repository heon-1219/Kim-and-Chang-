"""
RSI (Relative Strength Index) mean-reversion strategy.
- RSI < oversold  -> 'buy'
- RSI > overbought -> 'sell'
- otherwise        -> 'hold'
"""

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
