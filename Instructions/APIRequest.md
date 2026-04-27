# Alpaca API Request Audit

A complete map of where this codebase calls Alpaca, the throttling that already
exists, why the bot can fall into a 30-second "rate-limited then stuck" loop,
and concrete ideas for keeping rolling 60-second usage comfortably under 300.

The Alpaca paper account ceiling is **200 requests / minute / API key**. The
header in `dashboard.py` line 882 shows usage as `API {n}/200`. Treat 300 in the
title as an aspirational hard cap for *combined* trading + data API calls; in
reality each API has its own counter and we want the larger one to stay well
below 200.

---

## 1. Every place we hit Alpaca

All Alpaca traffic must flow through `broker.py`. Each wrapper is decorated with
`@track_api_call(...)`, which records a row in `api_calls` so the rolling
60-second counter is accurate.

### Wrappers defined in `broker.py`

| Function | Endpoint | Decorator name |
|---|---|---|
| `get_account()` | `GET /v2/account` | `get_account` |
| `get_open_position(symbol)` | `GET /v2/positions/{sym}` | `get_open_position` |
| `get_all_positions()` | `GET /v2/positions` | `get_all_positions` |
| `get_clock()` | `GET /v2/clock` | `get_clock` |
| `submit_order(order_data)` | `POST /v2/orders` | `submit_order` |
| `get_stock_bars(request)` | `GET /v2/stocks/bars` (Data API) | `get_stock_bars` |
| `get_crypto_bars(request)` | `GET /v1beta3/crypto/bars` (Data API) | `get_crypto_bars` |
| `get_portfolio_history(period, tf)` | `GET /v2/account/portfolio/history` | `get_portfolio_history` |

### Call sites (bot)

`bot.py`
- L294 `broker.get_account()` — pre-market warmup
- L310 `broker.get_clock()` — warmup, to compute "minutes to open"
- L330 `broker.get_account()` — open-bell ping
- L342 `broker.get_account()` — every `run_one_cycle`
- L350 `broker.get_clock()` — every `run_one_cycle`
- L399 `broker.get_stock_bars()` — every cycle, **batched union** of all
  picks + manual symbols, 1 call regardless of N
- L96 `broker.get_stock_bars()` — `_current_prices_for(strategy_name)`,
  **fires after every fill** to compute Telegram total-equity
- L151 `broker.get_open_position(symbol)` — every sell
- L131 / L165 `broker.submit_order(...)` — every buy / sell
- L431 `broker.get_clock()` — every `_compute_sleep_seconds`, runs even when
  the cycle was just skipped due to rate limiting *(see issue §3)*

### Call sites (dashboard / pages)

`dashboard.py`
- L257 `broker.get_account()` — `@st.cache_data(ttl=10)`
- L264 `broker.get_all_positions()` — `@st.cache_data(ttl=10)`
- L291 `broker.get_portfolio_history(...)` — `@st.cache_data(ttl=60)`,
  but loops up to 4 fallback (period, timeframe) combos when the first
  returns empty — worst case **4 calls per cache miss**
- L1265 `broker.submit_order(...)` — manual paper order

`pages/positions.py`
- L62 `broker.get_all_positions()` — `@st.cache_data(ttl=10)`

### Non-Alpaca calls that look similar

These do **not** count toward Alpaca quotas, but are worth listing because they
share the same "data fetch" mental bucket.
- `dashboard.py` L330 `yf.download(...)` — Mag 7 + indices snapshot
- `dashboard.py` L395 `yf.Ticker(symbol).history(...)` — manual-trade chart
- `bot.py` L77 `yf.Ticker(symbol).history(...)` — daily picker uses yfinance
- `universe.py` L38 — Wikipedia S&P 500 scrape, daily-cached

---

## 2. Mediation already in the code

### a. The 60-second rolling counter
`db.count_recent_api_calls(60)` returns the number of rows in `api_calls` whose
timestamp is within the last 60 seconds. `broker.is_rate_limited()` compares it
against `config.RATE_LIMIT_THRESHOLD = 180`. Header in dashboard (L882) shows
the same value as `API n/200`.

### b. Bot pauses when near the limit
`bot.py` L358:
```python
if broker.is_rate_limited():
    db.log("WARN", f"Near API rate limit, sleeping {RATE_LIMIT_SLEEP_SECONDS}s")
    time.sleep(config.RATE_LIMIT_SLEEP_SECONDS)   # 30 s
    return
```
This is the **30-second pause** referenced in the prompt.

