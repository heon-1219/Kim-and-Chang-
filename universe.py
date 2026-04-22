"""
S&P 500 symbol universe. Fetches from Wikipedia once per day; falls back to a
hardcoded mega-cap list if the fetch fails (offline / network / layout change).
"""

from __future__ import annotations

from datetime import date
from typing import Tuple

import requests
from bs4 import BeautifulSoup

# Fallback list used if the live fetch fails. Top ~60 S&P 500 names by weight.
# Better than an empty list, good enough to keep the bot trading.
_FALLBACK = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK.B", "TSLA",
    "AVGO", "LLY", "JPM", "V", "UNH", "XOM", "MA", "COST", "JNJ", "HD", "PG",
    "WMT", "NFLX", "BAC", "ABBV", "CRM", "ORCL", "CVX", "KO", "AMD", "MRK",
    "PEP", "ADBE", "LIN", "TMO", "ACN", "CSCO", "MCD", "ABT", "WFC", "DIS",
    "CAT", "PM", "GE", "INTU", "IBM", "TXN", "VZ", "QCOM", "DHR", "AMAT",
    "GS", "AXP", "T", "NOW", "NEE", "UBER", "ISRG", "BLK", "RTX", "SPGI",
]

# Cache: (date_fetched, symbols)
_CACHE: Tuple[date, list[str]] | None = None


def get_sp500_symbols() -> list[str]:
    """Return current S&P 500 tickers, cached for a full calendar day."""
    global _CACHE
    today = date.today()
    if _CACHE is not None and _CACHE[0] == today:
        return _CACHE[1]

    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (trading-bot/universe)"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "constituents"}) or soup.find("table")
        symbols: list[str] = []
        if table is not None:
            for row in table.find_all("tr")[1:]:
                cell = row.find("td")
                if not cell:
                    continue
                sym = cell.get_text(strip=True)
                if sym and sym.isascii():
                    symbols.append(sym)
        if len(symbols) < 400:
            raise ValueError(f"Only {len(symbols)} symbols parsed, looks wrong")
        _CACHE = (today, symbols)
        return symbols
    except Exception:
        _CACHE = (today, _FALLBACK)
        return _FALLBACK
