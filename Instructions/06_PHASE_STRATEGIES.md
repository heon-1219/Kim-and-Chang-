# Phase 6 — Strategy Abstraction (`strategies/`)

> **Prerequisite**: Phases 1–5 complete.

## Goal
Make adding new strategies trivial without restructuring code.

## Tasks

### 1. Implement `strategies/base.py`

```python
"""
Abstract base class for trading strategies.
All concrete strategies must inherit from this.
"""
from abc import ABC, abstractmethod
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
```

### 2. Implement `strategies/rsi_strategy.py`

```python
"""
RSI (Relative Strength Index) mean-reversion strategy.
- RSI < oversold -> 'buy'
- RSI > overbought -> 'sell'
- otherwise -> 'hold'
"""
import pandas as pd
from ta.momentum import RSIIndicator

from strategies.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    name = "rsi"

    def required_lookback_days(self, settings: dict) -> int:
        period = int(settings.get("rsi_period", "14"))
        # Need period+1 minimum for RSI; add buffer for missing days (weekends/holidays)
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
```

### 3. Implement `strategies/__init__.py` — registry

```python
"""
Registry of available strategies. To add a new strategy:
  1. Create strategies/your_strategy.py with a class inheriting BaseStrategy
  2. Import it here and add to STRATEGIES dict
  3. The dashboard will automatically show it in the strategy selector
"""
from strategies.rsi_strategy import RSIStrategy

STRATEGIES = {
    "rsi": RSIStrategy(),
}
```

### 4. Design notes
- Strategies are **stateless singletons**. They don't hold state between calls. State (positions, orders) lives in Alpaca and SQLite.
- Strategies pull their own parameters from `settings` dict — they know which keys they care about.
- Strategies do NOT place orders. They only return a signal string. The bot's main loop decides whether to act on the signal.
- Strategies do NOT call Alpaca APIs. They receive a `prices` Series.

This separation makes strategies trivially unit-testable.

---

## Verification

```bash
# 1. Registry loads
uv run python -c "
from strategies import STRATEGIES
print('Available:', list(STRATEGIES.keys()))
"
# Expected: Available: ['rsi']

# 2. RSI lookback calculation
uv run python -c "
from strategies import STRATEGIES
s = STRATEGIES['rsi']
print(s.required_lookback_days({'rsi_period': '14'}))
"
# Expected: 24

# 3. RSI buy signal on artificial data
uv run python -c "
import pandas as pd
from strategies import STRATEGIES
# Construct prices that trend down (will produce low RSI)
prices = pd.Series([100, 99, 98, 97, 96, 95, 94, 93, 92, 91,
                    90, 89, 88, 87, 86, 85])
s = STRATEGIES['rsi']
sig = s.signal(prices, {'rsi_period': '14', 'rsi_oversold': '30', 'rsi_overbought': '70'})
print('Signal:', sig)
"
# Expected: Signal: buy

# 4. RSI sell signal on artificial data
uv run python -c "
import pandas as pd
from strategies import STRATEGIES
prices = pd.Series([85, 86, 87, 88, 89, 90, 91, 92, 93, 94,
                    95, 96, 97, 98, 99, 100])
s = STRATEGIES['rsi']
sig = s.signal(prices, {'rsi_period': '14', 'rsi_oversold': '30', 'rsi_overbought': '70'})
print('Signal:', sig)
"
# Expected: Signal: sell

# 5. Insufficient data returns hold
uv run python -c "
import pandas as pd
from strategies import STRATEGIES
prices = pd.Series([100, 101, 102])
s = STRATEGIES['rsi']
print(s.signal(prices, {'rsi_period': '14', 'rsi_oversold': '30', 'rsi_overbought': '70'}))
"
# Expected: hold
```

If all 5 checks pass, Phase 6 is complete. Proceed to `07_PHASE_BOT.md`.
