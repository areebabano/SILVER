#!/usr/bin/env bash
# CEO Briefing — Cron Wrapper Script (Silver Tier Capstone)
# Schedule: 0 23 * * 0 (Sunday at 11 PM)
#
# Crontab entry:
#   0 23 * * 0 /path/to/AI_Employee_Vault/scripts/ceo_briefing.sh >> /path/to/AI_Employee_Vault/Logs/cron-briefing.log 2>&1

VAULT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$VAULT_DIR/Logs/cron-briefing.log"

echo "=== CEO Briefing Run: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOG_FILE"

cd "$VAULT_DIR" || exit 1

# Invoke Claude Code with the ceo-briefing skill
claude -p "Run the ceo-briefing skill for this week. Read Business_Goals.md, scan /Done/ for completed tasks and /Logs/ for activity data. Generate the weekly CEO briefing and save it to /Briefings/$(date '+%Y-%m-%d')_Monday_Briefing.md" >> "$LOG_FILE" 2>&1

echo "=== Completed: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >> "$LOG_FILE"
