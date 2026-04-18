"""
EMA Crossover trend-following strategy.
- Fast EMA crosses above slow EMA (golden cross) -> 'buy'
- Fast EMA crosses below slow EMA (death cross)  -> 'sell'
- otherwise                                       -> 'hold'
"""

import pandas as pd
from ta.trend import EMAIndicator

from strategies.base import BaseStrategy


class EMACrossoverStrategy(BaseStrategy):
    name = "ema_crossover"

    def required_lookback_days(self, settings: dict) -> int:
        slow = int(settings.get("ema_slow", "21"))
        return slow + 10

    def signal(self, prices: pd.Series, settings: dict) -> str:
        fast = int(settings.get("ema_fast", "9"))
        slow = int(settings.get("ema_slow", "21"))

        if len(prices) < slow + 1:
            return "hold"

        fast_ema = EMAIndicator(close=prices, window=fast).ema_indicator()
        slow_ema = EMAIndicator(close=prices, window=slow).ema_indicator()

        if pd.isna(fast_ema.iloc[-1]) or pd.isna(slow_ema.iloc[-1]):
            return "hold"

        prev_above = fast_ema.iloc[-2] > slow_ema.iloc[-2]
        curr_above = fast_ema.iloc[-1] > slow_ema.iloc[-1]

        if not prev_above and curr_above:
            return "buy"
        if prev_above and not curr_above:
            return "sell"
        return "hold"
