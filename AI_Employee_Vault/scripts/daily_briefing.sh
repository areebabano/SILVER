#!/usr/bin/env bash
# Daily Briefing — Cron Wrapper Script (Silver Tier)
# Schedule: 0 8 * * 1-5 (Weekdays at 8 AM)
#
# Crontab entry:
#   0 8 * * 1-5 /path/to/AI_Employee_Vault/scripts/daily_briefing.sh >> /path/to/AI_Employee_Vault/Logs/cron-daily.log 2>&1

VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$VAULT_DIR/Skills/Daily_Briefing/daily_briefing.py"
LOG_FILE="$VAULT_DIR/Logs/cron-daily.log"

echo "=== Daily Briefing Run: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOG_FILE"

cd "$VAULT_DIR" || exit 1

if [ -f "$SCRIPT" ]; then
    python "$SCRIPT" >> "$LOG_FILE" 2>&1
    echo "=== Completed: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOG_FILE"
else
    echo "ERROR: Script not found: $SCRIPT" >> "$LOG_FILE"
    exit 1
fi
