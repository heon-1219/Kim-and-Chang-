"""
Short-term moving-average crossover. Uses much shorter windows than EMA Crossover
so it fires frequently on intraday bars — meant for visible activity.
- Fast SMA crosses above slow SMA  → 'buy'
- Fast SMA crosses below slow SMA  → 'sell'
- otherwise                         → 'hold'
"""

import pandas as pd

from strategies.base import BaseStrategy


class ShortMAStrategy(BaseStrategy):
    name = "short_ma"

    def required_lookback_days(self, settings: dict) -> int:
        slow = int(settings.get("short_ma_slow", "15"))
        return slow + 5

    def signal(self, prices: pd.Series, settings: dict) -> str:
        fast = int(settings.get("short_ma_fast", "5"))
        slow = int(settings.get("short_ma_slow", "15"))

        if len(prices) < slow + 1:
            return "hold"

        fast_ma = prices.rolling(fast).mean()
        slow_ma = prices.rolling(slow).mean()

        if pd.isna(fast_ma.iloc[-1]) or pd.isna(slow_ma.iloc[-1]):
            return "hold"
        if pd.isna(fast_ma.iloc[-2]) or pd.isna(slow_ma.iloc[-2]):
            return "hold"

        prev_above = fast_ma.iloc[-2] > slow_ma.iloc[-2]
        curr_above = fast_ma.iloc[-1] > slow_ma.iloc[-1]

        if not prev_above and curr_above:
            return "buy"
        if prev_above and not curr_above:
            return "sell"
        return "hold"

    def pick_symbols(self, universe, n, fetch_closes, settings):
        fast = int(settings.get("short_ma_fast", "5"))
        slow = int(settings.get("short_ma_slow", "15"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < slow + 1:
                    continue
                fast_ma = closes.rolling(fast).mean().iloc[-1]
                slow_ma = closes.rolling(slow).mean().iloc[-1]
                price = float(closes.iloc[-1])
                if pd.isna(fast_ma) or pd.isna(slow_ma) or price == 0:
                    continue
                spread = (fast_ma - slow_ma) / price
                # Strongest positive spread first
                scored.append((-float(spread), sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
