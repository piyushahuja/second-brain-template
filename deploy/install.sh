#!/bin/bash
set -e

# Second Brain Installation Script
# Usage: ./install.sh [OPTIONS]
#
# Options:
#   --with-admin      Install admin panel dependencies (Flask)
#   --with-voice      Install voice transcription (Whisper + ffmpeg)
#   --with-syncthing  Install and configure Syncthing
#   --with-google     Set up Google OAuth (Gmail, Calendar, Drive)
#   --with-codex      Install Codex CLI (OpenAI agent, fallback orchestrator)
#   --with-gemini     Install Gemini LLM client (google-genai)
#   --with-openrouter Install OpenRouter LLM client (openai package)
#   --all             Install all optional components
#   --help            Show this help message

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(dirname "$SCRIPT_DIR")"
BOT_DIR="$WORKSPACE_ROOT/bot"
VENV_DIR="$WORKSPACE_ROOT/.venv"
LOG_DIR="$WORKSPACE_ROOT/logs"

# Parse arguments
WITH_ADMIN=false
WITH_VOICE=false
WITH_SYNCTHING=false
WITH_GOOGLE=false
WITH_CODEX=false
WITH_GEMINI=false
WITH_OPENROUTER=false

for arg in "$@"; do
    case $arg in
        --with-admin) WITH_ADMIN=true ;;
        --with-voice) WITH_VOICE=true ;;
        --with-syncthing) WITH_SYNCTHING=true ;;
        --with-google) WITH_GOOGLE=true ;;
        --with-codex) WITH_CODEX=true ;;
        --with-gemini) WITH_GEMINI=true ;;
        --with-openrouter) WITH_OPENROUTER=true ;;
        --all)
            WITH_ADMIN=true
            WITH_VOICE=true
            WITH_SYNCTHING=true
            WITH_CODEX=true
            WITH_GEMINI=true
            WITH_OPENROUTER=true
            ;;
        --help)
            head -20 "$0" | tail -15
            exit 0
            ;;
    esac
done

echo "=== Second Brain Installation ==="
echo "Workspace: $WORKSPACE_ROOT"
echo ""
echo "Options:"
echo "  Admin panel:  $WITH_ADMIN"
echo "  Voice notes:  $WITH_VOICE"
echo "  Syncthing:    $WITH_SYNCTHING"
echo "  Google OAuth: $WITH_GOOGLE"
echo ""

# --- Credentials ---

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Error: deploy/.env not found."
    echo "  cp $SCRIPT_DIR/.env.example $SCRIPT_DIR/.env"
    echo "  # Then edit .env with your credentials"
    exit 1
fi

source "$SCRIPT_DIR/.env"

if [ -z "$TELEGRAM_TOKEN" ] || [ "$TELEGRAM_TOKEN" = "your_bot_token_here" ]; then
    echo "Error: TELEGRAM_TOKEN not set in .env"
    exit 1
fi

if [ -z "$TELEGRAM_USER_ID" ] || [ "$TELEGRAM_USER_ID" = "your_telegram_user_id" ]; then
    echo "Error: TELEGRAM_USER_ID not set in .env"
    exit 1
fi

# --- Create directories ---

mkdir -p "$LOG_DIR"
mkdir -p "$WORKSPACE_ROOT/raw_sources/tracker"
mkdir -p "$WORKSPACE_ROOT/outputs/reports"

# --- Python dependencies via uv ---

echo "Installing Python dependencies..."
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

uv venv "$VENV_DIR" --quiet --allow-existing 2>/dev/null || uv venv "$VENV_DIR" --quiet
PYTHON="$VENV_DIR/bin/python3"

# Core dependencies
uv pip install --quiet --python "$PYTHON" python-telegram-bot pyyaml

# Optional: Admin panel
if [ "$WITH_ADMIN" = true ]; then
    echo "Installing admin panel dependencies..."
    uv pip install --quiet --python "$PYTHON" flask python-dotenv requests
fi

# Optional: Voice transcription
if [ "$WITH_VOICE" = true ]; then
    echo "Installing voice transcription dependencies..."
    uv pip install --quiet --python "$PYTHON" openai-whisper

    # Install ffmpeg
    if ! command -v ffmpeg &> /dev/null; then
        echo "Installing ffmpeg..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install ffmpeg
        else
            sudo apt-get update && sudo apt-get install -y ffmpeg
        fi
    fi
fi

echo "Python: $("$PYTHON" --version)"

# --- Claude CLI ---

echo ""
echo "Installing Claude CLI..."

# Ensure nvm is loaded (may already be installed from previous run)
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    source "$NVM_DIR/nvm.sh"
fi

if ! command -v node &> /dev/null; then
    echo "Node.js not found. Installing via nvm..."
    if [ ! -s "$NVM_DIR/nvm.sh" ]; then
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        # shellcheck disable=SC1091
        source "$NVM_DIR/nvm.sh"
    fi
    nvm install --lts
fi

if ! command -v claude &> /dev/null; then
    npm install -g @anthropic-ai/claude-code
fi

