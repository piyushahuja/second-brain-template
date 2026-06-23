# Second Brain — Architecture

A personal AI assistant that runs on a VPS, accessible via Telegram, powered by Claude Code. Always on, always remembering.

---

## Design Principles

1. **Vault-first** — your knowledge base is the source of truth; the bot reads and writes structured data
2. **Claude Code as runtime** — full tool access, session persistence, skills (not raw API calls)
3. **Telegram as interface** — mobile-native, asynchronous, works offline
4. **Domain-aware routing** — optionally use Telegram topics to route messages to domains. Domains could be (for example): 7F framework, or learning, work, relationships, spirit, health, investments. 
5. **Personality-aware** — SOUL.md defines who the assistant is
6. **Compounding knowledge** — every interaction can enrich outputs

---

## Quick Start

### Before you begin

You'll need three things before running setup:

1. **Telegram bot token** — message [@BotFather](https://t.me/BotFather) → `/newbot`
2. **Your Telegram user ID** — message [@userinfobot](https://t.me/userinfobot)
3. **Anthropic API key** — [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) (or use `claude login` after install)

### 1. Fork this template

Create a new repo for the client on GitHub (e.g. `client-brain`), then push this template to it.

### 2. Bootstrap on the VPS

Run this on a fresh machine — it clones the repo, collects credentials, installs everything, and starts the bot:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/you/second-brain-template/main/bootstrap.sh) \
  --repo git@github.com:you/client-brain.git
```

Or with optional components:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/you/second-brain-template/main/bootstrap.sh) \
  --repo git@github.com:you/client-brain.git --with-admin --with-gemini
```

The script will prompt for credentials, clone the repo to `~/second-brain`, write `deploy/.env`, run `deploy/install.sh`, and start the service.

### 3. Personalise

Fill in these files from the client's onboarding responses:

| File | Purpose |
|------|---------|
| `USER.md` | Identity, domains, priorities, targets |
| `SOUL.md` | Personality, tone, boundaries |
| `deploy/.env` | Secrets (Telegram token, API keys) |

### 4. Start (if not already running)

```bash
# Linux (systemd)
systemctl --user daemon-reload && systemctl --user enable --now second-brain-bot
systemctl --user status second-brain-bot

# macOS (launchd)
launchctl load ~/Library/LaunchAgents/com.secondbrain.bot.plist
```

---

## Directory Structure

```
second-brain/
│
├── CLAUDE.md                 # Schema: conventions, operations, rules
├── SOUL.md                   # Personality: tone, values, boundaries
├── USER.md                   # User identity: domains, priorities, targets
├── MEMORY.md                 # Curated long-term facts (LLM-maintained)
├── ARCHITECTURE.md           # This file
│
├── index.md                  # Catalog of output pages (LLM-maintained)
├── log.md                    # Chronological operation history (append-only)
│
├── raw_sources/              # Input data — READ ONLY for Claude
│   ├── tracker/              # Daily structured data (YYYY-MM-DD.json)
│   ├── photos/               # Images (meals, receipts, etc.)
│   ├── voice/                # Voice notes + transcripts
│   └── ...                   # Add more as needed (oura/, gmail/, etc.)
│
├── outputs/                  # LLM-generated artifacts
│   ├── reports/              # Digests, reviews
│   ├── dashboards/           # Synthesised web apps
│   ├── outputs_shared/             # Active project notes
│   └── summaries/            # Source summaries
│
├── skills/                   # Skill definitions (SKILL.md per skill)
│   ├── log/                  # Log data to tracker
│   ├── status/               # Quick status check
│   └── digest/               # Scheduled briefing
│
├── integrations/             # Installed data sources (manifest.json per source)
│   └── anthropic/            # Required: Claude API
│
├── catalog/                  # Available sources to install
│   └── .gitkeep
│
├── admin/                    # Web admin panel (optional)
│   ├── app.py                # Flask app
│   └── routes/
│       └── status.py         # /api/status endpoint
│
├── bot/                      # Telegram bot
│   ├── bot.py                # Main bot
│   ├── system-prompt.md      # Session system prompt
│   └── state/                # Session persistence
│
├── cron/                     # Scheduled jobs
│   ├── registry.json         # Job registry
│   └── run-skill.sh          # Generic skill runner
│
├── deploy/                   # Deployment config
│   ├── install.sh            # VPS setup script
│   └── .env.example          # Environment variables template
│
└── .claude/                  # Claude Code custom commands
    └── commands/
```

---

## Data Patterns

Every data source follows one of three patterns:

### Pattern A — Bot-captured (real-time)

**Flow:** User → Telegram → bot.py → VPS filesystem

| Source | Path |
|--------|------|
| Daily tracker | `raw_sources/tracker/YYYY-MM-DD.json` |
| Photos | `raw_sources/photos/<category>/YYYY-MM-DD/` |
| Voice notes | `raw_sources/voice/YYYY-MM-DD/` |

### Pattern B — Cloud-polled (scheduled)

**Flow:** VPS cron → external API → VPS filesystem

| Source | Path | Auth |
|--------|------|------|
| Oura | `raw_sources/oura/YYYY-MM-DD.json` | Personal token |
| Gmail | `raw_sources/gmail/YYYY-MM-DD.json` | OAuth2 |
| Calendar | `raw_sources/calendar/YYYY-MM-DD.json` | OAuth2 |

### Pattern C — Syncthing-delivered (Mac → VPS)

**Flow:** Mac app → Syncthing → `raw_sources/<source>/` on VPS

| Source | Example path |
|--------|--------------|
| Obsidian vault | `raw_sources/obsidian_vault/` |
| WhatsApp export | `raw_sources/whatsapp/` |

---

## Integration Architecture

Data sources are defined as manifests under `integrations/<name>/manifest.json`.

### manifest.json schema

```json
{
  "name": "oura",
  "label": "Oura Ring",
  "description": "Daily sleep score, readiness, HRV",
  "auth": {
    "type": "personal_access_token",
    "env_key": "OURA_TOKEN",
    "setup_url": "https://cloud.ouraring.com/personal-access-tokens"
  },
  "health": {
    "type": "api_call",
    "url": "https://api.ouraring.com/v2/usercollection/personal_info",
    "auth_header": "Authorization Bearer $OURA_TOKEN",
    "expect_status": 200
  }
}
```

**Auth types:** `personal_access_token` | `oauth2` | `api_key` | `file_sync` | `setup_token`

### Catalog vs Integrations

- `catalog/` — available sources not yet installed
- `integrations/` — installed sources with credentials configured

Install = copy manifest to `integrations/` + add env vars + register cron (if applicable).

---

## Tracker Schema

Daily data logged via `/log` skill writes to `raw_sources/tracker/YYYY-MM-DD.json`. Structure depends on your domains — here's an example:

```json
{
  "date": "2026-06-09",
  "health": {
    "weight_kg": 75.2,
    "exercise": true,
    "exercise_type": "running",
    "exercise_minutes": 30
  },
  "work": {
    "deep_work_hours": 4,
    "meetings": 2,
    "notes": "Shipped feature X"
  },
  "personal": {
    "mood": 4,
    "journal": true
  }
}
```

Define your own schema in USER.md → the `/log` skill parses accordingly.

---

## Core Operations

### Log (domain-aware)

```
User [in Health topic]: 75.2 kg, ran 30min
Bot: Logged: weight 75.2 kg, exercise running 30min
```

### Status

```
User: /status health
Bot: Today: weight logged, exercise not logged. Week trend: ↓0.3 kg
```

### Digest (scheduled)

```
[Morning cron]
Bot: Good morning. Today: 3 meetings, weight on track, 2 tasks due.
```

---

## Telegram Setup

### Option A: Simple DM

Just message the bot directly. No domain routing.

### Option B: Group with Topics (recommended)

1. Create private Telegram group
2. Enable Forum Mode (Settings → Topics)
3. Create one topic per domain
4. Get topic IDs from bot logs
5. Add to `.env`:

```bash
GROUP_CHAT_ID=-100xxxxxxxxxx
TOPIC_HEALTH=2
TOPIC_WORK=3
TOPIC_PERSONAL=4
```

---

## Session Management

- **Auto-reset**: After `MAX_QUERIES` (default 50) or `MAX_HOURS` (default 8)
- **Manual reset**: `/reset` command
- **System prompt**: Loaded from `bot/system-prompt.md`
- **Context files**: CLAUDE.md, SOUL.md, USER.md referenced in system prompt

---

## Cron Jobs

Jobs are registered in `cron/registry.json`:

```json
{
  "jobs": [
    {
      "name": "morning-digest",
      "schedule": "30 7 * * *",
      "script": "cron/run-skill.sh /digest",
      "enabled": true
    }
  ]
}
```

Run manually: `./cron/run-skill.sh /digest`

---

## Admin Panel (optional)

Minimal Flask app at `admin/app.py`, served at `http://VPS_IP:8080/admin`.

Features:
- Service status (bot running, RAM/disk)
- Cron job management
- Integration health checks
- Environment variable viewer

Secured by `ADMIN_TOKEN` header.

---

## VPS Requirements

- Ubuntu 22.04+ (or macOS for local dev)
- Python 3.11+
- 1GB RAM minimum
- Claude Code CLI installed and authenticated

Optional for voice notes:
- Whisper (`pip install openai-whisper`)
- ffmpeg

Optional for Mac sync:
- Syncthing

---

## Adding a Skill

Create `skills/<name>/SKILL.md`:

```markdown
# Skill: <name>

## Trigger
Phrases or commands that invoke this skill.

## Input
What the user provides.

## Output
What the skill produces.

## Files Touched
- Reads: ...
- Writes: ...

## Example
User: ...
Bot: ...
```

The bot reads SKILL.md before executing.

---

## Customisation Points

| What | Where | When |
|------|-------|------|
| Personality | SOUL.md | Different tone needed |
| Operations | CLAUDE.md | Different workflows |
| Domains | USER.md + .env topics | Always — from onboarding |
| User context | USER.md | Always — from onboarding |
| Skills | skills/ | As patterns emerge |
| Integrations | integrations/ | When adding data sources |

---

## Onboarding Checklist

Send to client before setup:

- [ ] Name, timezone, current life phase
- [ ] 3-7 life/work domains to track
- [ ] Current priorities and targets
- [ ] Preferred communication style
- [ ] Data sources they want connected
- [ ] Morning/evening routine preferences
- [ ] Key people to know about

Use responses to fill USER.md.

---

## Security Notes

- Bot whitelisted to single Telegram user ID
- API keys in `.env`, never committed
- Admin panel protected by `ADMIN_TOKEN`
- `raw_sources/` may contain sensitive data — encrypt at rest recommended
