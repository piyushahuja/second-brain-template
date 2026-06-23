# Integrations

Each subdirectory represents an installed data source or infrastructure component.

## manifest.json Schema

```json
{
  "name": "example",
  "label": "Example Service",
  "description": "What this integration does",
  "category": "data_source | infrastructure",
  "auth": {
    "type": "personal_access_token | oauth2 | api_key | file_sync | setup_token",
    "env_key": "ENV_VAR_NAME",
    "setup_url": "https://..."
  },
  "health": {
    "type": "api_call | command | file_exists",
    "url": "https://api.example.com/health",
    "auth_header": "Authorization Bearer $ENV_VAR",
    "expect_status": 200
  },
  "cron": {
    "schedule": "0 6 * * *",
    "script": "integrations/example/sync.sh"
  },
  "required": false
}
```

## Auth Types

| Type | Description | Example |
|------|-------------|---------|
| `api_key` | Static API key | Anthropic, OpenAI |
| `personal_access_token` | User-generated token | Oura, GitHub |
| `oauth2` | OAuth2 flow | Google, Zoom |
| `file_sync` | Syncthing-based | Obsidian, WhatsApp |
| `setup_token` | One-time setup | Claude Code |

## Health Check Types

| Type | Description |
|------|-------------|
| `api_call` | HTTP GET to URL, check status code |
| `command` | Run shell command, check exit code |
| `file_exists` | Check file/directory exists |

## Adding a New Integration

1. Create `integrations/<name>/manifest.json`
2. Add env vars to `deploy/.env.example`
3. (Optional) Add sync script: `integrations/<name>/sync.sh`
4. (Optional) Register cron job in `cron/registry.json`
