# /status

Show current status for one or all domains.

## Arguments

- No args: show all domains
- Domain name: show specific domain (e.g., `/status health`)

## Instructions

1. Read `skills/status/SKILL.md` for the skill definition
2. Load today's tracker from `raw_sources/tracker/YYYY-MM-DD.json`
3. Load USER.md for domain targets
4. For each domain (or requested domain):
   - Show what's been logged today
   - Show what's missing vs targets
   - Include 7-day trend if data exists
5. Keep output concise for mobile

## Output Format

```
[Domain]: ✓ logged | ✗ missing
Trend: context
```