### c. Batched bar fetch
`bot.py` L378–L399 unions every active strategy's picks + manual symbols into a
single `StockBarsRequest` — N symbols cost 1 Alpaca call, not N. This is the
single biggest existing throttle: a 6-strategy 10-pick run is still 1 bar call.

### d. Daily picker cache
`_PICKED_SYMBOLS[strategy_name] = (today, picks)` (bot.py L33, L265). The
picker (which uses yfinance, not Alpaca) runs at most once per strategy per
calendar day.

### e. S&P 500 universe cache
`universe.py` `_CACHE = (today, symbols)` — Wikipedia fetch happens once per
day, fallback list is hardcoded.

### f. Streamlit `@st.cache_data` TTLs
| Function | TTL | Where |
|---|---|---|
| `_cached_account` | 10 s | dashboard.py L253 |
| `_cached_all_positions` | 10 s | dashboard.py L260, positions.py L59 |
| `_portfolio_history` | 60 s | dashboard.py L267 |
| `_ticker_snapshots` (yfinance) | 60 s | dashboard.py L321 |
| `_stock_info` (yfinance) | 30 s | dashboard.py L390 |

### g. Adaptive sleep around the bell
`_compute_sleep_seconds` (bot.py L420) makes the bot:
- Closed, > 30 min to open → sleep up to 1 hour
- Closed, ≤ 30 min → run the warmup, sleep until the bell − 1 s
- Open → `LOOP_INTERVAL_SECONDS = 300` (5 min)

So the bot only spins fast inside trading hours.

### h. Per-strategy ownership in DB, not Alpaca
`db.get_strategy_holding`, `db.get_strategy_open_positions`,
`db.get_strategy_equity` — all derive from the local `trades` table. The bot
does not query Alpaca to figure out "do I hold X for strategy Y" on every tick.

### i. Hard kill switch path
`safety.check_can_trade(...)` runs before any trade attempt — if it returns
false, the cycle returns *before* `submit_order` and the get-position calls.

---

## 3. Why the "30 s pause then repeat" can loop

Walk through what happens when usage spikes near 180/min:

1. Cycle starts. `db.get_all_config()` (DB only).
2. `broker.get_account()` → **+1 call**, recorded.
3. `broker.get_clock()` → **+1 call**, recorded.
4. `broker.is_rate_limited()` checks the count — *includes the 2 we just made*.
5. If above threshold: `time.sleep(30); return`.
6. `main()` loop continues to `_compute_sleep_seconds()`, which calls
   `broker.get_clock()` again → **+1 call**.
7. `time.sleep(sleep_s)` — usually `LOOP_INTERVAL_SECONDS` (300 s) when
   market is open. **Good news**: by the time this sleep ends, the 60-second
   rolling window has fully expired, so the next cycle should see a clean
   counter.

So the *normal* loop should self-heal. The genuinely bad case is when
`LOOP_INTERVAL_SECONDS` is shorter than the 60 s rolling window combined with
the calls each cycle makes:

- Each "rate-limited" cycle still spends **3 calls**
  (`get_account` + `get_clock` + sleep-side `get_clock`).
- Each *normal* cycle spends **3 calls + 1 batched bars + ≥1 per fill +
  1 per fill for `_current_prices_for`**.
- If the bot is configured to a tight cycle interval, or many fills happen
  back-to-back with `_notify_trade` re-fetching bars after every order, the
  threshold can stay tripped for several minutes.

The mechanical traps:
- `_compute_sleep_seconds` calls `get_clock` even on a rate-limited skip.
- `_notify_trade` → `_current_prices_for` → `get_stock_bars`: **one extra
  data-API call after every single fill** to compute total equity, even
  though we already had the bars from this cycle's batched fetch.
- `_stock_info`, `_cached_account`, `_cached_all_positions` cache TTLs are
  short (10–30 s) — a busy dashboard tab adds 6–18 calls/min on its own.

---

## 4. Ideas to keep usage under 300 / min (ranked by ROI)

### Tier 1 — small code change, big win

1. **Reuse the cycle's batched bars for fill notifications.**
   `_current_prices_for` (bot.py L90) re-runs `_fetch_bars_batch` after every
   fill purely to value other open positions for Telegram. Pass
   `bars_by_symbol` from `run_one_cycle` down through `process_symbol` →
   `place_buy` / `place_sell` → `_notify_trade`. Saves **1 data call per
   fill** (can be ~10 calls/min on active days).

