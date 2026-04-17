# Phase 3 — Notifications (`notifications.py`)

> **Prerequisite**: Phases 1–2 complete.

## Goal
Telegram alert sender. Built early so all subsequent phases can use it.

## Tasks

### 1. Implement `notifications.py`

Required exports:
- `send_alert(message: str, level: str = "info") -> bool`
- `send_startup() -> bool`
- `send_shutdown() -> bool`

### 2. Levels and emoji prefixes

| Level | Emoji | When to use |
|---|---|---|
| `info` | ℹ️ | Status updates |
| `trade` | 💰 | Buy/sell execution |
| `warning` | ⚠️ | Non-fatal issues |
| `error` | 🔴 | Caught exceptions |
| `critical` | 🚨 | Safety stops, kill switch triggers |

### 3. Implementation requirements

- Read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from environment via `python-dotenv`.
- If either env var is missing or empty:
  - Print to console: `[NOTIFICATIONS] Skipping (no Telegram config): <message>`
  - Return `False`
  - Do NOT crash
- Use `requests.post()` with `timeout=10`.
- Telegram API endpoint: `https://api.telegram.org/bot<TOKEN>/sendMessage`
- POST body: `{"chat_id": <CHAT_ID>, "text": <prefixed_message>, "parse_mode": "Markdown"}`
- On HTTP error or timeout:
  - Call `db.log("ERROR", f"Telegram alert failed: {e}")`
  - Return `False`
  - Do NOT raise

### 4. Helper implementations

```python
def send_startup() -> bool:
    return send_alert("Bot started in PAPER TRADING mode", "info")

def send_shutdown() -> bool:
    return send_alert("Bot shutting down", "info")
```

### 5. Pattern reference
See `PATTERNS.md > Error Handling` for exception patterns.

---

## Verification

```bash
# Without Telegram env vars set
uv run python -c "import notifications; notifications.send_alert('test')"
# Expected: prints '[NOTIFICATIONS] Skipping...' message, no crash

# With Telegram env vars set in .env
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
import notifications
result = notifications.send_alert('Phase 3 verification test', 'info')
print('Sent:', result)
"
# Expected: Telegram message arrives, prints 'Sent: True'

# Invalid Telegram token doesn't crash
TELEGRAM_BOT_TOKEN=fake TELEGRAM_CHAT_ID=fake \
uv run python -c "import notifications; notifications.send_alert('test')"
# Expected: error logged to bot_log table, returns False, no crash
```

If all 3 checks pass, Phase 3 is complete. Proceed to `04_PHASE_SAFETY.md`.

---

## Telegram setup (instructions for the human user, not for Claude Code)

> User: do this once before running the bot in production.
> 1. Open Telegram, search `@BotFather`, send `/newbot`, follow prompts.
> 2. Save the bot token to `.env` as `TELEGRAM_BOT_TOKEN`.
> 3. Search `@userinfobot`, send any message, get your numeric chat ID.
> 4. Save the chat ID to `.env` as `TELEGRAM_CHAT_ID`.
> 5. Send any message to your new bot first (Telegram requires this before bot can DM you).
