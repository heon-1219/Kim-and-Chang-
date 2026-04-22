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

    def pick_symbols(self, universe, n, fetch_closes, settings):
        window = int(settings.get("bb_window", "20"))
        std = float(settings.get("bb_std", "2.0"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < window + 1:
                    continue
                bb = BollingerBands(close=closes, window=window, window_dev=std)
                lower = bb.bollinger_lband().iloc[-1]
                upper = bb.bollinger_hband().iloc[-1]
                price = closes.iloc[-1]
                if pd.isna(lower) or pd.isna(upper) or upper == lower:
                    continue
                # %B: 0 at lower band, 1 at upper. Prefer deepest below lower (tiny/neg).
                pct_b = (price - lower) / (upper - lower)
                scored.append((float(pct_b), sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
