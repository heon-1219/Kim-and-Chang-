"""
MACD (Moving Average Convergence Divergence) trend-following strategy.
- MACD line crosses above signal line -> 'buy'
- MACD line crosses below signal line -> 'sell'
- otherwise                           -> 'hold'
"""

import pandas as pd
from ta.trend import MACD

from strategies.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    name = "macd"

    def required_lookback_days(self, settings: dict) -> int:
        slow = int(settings.get("macd_slow", "26"))
        signal = int(settings.get("macd_signal", "9"))
        return slow + signal + 10

    def signal(self, prices: pd.Series, settings: dict) -> str:
        fast = int(settings.get("macd_fast", "12"))
        slow = int(settings.get("macd_slow", "26"))
        signal_period = int(settings.get("macd_signal", "9"))

        if len(prices) < slow + signal_period + 1:
            return "hold"

        macd = MACD(close=prices, window_fast=fast, window_slow=slow, window_sign=signal_period)
        macd_line = macd.macd()
        signal_line = macd.macd_signal()

        if pd.isna(macd_line.iloc[-1]) or pd.isna(signal_line.iloc[-1]):
            return "hold"

        prev_above = macd_line.iloc[-2] > signal_line.iloc[-2]
        curr_above = macd_line.iloc[-1] > signal_line.iloc[-1]

        if not prev_above and curr_above:
            return "buy"
        if prev_above and not curr_above:
            return "sell"
        return "hold"

    def pick_symbols(self, universe, n, fetch_closes, settings):
        fast = int(settings.get("macd_fast", "12"))
        slow = int(settings.get("macd_slow", "26"))
        sig = int(settings.get("macd_signal", "9"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < slow + sig + 1:
                    continue
                macd = MACD(close=closes, window_fast=fast, window_slow=slow, window_sign=sig)
                hist = (macd.macd() - macd.macd_signal()).iloc[-1]
                if pd.isna(hist):
                    continue
                # Strongest positive histogram first (momentum just turning up)
                scored.append((-float(hist), sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
