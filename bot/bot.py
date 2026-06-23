#!/usr/bin/env python3
"""
Second Brain Telegram Bot — Generic Template

Config-driven bot that routes messages to the configured AI provider.
Reads domains from config.yaml for topic routing.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("second-brain-bot")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR        = Path(__file__).parent
WORKSPACE_ROOT    = SCRIPT_DIR.parent
STATE_DIR         = SCRIPT_DIR / "state"
STATE_FILE        = STATE_DIR / "session.json"
CONFIG_FILE       = SCRIPT_DIR / "config.yaml"
SYSTEM_PROMPT_FILE = SCRIPT_DIR / "system-prompt.md"

STATE_DIR.mkdir(exist_ok=True)

# Make bot/ importable so we can load orchestrator.py from the same directory
sys.path.insert(0, str(SCRIPT_DIR))
from orchestrator import Orchestrator, create_orchestrator, OrchestratorUnavailable  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"domains": [], "telegram": {"use_topics": False}}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


CONFIG = load_config()

TOPIC_MAP: dict[int, str] = {}
DOMAIN_CONTEXT: dict[str, str] = {"general": "general queries"}

for domain in CONFIG.get("domains", []):
    name     = domain.get("name", "").lower()
    topic_id = domain.get("topic_id")
    context  = domain.get("context", "")
    if topic_id:
        TOPIC_MAP[int(topic_id)] = name
    if name:
        DOMAIN_CONTEXT[name] = context

log.info(f"Loaded {len(TOPIC_MAP)} domain topics: {list(TOPIC_MAP.values())}")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "0"))
MAX_QUERIES      = int(os.environ.get("MAX_QUERIES", "50"))
MAX_HOURS        = int(os.environ.get("MAX_HOURS", "8"))

if not TELEGRAM_TOKEN:
    log.error("TELEGRAM_TOKEN not set")
    sys.exit(1)

if not TELEGRAM_USER_ID:
    log.error("TELEGRAM_USER_ID not set")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------
def _load_orchestrators() -> tuple[Orchestrator, Orchestrator | None]:
    cfg           = CONFIG.get("orchestrators", {})
    default_name  = cfg.get("default", "claude")
    fallback_name = cfg.get("fallback")

    try:
        default = create_orchestrator(default_name)
    except ValueError as e:
        log.error(f"Invalid default orchestrator {default_name!r}: {e} — falling back to claude")
        default = create_orchestrator("claude")
        default_name = "claude"

    fallback = None
    if fallback_name and fallback_name != default_name:
        try:
            fallback = create_orchestrator(fallback_name)
        except ValueError as e:
            log.warning(f"Invalid fallback orchestrator {fallback_name!r}: {e} — disabled")

    log.info(
        f"Orchestrator: {default_name}"
        + (f" | fallback: {fallback_name}" if fallback_name else "")
    )
    return default, fallback


DEFAULT_ORCHESTRATOR, FALLBACK_ORCHESTRATOR = _load_orchestrators()

# ---------------------------------------------------------------------------
# Session State
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Failed to load state: {e}")
    return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save state: {e}")


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    log.info("Session state cleared")


def should_auto_reset() -> bool:
    state = load_state()
    if not state:
        return False

    if state.get("queries", 0) >= MAX_QUERIES:
        log.info(f"Auto-reset: query limit reached")
        return True

    created = state.get("created")
    if created:
        try:
            created_dt = datetime.fromisoformat(created)
            age_hours  = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
            if age_hours >= MAX_HOURS:
                log.info(f"Auto-reset: {age_hours:.1f}h old")
                return True
        except Exception as e:
            log.warning(f"Failed to parse created timestamp: {e}")

    return False


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
def load_system_prompt() -> str:
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text().strip()
    return f"Read CLAUDE.md, SOUL.md, and USER.md before responding. Working directory: {WORKSPACE_ROOT}"


# ---------------------------------------------------------------------------
# Query — with automatic fallback
# ---------------------------------------------------------------------------
async def query(prompt: str, domain: str = "general") -> str:
    if should_auto_reset():
        clear_state()

    state         = load_state()
    session_id    = state.get("session_id")
    system_prompt = load_system_prompt()

    if domain != "general" and domain in DOMAIN_CONTEXT:
        context = DOMAIN_CONTEXT[domain]
        prompt  = f"[Domain: {domain} — {context}]\n\n{prompt}"

    orchestrators_to_try = [(DEFAULT_ORCHESTRATOR, False)]
    if FALLBACK_ORCHESTRATOR:
        orchestrators_to_try.append((FALLBACK_ORCHESTRATOR, True))

    last_error = None
    for orchestrator, is_fallback in orchestrators_to_try:
        label = "fallback" if is_fallback else "primary"
        sid   = session_id if not is_fallback else None  # don't carry Claude sessions to Codex

        try:
            text, new_session_id = await orchestrator.query(prompt, sid, system_prompt)
            save_state({
                "session_id": new_session_id,
                "created":    state.get("created", datetime.now(timezone.utc).isoformat()),
                "queries":    state.get("queries", 0) + 1,
            })
            if is_fallback:
                text = f"_(via fallback orchestrator)_\n\n{text}"
            return text

        except OrchestratorUnavailable as e:
            log.warning(f"{label} orchestrator unavailable: {e}")
            last_error = str(e)
            # continue to next orchestrator

        except RuntimeError as e:
            err = str(e)
            if orchestrator.is_session_invalid(err):
                clear_state()
                return "Session expired. Please send your message again."
            log.error(f"{label} orchestrator error: {err}")
            return f"Error: {err[:300]}"

    return f"All orchestrators unavailable. Last error: {last_error or 'unknown'}"


# ---------------------------------------------------------------------------
# Domain Routing
# ---------------------------------------------------------------------------
def get_domain(update: Update) -> str:
    if not CONFIG.get("telegram", {}).get("use_topics"):
        return "general"
    thread_id = getattr(update.message, "message_thread_id", None)
    if thread_id and thread_id in TOPIC_MAP:
        return TOPIC_MAP[thread_id]
    return "general"


# ---------------------------------------------------------------------------
# Message Handling
# ---------------------------------------------------------------------------
async def send_reply(update: Update, text: str) -> None:
    thread_id = getattr(update.message, "message_thread_id", None)
    MAX_LEN   = 4096

    if len(text) <= MAX_LEN:
        await update.message.reply_text(
            text, message_thread_id=thread_id, parse_mode="Markdown"
        )
    else:
        chunks = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            await update.message.reply_text(
                chunk, message_thread_id=thread_id, parse_mode="Markdown"
            )
            await asyncio.sleep(0.3)


def is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else 0
    return user_id == TELEGRAM_USER_ID


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        log.warning(f"Unauthorized: {update.effective_user.id}")
        return

    if not update.message or not update.message.text:
        return

    text   = update.message.text.strip()
    domain = get_domain(update)

    log.info(f"Message in {domain}: {text[:50]}...")
    await update.message.chat.send_action("typing")

    response = await query(text, domain)
    await send_reply(update, response)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    clear_state()
    await update.message.reply_text("Session reset. Next message starts fresh.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    state = load_state()
    cfg   = CONFIG.get("orchestrators", {})
    prov  = cfg.get("default", "claude")
    fb    = cfg.get("fallback")

    provider_line = f"Orchestrator: {prov}" + (f" (fallback: {fb})" if fb else "")

    if not state:
        await update.message.reply_text(
            f"No active session.\n{provider_line}", parse_mode="Markdown"
        )
        return

    queries    = state.get("queries", 0)
    created    = state.get("created", "unknown")
    session_id = (state.get("session_id") or "none")[:8]
    domains    = ", ".join(TOPIC_MAP.values()) if TOPIC_MAP else "none (general only)"

    status = f"""*Session Status*
- ID: `{session_id}...`
- Created: {created}
- Queries: {queries}/{MAX_QUERIES}
- Domains: {domains}
- {provider_line}"""

    await update.message.reply_text(status, parse_mode="Markdown")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized.")
        return

    person_name = CONFIG.get("person", {}).get("name", "there")
    await update.message.reply_text(
        f"Hello {person_name}. I'm your second brain. Send me anything."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info(f"Starting bot for user {TELEGRAM_USER_ID}")
    log.info(f"Workspace: {WORKSPACE_ROOT}")
    log.info(f"Domains: {list(TOPIC_MAP.values()) or ['general only']}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