2. **Cache `get_clock` for ~30 s.** The clock changes every 86,400 s, not
   every 300 s. Wrap `broker.get_clock` with a small in-process TTL cache
   (or reuse the result inside one cycle so we don't fetch twice). Saves
   **2 calls / cycle minimum**, and removes the "rate-limited skip still costs
   a `get_clock`" trap in `_compute_sleep_seconds`.

3. **Skip `get_account` when we can.** `run_one_cycle` calls `get_account`
   for equity *and* `_send_open_ping_once` calls it again on the first cycle of
   the day. Have `run_one_cycle` pass `account` into the open-ping helper.

4. **Drop `get_open_position` before sell.** The DB already tracks
   `get_strategy_holding(symbol, strategy)`; we use `get_open_position`
   purely as a "did the user manually liquidate" sanity check. Either
   trust the DB (pure paper account, single-bot setup) or batch it: cache
   `get_all_positions()` once per cycle and look up symbols from that map.
   Saves up to **1 call per sell**.

5. **Check the rate limit *before* the API calls, not after.** Move
   `if broker.is_rate_limited(): ... return` to the very top of
   `run_one_cycle`. Currently we burn 2 calls before the check fires. Saves
   2 calls every time we're already over budget — exactly the situation
   where every call hurts.

### Tier 2 — config tweaks

6. **Lower `RATE_LIMIT_THRESHOLD`** from 180 to ~140. Gives ~30% headroom,
   still well under 200. The cost is more "near limit" warnings, not lost
   trades — the cycle just sleeps 30 s and resumes.

7. **Raise `LOOP_INTERVAL_SECONDS`** from 300 to 600 in low-volatility hours,
   or make it strategy-specific. Halves cycle-driven load. Most of the
   strategies (RSI, MACD, BB) don't gain anything from a 5-min vs 10-min
   cadence on 15-min bars.

8. **Cap `picker_top_n` per strategy.** Today every active strategy unions
   into the bar fetch. If 6 strategies each pick 30 names with no overlap,
   the bar request still ships ≥180 symbols in one HTTP round-trip — that's
   safe in terms of *count*, but not in terms of *response size* (one big
   request can still trigger Alpaca's per-request limits). Keep top_n ≤ 10
   per strategy or share a single global pick list.

### Tier 3 — dashboard load

9. **Lengthen dashboard TTLs:** `_cached_account` 10 s → 30 s,
   `_cached_all_positions` 10 s → 30 s. Account snapshots feel "live" at
   30 s and a single tab refresh drops from ~6 calls/min to ~2.

10. **Single `get_portfolio_history` attempt.** Today on a cache miss we
    can fire up to 4 fallback combinations. Pick the most reliable
    `(period, timeframe)` per bar size and only fall back once.

11. **Share the cycle-fetched positions with the dashboard.** Persist
    a snapshot of `get_all_positions` in `bot_config` (or a tiny new table)
    on every bot cycle, and have the dashboard prefer that snapshot when
    fresh enough. Eliminates the dashboard ↔ bot competing for the same
    quota.

### Tier 4 — structural

12. **Single `request.session` with HTTP-level rate limiting.** The
    `alpaca-py` SDK builds its own client per `TradingClient` and
    `StockHistoricalDataClient`; we can wrap the wrappers in a tiny
    token-bucket so calls block for a few hundred ms instead of failing
    cycles. This converts the "30 s skip" into "smooth back-pressure".

13. **Pre-aggregate intraday bars in the DB.** The bars from each cycle's
    batched fetch are already in memory — store them. The next cycle only
    needs to fetch the *delta* since the last fetch, not the full lookback.
    For 15-minute bars on a 5-minute cycle this means 1–2 fresh bars per
    symbol, dramatically smaller payloads (still 1 call, but cheaper).

14. **Switch to Alpaca websocket bar stream** for live prices once we're
    confident in the bot. Replaces every-cycle bar pulls with a steady
    push stream. Heaviest lift, but reduces the data API to near zero.

---

## 5. Quick checklist before declaring "we're under 300"

- [ ] Open the dashboard, leave a tab idle for 5 minutes, check
      `db.count_recent_api_calls(60)` — that's pure dashboard overhead.
- [ ] Inspect `api_calls` grouped by `endpoint` over the last hour:
      `SELECT endpoint, COUNT(*) FROM api_calls
       WHERE timestamp >= datetime('now', '-1 hour')
       GROUP BY endpoint ORDER BY 2 DESC;`
- [ ] Confirm `get_clock` and `get_account` aren't the top two — if they
      are, Tier 1 items 2 & 3 will help most.
- [ ] Confirm `get_stock_bars` count ≈ cycles/hour + fills/hour. If it's
      higher, `_current_prices_for` is firing more than expected — Tier 1
      item 1.
