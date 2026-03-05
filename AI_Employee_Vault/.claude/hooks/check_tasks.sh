#!/usr/bin/env bash
# Stop Hook — Check if tasks remain in /Needs_Action/
# If tasks remain and iterations < MAX, exit 2 (continue processing)
# Otherwise exit 0 (stop)
#
# Used by Claude Code Stop Hook to persist through multi-step workflows.

VAULT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NEEDS_ACTION="$VAULT_DIR/Needs_Action"
ITERATION_FILE="$VAULT_DIR/.claude/.iteration_count"
MAX_ITERATIONS=${MAX_ITERATIONS:-5}

# Read current iteration count
if [ -f "$ITERATION_FILE" ]; then
    ITERATIONS=$(cat "$ITERATION_FILE")
else
    ITERATIONS=0
fi

# Increment iteration
ITERATIONS=$((ITERATIONS + 1))
echo "$ITERATIONS" > "$ITERATION_FILE"

# Safety guard: stop after MAX_ITERATIONS
if [ "$ITERATIONS" -ge "$MAX_ITERATIONS" ]; then
    echo "[STOP HOOK] Max iterations ($MAX_ITERATIONS) reached. Stopping."
    rm -f "$ITERATION_FILE"
    exit 0
fi

# Check if there are .md files in Needs_Action (excluding .gitkeep)
TASK_COUNT=$(find "$NEEDS_ACTION" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l)

if [ "$TASK_COUNT" -gt 0 ]; then
    echo "[STOP HOOK] $TASK_COUNT task(s) remaining in Needs_Action. Continuing (iteration $ITERATIONS/$MAX_ITERATIONS)."
    exit 2  # Exit code 2 = continue processing
else
    echo "[STOP HOOK] No tasks remaining. Stopping."
    rm -f "$ITERATION_FILE"
    exit 0  # Exit code 0 = stop
fi
