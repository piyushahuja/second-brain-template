---
name: status
description: >
  Show a quick status check for one domain or all domains — what was logged
  today, what's missing, and 7-day trends compared to targets in USER.md.
  Use this skill when the user sends /status, asks "how am I doing", "what
  have I logged today", or wants to check progress against their goals.
compatibility: Claude Code with access to raw_sources/ and USER.md
allowed-tools: Read
---

# Skill: status

Quick status check for a domain or all domains.

## Trigger

- `/status` — all domains summary
- `/status health` — specific domain
- "How am I doing?" — general status
- "What have I logged today?" — today's data

## Input

Optional domain name. If omitted, show all domains.

## Output

1. Load today's tracker data
2. Load USER.md for targets (if defined)
3. Compare logged vs expected
4. Show trend context (last 7 days if available)
5. Return concise status

## Files Touched

- **Reads**:
  - `raw_sources/tracker/YYYY-MM-DD.json` (today)
  - `raw_sources/tracker/*.json` (last 7 days for trends)
  - `USER.md` (for targets)

## Status Format

```
[Domain]: [logged items] | [missing items]
Trend: [7-day context]
```

## Example

**Input**: `/status health`

**Processing**:
1. Load today's health data from tracker
2. Load USER.md health targets (e.g., daily exercise, weight tracking)
3. Check last 7 days for weight trend

**Output**:
```
Health today:
  ✓ Weight: 75.2 kg
  ✓ Exercise: weights 45min
  ✗ Calories: not logged

Trend (7d): weight ↓0.8 kg, exercise 5/7 days
```

## Domain Expectations

Define in USER.md what "complete" means per domain:

```markdown
## Targets

### Health
- Log weight daily
- Exercise 5x/week
- Track calories

### Work
- Log deep work hours
- Note key accomplishments
```

The status skill reads these to determine what's missing.

## No Data Case

If no tracker exists for today:
```
Nothing logged today. Start with /log or send data in a domain topic.
```
