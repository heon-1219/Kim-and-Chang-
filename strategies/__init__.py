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
