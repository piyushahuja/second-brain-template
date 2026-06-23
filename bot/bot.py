#!/usr/bin/env python3
"""
Second Brain Telegram Bot — Generic Template

Config-driven bot that routes messages to Claude Code.
Reads domains from config.yaml for topic routing.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
SCRIPT_DIR = Path(__file__).parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
STATE_DIR = SCRIPT_DIR / "state"
STATE_FILE = STATE_DIR / "session.json"
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
SYSTEM_PROMPT_FILE = SCRIPT_DIR / "system-prompt.md"

STATE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Load configuration from config.yaml."""
    if not CONFIG_FILE.exists():
        log.warning(f"No config.yaml found at {CONFIG_FILE}, using defaults")
        return {"domains": [], "telegram": {"use_topics": False}}

    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


CONFIG = load_config()

# Build topic map from config
TOPIC_MAP: dict[int, str] = {}
DOMAIN_CONTEXT: dict[str, str] = {"general": "general queries"}

for domain in CONFIG.get("domains", []):
    name = domain.get("name", "").lower()
    topic_id = domain.get("topic_id")
    context = domain.get("context", "")

    if topic_id:
        TOPIC_MAP[int(topic_id)] = name
    if name:
        DOMAIN_CONTEXT[name] = context

log.info(f"Loaded {len(TOPIC_MAP)} domain topics: {list(TOPIC_MAP.values())}")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_USER_ID = int(os.environ.get("TELEGRAM_USER_ID", "0"))
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "claude")
MAX_QUERIES = int(os.environ.get("MAX_QUERIES", "50"))
MAX_HOURS = int(os.environ.get("MAX_HOURS", "8"))

if not TELEGRAM_TOKEN:
    log.error("TELEGRAM_TOKEN not set")
    sys.exit(1)

if not TELEGRAM_USER_ID:
    log.error("TELEGRAM_USER_ID not set")
    sys.exit(1)

CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "120"))  # seconds


# ---------------------------------------------------------------------------
# Claude CLI Validation
# ---------------------------------------------------------------------------
def check_claude_cli() -> bool:
    """Check if Claude CLI is installed and authenticated."""
    # Check if CLI exists
    try:
        result = subprocess.run(
            [CLAUDE_PATH, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.error(f"Claude CLI not found or not working: {result.stderr}")
            return False
        log.info(f"Claude CLI: {result.stdout.strip()}")
    except FileNotFoundError:
        log.error(f"Claude CLI not found at: {CLAUDE_PATH}")
        return False
    except Exception as e:
        log.error(f"Error checking Claude CLI: {e}")
        return False

    # Check if authenticated (has API key or is logged in)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        log.info("Using ANTHROPIC_API_KEY for authentication")
        return True

    # Try a minimal query to check auth
    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", "hi", "--output-format", "json", "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WORKSPACE_ROOT,
        )
        if "error" in result.stderr.lower() and "auth" in result.stderr.lower():
            log.error("Claude CLI not authenticated. Run: claude login")
            return False
        if result.returncode != 0 and "unauthorized" in result.stderr.lower():
            log.error("Claude CLI not authenticated. Run: claude login")
            return False
        return True
    except subprocess.TimeoutExpired:
        log.warning("Claude auth check timed out — assuming authenticated")
        return True
    except Exception as e:
        log.error(f"Error checking Claude auth: {e}")
        return False


CLAUDE_AUTHENTICATED = check_claude_cli()
if not CLAUDE_AUTHENTICATED:
    log.error("Claude CLI is not authenticated. Set ANTHROPIC_API_KEY or run: claude login")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Session State
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """Load session state from disk."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Failed to load state: {e}")
    return {}


def save_state(state: dict) -> None:
    """Save session state to disk."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save state: {e}")


