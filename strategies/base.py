"""
Abstract base class for trading strategies.
All concrete strategies must inherit from this.
"""

from abc import ABC, abstractmethod
from typing import Callable

import pandas as pd


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def required_lookback_days(self, settings: dict) -> int:
        """How many days of price history this strategy needs to make a decision."""
        ...

    @abstractmethod
    def signal(self, prices: pd.Series, settings: dict) -> str:
        """
        Compute a trading signal from a price series.

        Args:
            prices: Series of close prices, oldest to newest.
            settings: dict from db.get_all_config() — strategies pull their own params.

        Returns:
            'buy', 'sell', or 'hold'
        """
        ...

    def pick_symbols(
        self,
        universe: list[str],
        n: int,
        fetch_closes: Callable[[str], pd.Series],
        settings: dict,
    ) -> list[str]:
        """
        Rank the universe and return the top-N symbols that best fit this
        strategy's setup right now. Default: first N of the universe.

        `fetch_closes(symbol)` returns a daily close Series; the default
        implementation doesn't call it but subclasses use it for ranking.
        """
        return list(universe)[:n]