# Find Claude path and save to .env
CLAUDE_FULL_PATH=$(which claude 2>/dev/null)
if [ -z "$CLAUDE_FULL_PATH" ]; then
    # Try to find it in nvm directories
    CLAUDE_FULL_PATH=$(find "$HOME/.nvm/versions/node" -name "claude" -type f 2>/dev/null | head -1)
fi

if [ -n "$CLAUDE_FULL_PATH" ]; then
    echo "Claude: $($CLAUDE_FULL_PATH --version 2>/dev/null || echo 'not found')"
    echo "Claude path: $CLAUDE_FULL_PATH"

    # Add or update CLAUDE_PATH in .env
    if grep -q "^CLAUDE_PATH=" "$SCRIPT_DIR/.env" 2>/dev/null; then
        sed -i "s|^CLAUDE_PATH=.*|CLAUDE_PATH=$CLAUDE_FULL_PATH|" "$SCRIPT_DIR/.env"
    else
        echo "CLAUDE_PATH=$CLAUDE_FULL_PATH" >> "$SCRIPT_DIR/.env"
    fi
    echo "CLAUDE_PATH saved to .env"

    # Ensure claude is executable
    chmod +x "$CLAUDE_FULL_PATH"

    # Symlink to /usr/local/bin so 'claude' is in PATH for all services
    if [ ! -L /usr/local/bin/claude ] || [ "$(readlink /usr/local/bin/claude)" != "$CLAUDE_FULL_PATH" ]; then
        echo "Creating symlink: /usr/local/bin/claude -> $CLAUDE_FULL_PATH"
        if sudo ln -sf "$CLAUDE_FULL_PATH" /usr/local/bin/claude 2>/dev/null; then
            echo "Symlink created."
        else
            echo "WARNING: Could not create symlink (sudo required). Run manually:"
            echo "  sudo ln -sf $CLAUDE_FULL_PATH /usr/local/bin/claude"
        fi
    else
        echo "Symlink already exists: /usr/local/bin/claude"
    fi
else
    echo "Claude: not found"
fi

# --- Claude authentication ---

echo ""
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "ANTHROPIC_API_KEY is set in .env."
elif [ -n "$CLAUDE_FULL_PATH" ] && "$CLAUDE_FULL_PATH" -p "" --output-format json &> /dev/null; then
    echo "Claude is authenticated via ~/.claude config."
else
    echo "Claude is not authenticated."
    echo "  Option A: Add ANTHROPIC_API_KEY to .env"
    echo "  Option B: Run: claude login"
fi

# --- Optional: Codex CLI ---

if [ "$WITH_CODEX" = true ]; then
    echo ""
    echo "Installing Codex CLI..."
    if ! command -v codex &> /dev/null; then
        npm install -g @openai/codex
    fi

    CODEX_FULL_PATH=$(which codex 2>/dev/null)
    if [ -n "$CODEX_FULL_PATH" ]; then
        echo "Codex: $(codex --version 2>/dev/null || echo 'installed')"
        echo "Codex path: $CODEX_FULL_PATH"

        if grep -q "^CODEX_PATH=" "$SCRIPT_DIR/.env" 2>/dev/null; then
            sed -i "s|^CODEX_PATH=.*|CODEX_PATH=$CODEX_FULL_PATH|" "$SCRIPT_DIR/.env"
        else
            echo "CODEX_PATH=$CODEX_FULL_PATH" >> "$SCRIPT_DIR/.env"
        fi
        echo "CODEX_PATH saved to .env"
    else
        echo "Codex: not found after installation — check npm output above"
    fi

    # Codex device-auth stores OAuth tokens in the OS keyring.
    # On headless VPS there is no keyring daemon by default — install and
    # enable gnome-keyring so tokens persist across sessions.
    echo ""
    echo "Setting up keyring for Codex device-auth..."
    if ! command -v gnome-keyring-daemon &> /dev/null; then
        if command -v apt-get &> /dev/null; then
            sudo apt-get install -y gnome-keyring
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y gnome-keyring
        elif command -v brew &> /dev/null; then
            echo "macOS: keyring handled natively, no extra install needed."
        else
            echo "Warning: could not install gnome-keyring — install it manually before using Codex device-auth."
        fi
    fi

    if command -v gnome-keyring-daemon &> /dev/null; then
        # Deploy systemd user service if not already present
        SERVICE_DIR="$HOME/.config/systemd/user"
        mkdir -p "$SERVICE_DIR"
        cat > "$SERVICE_DIR/gnome-keyring.service" <<'SERVICE'
[Unit]
Description=GNOME Keyring daemon (headless)
Documentation=man:gnome-keyring-daemon(1)

[Service]
Type=simple
ExecStart=/usr/bin/gnome-keyring-daemon --foreground --unlock --components=secrets
Restart=on-failure

[Install]
WantedBy=default.target
SERVICE
        systemctl --user daemon-reload
        systemctl --user enable gnome-keyring.service
        systemctl --user start gnome-keyring.service
        echo "Keyring daemon enabled and started."
    fi

    echo ""
    echo "Next: use 'Login with ChatGPT' in the admin panel to authenticate Codex."
fi

# --- Optional: Gemini LLM client ---

