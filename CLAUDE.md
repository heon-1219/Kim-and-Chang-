# Project: Alpaca Paper Trading Bot

> This file is auto-loaded by Claude Code at the start of every session.
> Read `instructions/00_OVERALL_PLAN.md` for full project context before any task.

---

## What this project is

A **paper trading** bot for Alpaca, plus a Streamlit dashboard. Single user, runs 24/7 on a Vultr VPS. Built with Python + UV + SQLite.

**Stage**: Greenfield. Build from scratch following `instructions/` phase files in order.

---

## Workflow rules

### When the user asks you to build or implement something
1. **Identify the relevant phase file** in `instructions/` (e.g., "set up the database" → `instructions/02_PHASE_DATABASE.md`).
2. **Always read `instructions/00_OVERALL_PLAN.md` first** if you haven't this session.
3. Read the specific phase file you need.
4. If the phase references `PATTERNS.md`, read it too.
5. Execute the phase. Stop at the verification block. Do NOT auto-proceed to the next phase.
6. Run the verification commands and report results.
7. Wait for the user to say "proceed" before starting the next phase.

### When the user asks a quick question
Don't load phase files for trivial questions. Use this CLAUDE.md as your context and answer directly.

### When you finish a phase
Report:
- What you built (files created/modified)
- Verification results (pass/fail for each check)
- Any deviations from the spec and why
- Next phase to run (don't run it automatically)

---

## Hard constraints (NEVER violate)

These are critical. If a request would violate any of these, STOP and ask the user.

- ❌ **Never use `paper=False`**. The bot is paper-trading-only by design.
- ❌ **Never commit `.env` or write secrets to code/logs/URLs**.
- ❌ **Never use `eval()` or `exec()`** on any input.
- ❌ **Never use bare `except:`** clauses.
- ❌ **Never bind the dashboard to `0.0.0.0`**. Localhost only (`127.0.0.1`).
- ❌ **Never add web-based code upload features**. The user explicitly declined this.
- ❌ **Never add real-money trading code paths**, even disabled or behind flags.

## Banned dependencies

Do not introduce any of these. The user has explicitly chosen alternatives.

- FastAPI / Flask / Django (we use Streamlit for UI)
- React / Vue / HTMX / Jinja2
- Celery / Redis / RabbitMQ
- PostgreSQL / MySQL / MongoDB (we use SQLite)
- Docker / Kubernetes
- APScheduler (we use a simple `while True` loop)
- pip / poetry / pipenv (we use UV)

If you think one of these is needed, STOP and ask first.

---

## Tech stack

- **Python 3.12** managed by UV
- **SQLite** with WAL mode
- **alpaca-py** SDK for trading API
- **Streamlit** for the dashboard
- **systemd** for service management on the server
- **Telegram bot** for alerts (optional)

---

## File structure (final state after all phases)

```
trading-bot/
├── pyproject.toml
├── .python-version
├── .env.example
├── .env                  # gitignored
├── .gitignore
├── README.md             # user-facing, written in Phase 10
├── CLAUDE.md             # this file
├── bot.py                # main loop
├── dashboard.py          # Streamlit UI
├── db.py                 # SQLite layer
├── config.py             # default constants
├── safety.py             # kill switch + risk limits
├── broker.py             # Alpaca wrapper (rate limit + slippage)
├── notifications.py      # Telegram alerts
├── strategies/
│   ├── __init__.py       # strategy registry
│   ├── base.py           # BaseStrategy ABC
│   └── rsi_strategy.py   # default RSI implementation
├── deploy/
│   ├── trading-bot.service
│   ├── trading-dashboard.service
│   ├── install.sh
│   └── update.sh
├── logs/                 # gitignored, created on first run
├── trading.db            # gitignored, SQLite database
└── instructions/                 # build docs (this is your instruction set)
    ├── 00_OVERALL_PLAN.md
    ├── 01_PHASE_SCAFFOLDING.md
    ├── ...
    ├── PATTERNS.md
    └── CHECKLIST.md
```

---

## When in doubt

1. Prefer **simpler** over more complex.
2. Prefer **safer** over more permissive (always favor preventing bad trades).
3. Match patterns shown in `instructions/PATTERNS.md`.
4. If uncertain whether something violates the constraints above — **ask, don't assume**.

---

## Common pitfalls to avoid

- Don't add features the phase didn't ask for ("scope creep")
- Don't refactor existing code unless the phase explicitly says to
- Don't skip verification blocks — the user relies on them
- Don't write tests yet (testing framework will be added later)
- Don't add fancy error formatting; use the patterns in `PATTERNS.md`
- Don't import strategy logic into `bot.py` directly — go through the registry
- Don't call Alpaca clients directly outside `broker.py`
- Don't access SQLite directly outside `db.py`

---

## How to update this file

This CLAUDE.md is intentionally short. If you find yourself repeating context across sessions, add it here. If a phase introduces a new pattern that should apply to all future sessions, add a one-liner here pointing to the relevant section in `instructions/`.