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

    def pick_symbols(self, universe, n, fetch_closes, settings):
        fast = int(settings.get("ema_fast", "9"))
        slow = int(settings.get("ema_slow", "21"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < slow + 1:
                    continue
                fast_ema = EMAIndicator(close=closes, window=fast).ema_indicator().iloc[-1]
                slow_ema = EMAIndicator(close=closes, window=slow).ema_indicator().iloc[-1]
                price = closes.iloc[-1]
                if pd.isna(fast_ema) or pd.isna(slow_ema) or price == 0:
                    continue
                # Prefer strongest positive fast-over-slow spread
                spread = (fast_ema - slow_ema) / price
                scored.append((-float(spread), sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
