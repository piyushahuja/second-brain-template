# Skill: digest

Daily briefing with status across all domains.

## Trigger

- `/digest` — manual trigger
- Cron job (default: 7:30am) — automatic daily

## Input

None required. Optionally specify date: `/digest yesterday`

## Output

Morning briefing covering:
1. **Today's schedule** (if calendar integration enabled)
2. **Domain status** — what was logged yesterday, streaks, alerts
3. **Priorities** — from USER.md current focus
4. **Action items** — things that need attention

Output sent to Telegram (General topic or DM).

## Files Touched

- **Reads**:
  - `raw_sources/tracker/*.json` (recent days)
  - `raw_sources/calendar/YYYY-MM-DD.json` (if exists)
  - `USER.md` (priorities, targets)
  - `MEMORY.md` (relevant long-term context)

## Digest Format

```
Good morning.

📅 Today: [meeting count], [key events]

📊 Yesterday:
  Health: ✓ weight, ✓ exercise, ✗ calories
  Work: ✓ 4h deep work, shipped feature X
  Personal: ✓ journaled, mood 4/5

🎯 Focus: [current priority from USER.md]

⚠️ Attention:
  - [streak at risk]
  - [target falling behind]
```

## Cron Setup

In `cron/registry.json`:
```json
{
  "name": "morning-digest",
  "schedule": "30 7 * * *",
  "timezone": "America/New_York",
  "script": "./run-skill.sh /digest",
  "enabled": true
}
```

Adjust timezone to user's local time.

## Sending to Telegram

The digest skill should output to stdout. The cron runner pipes this to the bot, which sends to Telegram.

Alternative: skill can directly call Telegram API if `TELEGRAM_TOKEN` is available in env.

## Customisation

Users can adjust in USER.md:
- Which domains to include
- What "attention" thresholds trigger alerts
- Preferred digest length (brief vs detailed)

## No Data Case

If no recent tracker data:
```
Good morning. No data logged recently — send /log to start tracking.
```
