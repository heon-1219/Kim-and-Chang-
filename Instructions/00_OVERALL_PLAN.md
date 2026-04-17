# 00 — Overall Plan

> **For Claude Code**: Read this file FIRST. Every phase file assumes you've read this. This file defines the project context, constraints, and architecture that apply to all phases.

---

## Project Context

### What we're building
An Alpaca **paper trading** bot for a single user, running 24/7 on a small VPS, with a personal-use web dashboard for monitoring and configuration.

### Who runs it
One person (the project owner). No multi-user features needed. No authentication beyond SSH/network-level access controls.

### Where it runs
- **Development**: User's Windows laptop (UV environment)
- **Production**: Vultr VPS in New Jersey
  - Ubuntu 24.04 LTS
  - 1 vCPU, 2GB RAM
  - Server already provisioned and SSH-secured
  - User: `trader` (non-root, sudo enabled)

### Trading scope
- US stocks + crypto via Alpaca
- Hourly/daily decisions (swing trading, NOT high-frequency)
- Paper trading account only (gets fake $100,000 from Alpaca)

---

## Hard Constraints (DO NOT violate)

### Banned technologies
- ❌ FastAPI (use Streamlit for the dashboard)
- ❌ React, Vue, Next.js, any frontend framework
- ❌ HTMX, Jinja2 templates
- ❌ Celery, Redis, RabbitMQ
- ❌ PostgreSQL, MySQL, MongoDB
- ❌ Docker (will be added later, not now)
- ❌ Kubernetes, anything orchestration-related
- ❌ APScheduler (use a simple `while True` loop)

### Banned features
- ❌ Dynamic code upload via web UI (HUGE security risk, user explicitly declined)
- ❌ User authentication system (single-user, dashboard accessed via SSH tunnel)
- ❌ Multiple user accounts in the application
- ❌ Live (real money) trading mode — `paper=True` is hardcoded everywhere
- ❌ Auto-deploy from git push (manual deploy only — bug safety)

### Banned patterns
- ❌ Storing API keys in code or git (use `.env`)
- ❌ Storing API keys in URLs or logs
- ❌ Using `eval()` or `exec()` on any user input
- ❌ Bare `except:` clauses (catch specific exceptions)
- ❌ Hard-coded sleep values without comments explaining why

---

## Architecture Overview

### Two processes, one database

```
┌──────────────────────────────────────────────────────────────┐
│                   Vultr server (Ubuntu 24.04)                │
│                                                              │
│  ┌──────────────────┐         ┌──────────────────┐           │
│  │   bot.py         │         │   dashboard.py   │           │
│  │  (always on)     │         │   (Streamlit)    │           │
│  │  systemd-managed │         │  systemd-managed │           │
│  └────────┬─────────┘         └────────┬─────────┘           │
│           │                            │                     │
│           ▼                            ▼                     │
│  ┌──────────────────────────────────────────────┐            │
│  │         trading.db (SQLite, WAL mode)        │            │
│  │  trades, logs, config, heartbeat, api_calls, │            │
│  │  safety_events                               │            │
│  └──────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────┘
                       │                       │
                       ▼                       ▼
              ┌────────────────┐      ┌────────────────┐
              │  Alpaca API    │      │   Telegram     │
              │  (paper only)  │      │   (alerts)     │
              └────────────────┘      └────────────────┘
```

### Why this architecture
- **Two processes**: Bot keeps running even when dashboard isn't being viewed.
- **SQLite + WAL**: Allows concurrent reads (dashboard) while writing (bot).
- **systemd**: Auto-restart on crash, auto-start on boot.
- **No web framework for the bot**: It's a background worker, not a web app.

---

## Tech Stack (use exactly these versions or newer)

```
Python 3.12 (managed by UV)
alpaca-py >= 0.30.0
pandas >= 2.2.0
streamlit >= 1.40.0
ta >= 0.11.0          # for RSI calculation
python-dotenv >= 1.0.0
requests >= 2.32.0    # for Telegram API
```