if [ "$WITH_GEMINI" = true ]; then
    echo ""
    echo "Installing Gemini client..."
    uv pip install --quiet --python "$PYTHON" google-genai
    echo "Gemini client installed."
    echo "Next: add GEMINI_API_KEY to .env (get key at https://aistudio.google.com/app/apikey)"
fi

# --- Optional: OpenRouter LLM client ---

if [ "$WITH_OPENROUTER" = true ]; then
    echo ""
    echo "Installing OpenRouter client..."
    uv pip install --quiet --python "$PYTHON" openai
    echo "OpenRouter client installed."
    echo "Next: add OPENROUTER_API_KEY to .env (get key at https://openrouter.ai/keys)"
fi

# --- Optional: Syncthing ---

if [ "$WITH_SYNCTHING" = true ]; then
    echo ""
    echo "Installing Syncthing..."
    if ! command -v syncthing &> /dev/null; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install syncthing
        else
            sudo apt-get update && sudo apt-get install -y syncthing
        fi
    fi
    echo "Syncthing: $(syncthing --version 2>/dev/null | head -1 || echo 'not found')"
    if command -v syncthing &> /dev/null; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew services start syncthing 2>/dev/null || echo "Start manually: syncthing serve --no-browser"
        else
            systemctl --user enable syncthing 2>/dev/null || true
            systemctl --user start syncthing 2>/dev/null || echo "Start manually: syncthing serve --no-browser"
        fi
        echo "Syncthing web UI: http://127.0.0.1:8384"
    fi
fi

# --- Optional: Google OAuth setup ---

if [ "$WITH_GOOGLE" = true ]; then
    echo ""
    echo "Google OAuth setup:"
    echo "1. Go to https://console.cloud.google.com/apis/credentials"
    echo "2. Create OAuth 2.0 Client ID (Web application)"
    echo "3. Add redirect URI: \${VPS_BASE_URL}/oauth/google/callback"
    echo "4. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env"
    echo "5. Enable Gmail API, Calendar API, Drive API"
fi

# --- Service ---

echo ""
echo "Installing service..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: launchd
    PLIST_PATH="$HOME/Library/LaunchAgents/com.secondbrain.bot.plist"
    cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.secondbrain.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python3</string>
        <string>$BOT_DIR/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$WORKSPACE_ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/bot.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
    echo "Created: $PLIST_PATH"
    echo ""
    echo "Start:  launchctl load $PLIST_PATH"
    echo "Stop:   launchctl unload $PLIST_PATH"
    echo "Logs:   tail -f $LOG_DIR/bot.log"

else
    # Linux: systemd
    SERVICE_NAME="second-brain-bot"
    SERVICE_PATH="$HOME/.config/systemd/user/$SERVICE_NAME.service"

    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SERVICE_PATH" << EOF
[Unit]
Description=Second Brain Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$WORKSPACE_ROOT
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$VENV_DIR/bin/python3 $BOT_DIR/bot.py
Restart=always
RestartSec=10
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF
    echo "Created: $SERVICE_PATH"

    # Admin panel service (if enabled)
    if [ "$WITH_ADMIN" = true ]; then
        ADMIN_SERVICE_PATH="$HOME/.config/systemd/user/second-brain-admin.service"
        cat > "$ADMIN_SERVICE_PATH" << EOF
[Unit]
Description=Second Brain Admin Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$WORKSPACE_ROOT
EnvironmentFile=$SCRIPT_DIR/.env
ExecStart=$VENV_DIR/bin/python3 $WORKSPACE_ROOT/admin/app.py
Restart=always
RestartSec=10
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=ADMIN_TOKEN=${ADMIN_TOKEN:-}
Environment=ADMIN_PORT=${ADMIN_PORT:-8080}

[Install]
WantedBy=default.target
EOF
        echo "Created: $ADMIN_SERVICE_PATH"
    fi

    echo ""
    echo "Start bot:    systemctl --user daemon-reload && systemctl --user enable --now $SERVICE_NAME"
    echo "Status:       systemctl --user status $SERVICE_NAME"
    echo "Logs:         journalctl --user -u $SERVICE_NAME -f"

    if [ "$WITH_ADMIN" = true ]; then
        echo ""
        echo "Start admin:  systemctl --user enable --now second-brain-admin"
        echo "Admin URL:    http://localhost:${ADMIN_PORT:-8080}/admin"
    fi
fi

# --- Cron setup ---

echo ""
echo "Cron jobs:"
echo "  Jobs are defined in cron/registry.json"
echo "  To enable, set 'enabled': true and add to crontab:"
echo ""
echo "  crontab -e"
echo "  30 7 * * * cd $WORKSPACE_ROOT && ./cron/run-skill.sh /digest"
echo ""

# --- Done ---

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Fill in USER.md with user identity and targets"
echo "2. (Optional) Customize SOUL.md personality"
echo "3. Start the bot service"
echo "4. Message the bot on Telegram to test"
echo ""
echo "For topic-based routing:"
echo "1. Create a private Telegram group"
echo "2. Enable Forum Mode (Topics)"
echo "3. Create topics for each domain"
echo "4. Add topic IDs to .env"
