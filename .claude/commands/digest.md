# /digest

Generate and send the daily briefing.

## Instructions

1. Read `skills/digest/SKILL.md` for the skill definition
2. Load today's date and check for calendar data in `raw_sources/calendar/`
3. Load recent tracker data from `raw_sources/tracker/` (last 7 days)
4. Read `USER.md` for priorities and targets
5. Generate a concise briefing covering:
   - Today's schedule (if calendar data exists)
   - Yesterday's domain status
   - Current focus areas
   - Items needing attention
6. Output the briefing to stdout (for Telegram delivery)

## Output Format

Keep it mobile-friendly — short paragraphs, emoji headers, bullet points.
