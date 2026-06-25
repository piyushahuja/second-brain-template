---
name: log
description: >
  Log structured data to the daily tracker (raw_sources/tracker/YYYY-MM-DD.json).
  Use this skill when the user sends trackable data — weight, exercise, meals,
  mood, work hours, spending, or any domain metric — whether via /log command
  or as natural language in a domain topic. Merges into existing data, never
  overwrites unrelated fields.
compatibility: Claude Code with access to raw_sources/tracker/
allowed-tools: Read Write
---

# Skill: log

Log structured data to the daily tracker.

## Trigger

- Natural language in a domain topic: "75kg, ran 30min"
- Explicit command: `/log weight 75kg exercise running 30min`
- Any message that contains trackable data

## Input

Freeform text containing one or more data points. The skill parses based on:
1. **Domain context** — which Telegram topic the message came from
2. **Keywords** — weight, exercise, mood, spend, read, etc.
3. **Values** — numbers with units, durations, boolean indicators

## Output

1. Parse input into structured fields
2. Load existing `raw_sources/tracker/YYYY-MM-DD.json` (or create)
3. Merge new fields (never overwrite unrelated fields)
4. Save updated tracker file
5. Confirm what was logged

## Files Touched

- **Reads**: `raw_sources/tracker/YYYY-MM-DD.json` (if exists)
- **Writes**: `raw_sources/tracker/YYYY-MM-DD.json`

## Domain Parsing Rules

Adapt these to match domains defined in USER.md:

| Domain | Keywords | Fields |
|--------|----------|--------|
| Health | weight, kg, exercise, ran, walked, gym, calories | weight_kg, exercise, exercise_type, exercise_minutes, calories |
| Work | wrote, shipped, meeting, deep work | deep_work_hours, meetings, notes |
| Personal | mood, journal, grateful | mood (1-5), journal (bool), gratitude |
| Finance | spent, bought, paid | spend, category, notes |

## Example

**Input** (in Health topic):
```
75.2 kg, weights 45min, 1800 cal
```

**Processing**:
1. Detect domain: Health (from topic)
2. Parse: weight=75.2, exercise_type=weights, exercise_minutes=45, calories=1800
3. Load today's tracker (may have other domains already)
4. Merge health fields
5. Save

**Output**:
```
Logged: weight 75.2 kg, exercise weights 45min, calories 1800
```

## Error Handling

- If parsing is ambiguous, ask for clarification
- If domain is unclear (general topic), ask which domain
- Never silently fail — confirm what was logged or report the issue
