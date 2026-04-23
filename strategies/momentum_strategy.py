"""
Rate-of-Change momentum strategy. Fires often on intraday bars because a small
threshold (~0.3%) is frequently crossed. Good for seeing activity quickly.
- ROC > +threshold  → 'buy'
- ROC < -threshold  → 'sell'
- otherwise          → 'hold'
"""

import pandas as pd

from strategies.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def required_lookback_days(self, settings: dict) -> int:
        window = int(settings.get("momentum_window", "3"))
        return window + 5

    def signal(self, prices: pd.Series, settings: dict) -> str:
        window = int(settings.get("momentum_window", "3"))
        threshold = float(settings.get("momentum_threshold", "0.3")) / 100.0

        if len(prices) < window + 1:
            return "hold"

        now = float(prices.iloc[-1])
        then = float(prices.iloc[-1 - window])
        if then <= 0 or pd.isna(now) or pd.isna(then):
            return "hold"
        roc = (now - then) / then

        if roc > threshold:
            return "buy"
        if roc < -threshold:
            return "sell"
        return "hold"

    def pick_symbols(self, universe, n, fetch_closes, settings):
        window = int(settings.get("momentum_window", "3"))
        scored: list[tuple[float, str]] = []
        for sym in universe:
            try:
                closes = fetch_closes(sym)
                if len(closes) < window + 1:
                    continue
                now = float(closes.iloc[-1])
                then = float(closes.iloc[-1 - window])
                if then <= 0:
                    continue
                roc = (now - then) / then
                # Largest positive ROC first (entering strong uptrend)
                scored.append((-roc, sym))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0])
        return [s for _, s in scored[:n]]
