#!/bin/bash
set -e

# bootstrap.sh — one-time setup for Second Brain on a fresh machine
#
# Usage:
#   bash bootstrap.sh
#   bash bootstrap.sh --repo git@github.com:you/client-brain.git
#   bash bootstrap.sh --repo <url> --dir ~/second-brain --all
#
# All flags after --repo/--dir are forwarded to deploy/install.sh
# If no install flags are provided, bootstrap defaults to the recommended
# client stack: admin panel, Syncthing, and optional LLM fallback clients.

REPO_URL=""
INSTALL_DIR="$HOME/second-brain"
INSTALL_FLAGS=()

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO_URL="$2"; shift 2 ;;
        --dir)  INSTALL_DIR="$2"; shift 2 ;;
        *)      INSTALL_FLAGS+=("$1"); shift ;;
    esac
done

# ─── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       Second Brain — Bootstrap           ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Before continuing, you need:"
echo ""
echo "  1. A Telegram bot token"
echo "     → Message @BotFather on Telegram → /newbot"
echo ""
echo "  2. Your Telegram user ID"
echo "     → Message @userinfobot on Telegram"
echo ""
echo "  3. An Anthropic API key  (OR run 'claude login' after install)"
echo "     → https://console.anthropic.com/settings/keys"
echo ""
read -rp "Ready? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi
echo ""

if [ ${#INSTALL_FLAGS[@]} -eq 0 ]; then
    read -rp "Install admin panel, Syncthing, and LLM fallbacks? [Y/n] " full_stack
    if [[ "$full_stack" != "n" && "$full_stack" != "N" ]]; then
        INSTALL_FLAGS=(--with-admin --with-syncthing --with-codex --with-gemini --with-openrouter)
        echo "Using recommended install flags: ${INSTALL_FLAGS[*]}"
    else
        echo "Using minimal install. You can add optional components later with deploy/install.sh."
    fi
    echo ""
fi

# ─── Collect required values ───────────────────────────────────────────────────

if [ -z "$REPO_URL" ]; then
    read -rp "Repo URL to clone (git@github.com:you/client-brain.git): " REPO_URL
    if [ -z "$REPO_URL" ]; then
        echo "Error: repo URL is required."
        exit 1
    fi
fi

read -rp "Install directory [$INSTALL_DIR]: " input
INSTALL_DIR="${input:-$INSTALL_DIR}"

echo ""
echo "--- Credentials ---"
echo ""

read -rp "Telegram bot token: " TELEGRAM_TOKEN
if [ -z "$TELEGRAM_TOKEN" ]; then
    echo "Error: TELEGRAM_TOKEN is required."
    exit 1
fi

read -rp "Your Telegram user ID: " TELEGRAM_USER_ID
if [ -z "$TELEGRAM_USER_ID" ]; then
    echo "Error: TELEGRAM_USER_ID is required."
    exit 1
fi

read -rp "Anthropic API key (leave blank to use 'claude login' after install): " ANTHROPIC_API_KEY
echo ""

# ─── Clone repo ────────────────────────────────────────────────────────────────

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Repo already exists at $INSTALL_DIR — skipping clone."
else
    echo "Cloning $REPO_URL → $INSTALL_DIR ..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ─── Write .env ────────────────────────────────────────────────────────────────

ENV_FILE="$INSTALL_DIR/deploy/.env"

if [ -f "$ENV_FILE" ]; then
    read -rp "deploy/.env already exists. Overwrite? [y/N] " ow
    if [[ "$ow" != "y" && "$ow" != "Y" ]]; then
        echo "Keeping existing .env."
    else
        cp "$ENV_FILE" "$ENV_FILE.bak"
        echo "Backed up to deploy/.env.bak"
        WRITE_ENV=true
    fi
else
    WRITE_ENV=true
fi

if [ "${WRITE_ENV:-false}" = true ]; then
    cp "$INSTALL_DIR/deploy/.env.example" "$ENV_FILE"

    # Inject required values
    sed -i "s|^TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=$TELEGRAM_TOKEN|" "$ENV_FILE"
    sed -i "s|^TELEGRAM_USER_ID=.*|TELEGRAM_USER_ID=$TELEGRAM_USER_ID|" "$ENV_FILE"
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY|" "$ENV_FILE"
    fi

    echo "Written: deploy/.env"
fi

# ─── Run install ────────────────────────────────────────────────────────────────

echo ""
echo "--- Running install ---"
echo ""

bash "$INSTALL_DIR/deploy/install.sh" "${INSTALL_FLAGS[@]}"

# ─── Start service ─────────────────────────────────────────────────────────────

echo ""
echo "--- Starting service ---"
echo ""

if [[ "$OSTYPE" == "darwin"* ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.secondbrain.bot.plist"
    if [ -f "$PLIST" ]; then
        launchctl load "$PLIST" 2>/dev/null && echo "Bot started (launchd)." || echo "Warning: launchctl failed — start manually."
    fi
else
    systemctl --user daemon-reload
    if systemctl --user enable --now second-brain-bot 2>/dev/null; then
        echo "Bot started (systemd)."
        systemctl --user status second-brain-bot --no-pager -l || true
    else
        echo "Warning: systemctl failed — start manually:"
        echo "  systemctl --user enable --now second-brain-bot"
    fi

    if printf '%s\n' "${INSTALL_FLAGS[@]}" | grep -Eq '^--(all|with-admin)$'; then
        if systemctl --user enable --now second-brain-admin 2>/dev/null; then
            echo "Admin panel started (systemd)."
        else
            echo "Warning: admin service was installed but not started:"
            echo "  systemctl --user enable --now second-brain-admin"
        fi
    fi
fi

# ─── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           Setup Complete                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo ""

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "  ! Authenticate Claude:"
    echo "    claude login"
    echo ""
fi

echo "  1. Fill in USER.md with client identity and domains:"
echo "     $INSTALL_DIR/USER.md"
echo ""
echo "  2. (Optional) Customize personality:"
echo "     $INSTALL_DIR/SOUL.md"
echo ""
echo "  3. Message the bot on Telegram to test it."
echo ""
if printf '%s\n' "${INSTALL_FLAGS[@]}" | grep -Eq '^--(all|with-admin)$'; then
    echo "  4. Open the admin panel:"
    echo "     http://localhost:${ADMIN_PORT:-8080}/admin"
    echo ""
    echo "  5. To sync a client folder:"
    echo "     - Admin → Infrastructure → copy Server Device ID"
    echo "     - On the client device, install Syncthing and add this server as a remote device"
    echo "     - Share any local folder with the server"
    echo "     - Back in Admin → Infrastructure, accept it under raw_sources/<source-name>"
    echo "     - Optional: click Outputs to Client to share outputs/shared back"
    echo ""
    next_step=6
else
    next_step=4
fi

echo "  $next_step. For domain routing (Telegram topics):"
echo "     - Create a private group → enable Forum Mode → create topics"
echo "     - Add GROUP_CHAT_ID and TOPIC_* to deploy/.env"
echo "     - Restart: systemctl --user restart second-brain-bot"
echo ""
echo "Logs:   journalctl --user -u second-brain-bot -f"
if printf '%s\n' "${INSTALL_FLAGS[@]}" | grep -Eq '^--(all|with-admin)$'; then
    echo "Admin:  journalctl --user -u second-brain-admin -f"
fi
echo "Config: $INSTALL_DIR/deploy/.env"
echo ""