**Package manager**: UV (https://docs.astral.sh/uv/) — NOT pip/poetry/pipenv.

---

## Final Directory Structure

```
trading-bot/
├── pyproject.toml
├── .python-version
├── .env.example
├── .gitignore
├── README.md
├── bot.py
├── dashboard.py
├── db.py
├── config.py
├── safety.py
├── broker.py
├── notifications.py
├── strategies/
│   ├── __init__.py
│   ├── base.py
│   └── rsi_strategy.py
├── deploy/
│   ├── trading-bot.service
│   └── trading-dashboard.service
└── docs/                 # this folder, kept in repo for reference
    ├── 00_OVERALL_PLAN.md
    ├── 01_PHASE_SCAFFOLDING.md
    ├── ...
    ├── PATTERNS.md
    └── CHECKLIST.md
```

### Module responsibilities (single responsibility — do not mix)
- **`bot.py`**: Main loop, orchestration only. No strategy logic, no DB schema, no API details.
- **`dashboard.py`**: Streamlit UI only. No trading logic.
- **`db.py`**: ALL SQLite access. Other modules import functions from here.
- **`config.py`**: Default configuration values (constants only, no logic).
- **`safety.py`**: Kill switch and risk limit checks.
- **`broker.py`**: Alpaca API wrapper with rate limit tracking.
- **`notifications.py`**: Telegram alert sending.
- **`strategies/base.py`**: `BaseStrategy` abstract class.
- **`strategies/rsi_strategy.py`**: Concrete RSI implementation.

---

## Phase Execution Order

Execute these phases **in order**. After each phase, run the verification block in that phase's file before moving to the next.

| # | File | Goal |
|---|------|------|
| 1 | `01_PHASE_SCAFFOLDING.md` | UV project setup |
| 2 | `02_PHASE_DATABASE.md` | SQLite schema and helpers (everything depends on this) |
| 3 | `03_PHASE_NOTIFICATIONS.md` | Telegram alerts |
| 4 | `04_PHASE_SAFETY.md` | Kill switch and risk limits |
| 5 | `05_PHASE_BROKER.md` | Alpaca wrapper with rate limit + slippage |
| 6 | `06_PHASE_STRATEGIES.md` | BaseStrategy + RSI implementation |
| 7 | `07_PHASE_BOT.md` | Main loop |
| 8 | `08_PHASE_DASHBOARD.md` | Streamlit UI |
| 9 | `09_PHASE_DEPLOY.md` | systemd service files |
| 10 | `10_PHASE_USER_README.md` | User-facing README |

After Phase 10, run `CHECKLIST.md` for final verification.

---

## Reference Documents

These are read on-demand during phases:

- **`PATTERNS.md`** — Code patterns (DB access, error handling, configuration, trade execution). Phases reference this with `See PATTERNS.md > <section>`.
- **`CHECKLIST.md`** — Final verification checklist. Use after Phase 10.

---

## What Comes Later (NOT now)

These are explicitly out of scope. Do NOT preemptively add scaffolding.

- Backtesting framework
- Multiple concurrent strategies on different symbols
- WebSocket data streaming (polling REST every cycle is fine for hourly trading)
- Crypto-specific logic (start with stocks; crypto comes after stocks works)
- ML signal generation
- Performance analytics beyond the basic dashboard
- Anything involving real money

---

## Disclaimers

- This is paper trading software. It uses Alpaca's paper trading endpoint and does not interact with real money.
- The default RSI strategy is for educational purposes and is unlikely to be profitable.
- The user is responsible for their own trading decisions, strategies, and outcomes.

---

## When You're Stuck

If a requirement is ambiguous, default to:
1. The simpler implementation
2. The safer implementation (always favor preventing bad trades over enabling more trades)
3. The pattern shown in `PATTERNS.md`

If you can't satisfy a constraint without violating a banned item, STOP and ask the user.
