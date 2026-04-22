"""
Default configuration constants. Runtime values are stored in the bot_config DB table
and can be edited via the dashboard. These constants are used to seed the table on first init.
"""

# Trading targets
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA"]

# RSI strategy defaults
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 30
DEFAULT_RSI_OVERBOUGHT = 70

# MACD strategy defaults
DEFAULT_MACD_FAST = 12
DEFAULT_MACD_SLOW = 26
DEFAULT_MACD_SIGNAL = 9

# Bollinger Bands strategy defaults
DEFAULT_BB_WINDOW = 20
DEFAULT_BB_STD = 2.0

# EMA Crossover strategy defaults
DEFAULT_EMA_FAST = 9
DEFAULT_EMA_SLOW = 21

# Position sizing
DEFAULT_POSITION_PCT = 5.0       # % of equity per position
DEFAULT_MAX_POSITIONS = 4

# Safety limits
DEFAULT_DAILY_LOSS_LIMIT_PCT = 2.0   # auto-kill if today's loss exceeds this
DEFAULT_MAX_DRAWDOWN_PCT = 10.0      # auto-kill if drawdown exceeds this
DEFAULT_MAX_TRADES_PER_MINUTE = 20   # detect runaway loops

# Slippage simulation
DEFAULT_SLIPPAGE_BPS = 5             # 5 basis points = 0.05%

# Bot loop
LOOP_INTERVAL_SECONDS = 300          # 5 min — active intraday trading
RATE_LIMIT_SLEEP_SECONDS = 30        # extra sleep when near rate limit
RATE_LIMIT_THRESHOLD = 180           # Alpaca limit is 200/min; leave 20 buffer

# Database
DB_PATH = "trading.db"

# Default active strategy
DEFAULT_ACTIVE_STRATEGY = "rsi"

# How many S&P 500 names each strategy picks per day
DEFAULT_PICKER_TOP_N = 10
