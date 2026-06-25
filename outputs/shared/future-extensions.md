---
type: reference
title: Future Extensions Roadmap
description: Architectural improvements and extensions identified through analysis of Hermes Agent, GBrain, OKF, and agentskills.io
tags: [architecture, roadmap, extensions, memory, platform, mcp]
timestamp: 2026-06-24
status: active
---

# Future Extensions Roadmap

Distilled from analysis of [Hermes Agent](https://github.com/nousresearch/hermes-agent), [GBrain](https://github.com/garrytan/gbrain), [OKF spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), and [agentskills.io](https://agentskills.io).

Each extension is rated by effort and value, with a recommended trigger (when it earns its complexity).

---

## 1. Typed Schemas per Page Type

**Status: Do now — zero infrastructure, immediate value**

Define a mandatory frontmatter schema per output page type in CLAUDE.md. Claude enforces these on write; queries become filterable without reading page bodies.

### Schema definitions

```yaml
# type: person
---
type: person
name: Alice Chen
company: Acme Corp
role: Head of Data
relationship: colleague     # colleague | friend | mentor | client | vendor | family
last_contact: 2026-06-15
tags: [work, data]
---

# type: project
---
type: project
name: Project X
status: active              # active | paused | complete | abandoned
owner: Alice Chen
deadline: 2026-08-01
priority: high              # high | medium | low
tags: [work, q3]
---

# type: summary
---
type: summary
source: book-title-or-url
author: Author Name
date_ingested: 2026-06-24
tags: [domain, topic]
---

# type: report
---
type: report
date: 2026-06-24
period: weekly              # daily | weekly | monthly | quarterly
domains: [health, work]
tags: []
---

# type: insight
---
type: insight
domain: health
confidence: high            # high | medium | low
source: tracker             # tracker | conversation | external
timestamp: 2026-06-24
tags: []
---

# type: decision
---
type: decision
domain: work
status: made                # proposed | made | reversed
date: 2026-06-24
context: why this decision was needed
tags: []
---
```

### Why it matters

With typed schemas, Claude can answer "list all active projects with August deadlines" by reading frontmatter only — skipping every page body. Combined with a SQLite index (see §3), these become instant structured queries.

**Trigger:** Now. Add to CLAUDE.md immediately.

---

## 2. Gap Analysis + Search→Synthesize Flow

**Status: Do now — prompting change only, no infrastructure**

Add a mandatory three-step flow to CLAUDE.md and bot/system-prompt.md for any query that touches the knowledge base.

### The flow

```
Step 1 — SEARCH
  Explicitly state what you're looking for and where before reading files.
  "Looking for: Alice's notes, project X pages, health data from June"

Step 2 — SYNTHESIZE
  Answer from what you found.

Step 3 — GAP ANALYSIS (required)
  Always append a gap section:
  - Data not found: "No sleep data logged this week"
  - Stale pages: "Project X page last updated 3 months ago"
  - Contradictions: "Page A says X, page B says Y — unclear which is current"
  - Missing pages: "No person page exists for Bob yet"
```

### Knowledge audit skill (future)

A `/audit` skill that reads index.md and all output pages, then reports:
- Pages not updated in 60+ days
- Pages with incomplete frontmatter
- Broken wiki links
- Domains with no data logged in 7+ days

**Trigger:** Add search→synthesize + gap analysis to system prompt now. Build `/audit` skill when outputs/ has 30+ pages.

---

## 3. SQLite Memory Layer

**Status: Build at two trigger points**

### Trigger A: Tracker queries (~3 months of data, ~90 JSON files)

When "how many days did I exercise this month?" requires Claude to read 30 JSON files, migrate tracker data to SQLite.

**Architecture:** Keep JSON files as source of truth (git-tracked, human-readable). Add a sync script that imports them into `tracker.db`.

```sql
CREATE TABLE tracker (
  date      TEXT,
  domain    TEXT,
  field     TEXT,
  value     TEXT,
  PRIMARY KEY (date, domain, field)
);

-- How many exercise days in June?
SELECT COUNT(*) FROM tracker
WHERE date LIKE '2026-06-%'
  AND domain = 'health'
  AND field  = 'exercise'
  AND value  = 'true';

-- Average weight this month
SELECT AVG(CAST(value AS REAL)) FROM tracker
WHERE date LIKE '2026-06-%'
  AND domain = 'health'
  AND field  = 'weight_kg';
```

Claude queries via `Bash` tool: `sqlite3 tracker.db "SELECT ..."`. No new tooling needed.

### Trigger B: Knowledge page search (~100 output pages)

When loading index.md + all outputs/ pages burns too much context, add an FTS5 index over frontmatter.

```sql
CREATE VIRTUAL TABLE pages USING fts5(
  type,
  title,
  description,
  tags,
  path UNINDEXED,
  timestamp UNINDEXED
);

-- Find person pages related to investing
SELECT path, title FROM pages
WHERE pages MATCH 'type:person AND investing'
ORDER BY bm25(pages) LIMIT 10;
```

**Sync script:** `scripts/build-index.sh` — reads all `outputs/**/*.md` frontmatter → inserts into `pages` table. Run at startup or on cron.

Claude queries the index first (fast, cheap), then reads the full markdown files for top results only.

### Trigger C: Semantic search / large brain (500+ pages)

Upgrade to Postgres + pgvector. Options:
- Self-hosted Postgres on VPS (more RAM, more maintenance)
- Supabase managed (free tier: 500MB — enough for a personal brain for years)

At this scale, the query pattern becomes: embed the user's question → cosine similarity search → return top-k chunks → Claude synthesizes.

**Don't build this prematurely.** Claude's 200k context window can hold ~150-200 pages. That's the ceiling before RAG is necessary.

---

## 4. Knowledge Graph (Entity Relationships)

**Status: Start manual, automate later**

### Phase 1: Manual relationships in frontmatter (now)

Add a `relationships` block to person and project pages. Human-maintained, precise, zero infrastructure.

```yaml
---
type: person
name: Alice Chen
relationships:
  - entity: Acme Corp
    type: works_at
  - entity: Project X
    type: leads
  - entity: Bob Smith
    type: collaborates_with
    context: co-founded the data team
---
```

Claude reads these when asked "who do I know at Acme?" — no graph traversal needed, just frontmatter filtering.

### Phase 2: Link graph from wiki links (100+ pages)

Our wiki links `[[outputs/people/alice.md]]` are already an untyped graph. A script can build a `edges` table from them:

```sql
CREATE TABLE edges (
  source TEXT,   -- page path
  target TEXT,   -- referenced page path
  type   TEXT    -- 'mentions' | frontmatter relationship type
);
```

Enables: "show me all pages that mention Alice" without reading every file.

### Phase 3: NLP entity extraction (if needed, 500+ pages)

Use spaCy for named entity recognition on page bodies. Extracts people, companies, places automatically. Not recommended until phase 2 is saturated — manual relationships are more accurate at small scale, and LLM-assisted extraction (when ingesting a new page) is more semantically rich than NLP heuristics.

**Skip:** zero-LLM NLP extraction a la GBrain. Their constraint is cost at thousands-of-users scale. Our constraint is different.

---

## 5. Multi-Platform Gateway

**Status: Extract Channel ABC now; add platforms on demand**

### Architecture

```
┌──────────────────────────────────────────────────────┐
│  CHANNELS  (one class per platform)                  │
│                                                      │
│  class Channel(ABC):                                 │
│      async def send(text, topic=None)                │
│      async def start(on_message: Callable)           │
│                                                      │
│  TelegramChannel   — done                            │
│  SlackChannel      — add when needed                 │
│  SignalChannel     — signal-cli, good for privacy    │
└──────────────────────┬───────────────────────────────┘
                       │ on_message(text, user_id, topic)
┌──────────────────────▼───────────────────────────────┐
│  ORCHESTRATOR  (platform-agnostic)                   │
│  Spawns claude, reads response, calls channel.send() │
│  Manages session state                               │
└──────────────────────────────────────────────────────┘
```

Entry point:
```python
channels = [TelegramChannel(cfg), SlackChannel(cfg)]
orchestrator = Orchestrator(channels)
asyncio.gather(*[ch.start(orchestrator.on_message) for ch in channels])
```

### Platform notes

| Platform | SDK | Complexity | Notes |
|---|---|---|---|
| Telegram | python-telegram-bot | Done | Best fit. Topics = domains. |
| Slack | slack-sdk (Socket Mode) | Low | `#health`, `#work` channels → domains. Free. |
| Signal | signal-cli (Java) | Medium | End-to-end encrypted. No official Python SDK. |
| WhatsApp | Twilio Business API | High + cost | Unofficial clients risk account bans. |
| Discord | discord.py | Low | Good if user already uses Discord. |

**Recommendation:** Add Slack next (cleanest fit), skip WhatsApp unless essential (no safe free option).

**Don't build** a full Hermes-style registry with `check_fn`, `validate_config`, `adapter_factory`. A simple list of Channel instances is sufficient for ≤ 5 platforms.

---

## 6. MCP Exposure

**Status: Build when you need cross-context access**

MCP (Model Context Protocol) makes the second brain queryable from Claude Desktop, Cursor, Codex, web UIs, or other agents — without going through Telegram.

### Minimal MCP server (4 tools)

```python
# mcp_server.py
from mcp.server import Server

server = Server("second-brain")

@server.tool()
async def search_brain(query: str) -> str:
    """Search knowledge base — outputs/, MEMORY.md, tracker"""
    # Spawns: claude -p "search for: {query}" in workspace
    ...

@server.tool()
async def log_data(domain: str, data: dict) -> str:
    """Log structured data to daily tracker"""
    # Direct file write — no Claude spawn needed
    ...

@server.tool()
async def get_status(domain: str = None) -> str:
    """Quick status check across domains"""
    # Spawns: claude -p "/status {domain}"
    ...

@server.tool()
async def capture(text: str) -> str:
    """Capture a quick note to inbox"""
    # Direct file write — fast, no Claude spawn
    ...
```

Claude Desktop config:
```json
{
  "mcpServers": {
    "second-brain": {
      "command": "python",
      "args": ["/home/user/second-brain/mcp_server.py"]
    }
  }
}
```

### Tool latency notes

- `log_data`, `capture` → direct file operations, instant
- `search_brain`, `get_status` → spawn Claude Code session, 5-15s acceptable
- `get_digest` → too slow for MCP (~60-120s), omit or make async

### Alternative: HTTP API

The admin panel already has Flask. A simple HTTP API (`GET /api/search?q=...`, `POST /api/log`) gets 80% of the MCP benefit with 20% the effort — and any script, web UI, or curl can call it. Add this before MCP if a web UI or scripting access is the main need.

**Trigger:** Build MCP when you want Claude Desktop or Cursor integration specifically. Build HTTP API first if you want web UI or scripting access.

---

## 7. Skills: agentskills.io Compliance

**Status: Done (frontmatter added 2026-06-24)**

All three skills now have compliant YAML frontmatter (`name`, `description`, `compatibility`, `allowed-tools`).

### Future skills to build

| Skill | Trigger phrase | Value |
|---|---|---|
| `/audit` | "audit the brain", "what's stale" | Surfaces gaps and stale pages |
| `/weekly` | "weekly review", "/weekly" | Cross-domain weekly synthesis |
| `/capture` | "remember this", "note: ..." | Fast freeform capture to inbox/ |
| `/ingest <url>` | "read and summarize this" | Web page / document ingestion |
| `/people` | "who do I know at X" | Query person pages + relationships |
| `/search <query>` | "find notes about X" | Explicit knowledge base search |

Skills go in `skills/<name>/SKILL.md`. Scripts (if any) go in `skills/<name>/scripts/`. Reference docs in `skills/<name>/references/`.

---

## Priority Order

| Extension | Effort | Value | Trigger |
|---|---|---|---|
| Typed schemas in CLAUDE.md | Low | High | **Now** |
| Gap analysis in system prompt | Low | High | **Now** |
| `relationships` in person frontmatter | Low | Medium | **Now, as pages grow** |
| SQLite tracker queries | Low | High | ~3 months of data |
| `/audit` skill | Low | Medium | ~30 output pages |
| Channel ABC + SlackChannel | Medium | Medium | Second platform needed |
| SQLite FTS over outputs/ | Medium | High | ~100 output pages |
| HTTP API (admin panel) | Low | Medium | Web UI or script access needed |
| MCP server | Medium | High | Claude Desktop / Cursor integration |
| Link graph from wiki links | Medium | Medium | ~100 pages |
| Postgres + pgvector | High | High | 500+ pages, semantic search needed |
| NLP entity extraction | High | Low | Probably never at personal scale |
| WhatsApp | High | Low | Probably never (no safe free API) |

---

## References

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — multi-platform gateway, memory provider pattern, skill registry
- [GBrain](https://github.com/garrytan/gbrain) — hybrid retrieval (vector + BM25 + graph), typed schemas, gap analysis, MCP exposure
- [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) — frontmatter conventions, index.md + log.md patterns
- [agentskills.io](https://agentskills.io/specification) — SKILL.md spec, progressive disclosure, description optimization

---

*Last updated: 2026-06-24*