def clear_state() -> None:
    """Clear session state."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    log.info("Session state cleared")


def should_auto_reset() -> bool:
    """Check if session should be auto-reset due to age or query count."""
    state = load_state()
    if not state:
        return False

    # Check query count
    queries = state.get("queries", 0)
    if queries >= MAX_QUERIES:
        log.info(f"Auto-reset: {queries} queries (max {MAX_QUERIES})")
        return True

    # Check session age
    created = state.get("created")
    if created:
        try:
            created_dt = datetime.fromisoformat(created)
            age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
            if age_hours >= MAX_HOURS:
                log.info(f"Auto-reset: {age_hours:.1f} hours old (max {MAX_HOURS})")
                return True
        except Exception as e:
            log.warning(f"Failed to parse created timestamp: {e}")

    return False


# ---------------------------------------------------------------------------
# Claude Code Integration
# ---------------------------------------------------------------------------
async def create_session() -> Optional[str]:
    """Create a new Claude Code session."""
    log.info("Creating new Claude session...")

    # Build system prompt
    system_prompt = f"Read CLAUDE.md, SOUL.md, and USER.md before responding. Working directory: {WORKSPACE_ROOT}"

    if SYSTEM_PROMPT_FILE.exists():
        system_prompt = SYSTEM_PROMPT_FILE.read_text().strip()

    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_PATH,
            "--print-session-id",
            "--output-format", "json",
            "--system-prompt", system_prompt,
            "-p", "Read your bootstrap files (CLAUDE.md, SOUL.md, USER.md) and confirm you're ready. Be brief.",
            cwd=WORKSPACE_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=CLAUDE_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            log.error(f"Session creation timed out after {CLAUDE_TIMEOUT}s")
            return None

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            log.error(f"Failed to create session: {error_msg}")
            return None

        # Parse session ID from output
        for line in stdout.decode().splitlines():
            try:
                data = json.loads(line)
                if data.get("type") == "system" and "session_id" in data:
                    session_id = data["session_id"]
                    save_state({
                        "session_id": session_id,
                        "created": datetime.now(timezone.utc).isoformat(),
                        "queries": 0,
                    })
                    log.info(f"Created session: {session_id}")
                    return session_id
            except json.JSONDecodeError:
                continue

        log.error("No session ID in output")
        return None

    except Exception as e:
        log.error(f"Exception creating session: {e}")
        return None


async def get_or_create_session() -> Optional[str]:
    """Get existing session or create new one."""
    if should_auto_reset():
        clear_state()
        return await create_session()

    state = load_state()
    session_id = state.get("session_id")

    if session_id:
        return session_id

    return await create_session()


async def query_claude(prompt: str, domain: str = "general") -> str:
    """Send a query to Claude Code and return the response."""
    session_id = await get_or_create_session()

    if not session_id:
        return "Failed to create Claude session. Check server logs or run `claude login` on the server."

    # Add domain context prefix
    if domain != "general" and domain in DOMAIN_CONTEXT:
        context = DOMAIN_CONTEXT[domain]
        prompt = f"[Domain: {domain} — {context}]\n\n{prompt}"

    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_PATH,
            "--resume", session_id,
            "--output-format", "stream-json",
            "-p", prompt,
            cwd=WORKSPACE_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=CLAUDE_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            log.error(f"Claude query timed out after {CLAUDE_TIMEOUT}s")
            return f"Request timed out after {CLAUDE_TIMEOUT} seconds. Try a simpler query."

        # Update query count
        state = load_state()
        state["queries"] = state.get("queries", 0) + 1
        save_state(state)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            log.error(f"Claude query failed: {error_msg}")

            # Provide user-friendly error messages
            if "auth" in error_msg.lower() or "unauthorized" in error_msg.lower():
                return "Claude CLI authentication error. Contact admin to run `claude login` on the server."
            if "session" in error_msg.lower() and "not found" in error_msg.lower():
                clear_state()
                return "Session expired. Please send your message again."

            return f"Error from Claude: {error_msg[:300]}"

        # Parse streaming JSON output
        response_parts = []
        for line in stdout.decode().splitlines():
            try:
                data = json.loads(line)
                if data.get("type") == "assistant" and "content" in data:
                    for block in data["content"]:
                        if block.get("type") == "text":
                            response_parts.append(block["text"])
            except json.JSONDecodeError:
                continue

        return "".join(response_parts) or "No response from Claude."

    except Exception as e:
        log.error(f"Exception querying Claude: {e}")
        return f"Something went wrong: {e}"


# ---------------------------------------------------------------------------
# Domain Routing
# ---------------------------------------------------------------------------
def get_domain(update: Update) -> str:
    """Extract domain from message thread (topic) ID."""
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
    """Send a reply, respecting topic threads and handling long messages."""
    thread_id = getattr(update.message, "message_thread_id", None)

    # Telegram max message length
    MAX_LEN = 4096

    if len(text) <= MAX_LEN:
        await update.message.reply_text(
            text,
            message_thread_id=thread_id,
            parse_mode="Markdown",
        )
    else:
        # Split long messages
        chunks = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            await update.message.reply_text(
                chunk,
                message_thread_id=thread_id,
                parse_mode="Markdown",
            )
            await asyncio.sleep(0.3)


def is_authorized(update: Update) -> bool:
    """Check if the user is authorized."""
    user_id = update.effective_user.id if update.effective_user else 0
    return user_id == TELEGRAM_USER_ID


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages."""
    if not is_authorized(update):
        log.warning(f"Unauthorized: {update.effective_user.id}")
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    domain = get_domain(update)

    log.info(f"Message in {domain}: {text[:50]}...")

    # Show typing indicator
    await update.message.chat.send_action("typing")

    # Query Claude
    response = await query_claude(text, domain)

    # Send response
    await send_reply(update, response)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command."""
    if not is_authorized(update):
        return

    clear_state()
    await update.message.reply_text("Session reset. Next message starts fresh.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not is_authorized(update):
        return

    state = load_state()

    if not state:
        await update.message.reply_text("No active session.")
        return

    queries = state.get("queries", 0)
    created = state.get("created", "unknown")
    session_id = state.get("session_id", "none")[:8]

    domains_list = ", ".join(TOPIC_MAP.values()) if TOPIC_MAP else "none (general only)"

    status = f"""*Session Status*
- ID: `{session_id}...`
- Created: {created}
- Queries: {queries}/{MAX_QUERIES}
- Domains: {domains_list}"""

    await update.message.reply_text(status, parse_mode="Markdown")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
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
    """Start the bot."""
    log.info(f"Starting bot for user {TELEGRAM_USER_ID}")
    log.info(f"Workspace: {WORKSPACE_ROOT}")
    log.info(f"Domains configured: {list(TOPIC_MAP.values()) or ['general only']}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("status", cmd_status))

    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
