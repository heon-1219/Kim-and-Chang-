"""
Bollinger Bands mean-reversion strategy.
- Price drops below lower band -> 'buy'
- Price rises above upper band -> 'sell'
- otherwise                    -> 'hold'
"""

import pandas as pd
from ta.volatility import BollingerBands

from strategies.base import BaseStrategy


class BollingerStrategy(BaseStrategy):
    name = "bollinger"

    def required_lookback_days(self, settings: dict) -> int:
        window = int(settings.get("bb_window", "20"))
        return window + 10

    def signal(self, prices: pd.Series, settings: dict) -> str:
        window = int(settings.get("bb_window", "20"))
        std = float(settings.get("bb_std", "2.0"))

        if len(prices) < window + 1:
            return "hold"

        bb = BollingerBands(close=prices, window=window, window_dev=std)
        lower = bb.bollinger_lband()
        upper = bb.bollinger_hband()
        latest_price = prices.iloc[-1]

        if pd.isna(lower.iloc[-1]) or pd.isna(upper.iloc[-1]):
            return "hold"

        if latest_price < lower.iloc[-1]:
            return "buy"
        if latest_price > upper.iloc[-1]:
            return "sell"
        return "hold"
