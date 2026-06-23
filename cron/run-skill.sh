#!/bin/bash
# Generic skill runner for cron jobs
# Usage: ./run-skill.sh /digest
# Usage: ./run-skill.sh "/weekly fitness"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$WORKSPACE_ROOT/deploy"

# Load config
if [ -f "$DEPLOY_DIR/.env" ]; then
    source "$DEPLOY_DIR/.env"
fi

CLAUDE_PATH="${CLAUDE_PATH:-claude}"
LOG_FILE="/tmp/second-brain-cron.log"
SKILL="${1:-/digest}"

echo "[$(date)] Running skill: $SKILL" >> "$LOG_FILE"

cd "$WORKSPACE_ROOT"
$CLAUDE_PATH -p "$SKILL" \
    --output-format json \
    --dangerously-skip-permissions \
    2>> "$LOG_FILE" | jq -r '.result // .error // "No output"' >> "$LOG_FILE"

echo "[$(date)] Skill complete: $SKILL" >> "$LOG_FILE"
