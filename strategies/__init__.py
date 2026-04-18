"""
Registry of available strategies. To add a new strategy:
  1. Create strategies/your_strategy.py with a class inheriting BaseStrategy
  2. Import it here and add to STRATEGIES dict
  3. The dashboard will automatically show it in the strategy selector
"""

from strategies.bollinger_strategy import BollingerStrategy
from strategies.ema_crossover_strategy import EMACrossoverStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_strategy import RSIStrategy

STRATEGIES = {
    "rsi": RSIStrategy(),
    "macd": MACDStrategy(),
    "bollinger": BollingerStrategy(),
    "ema_crossover": EMACrossoverStrategy(),
}
