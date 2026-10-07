#!/usr/bin/env bash
# PreCompact hook: create handoff before auto-compaction, block after 3 compactions.
# Ported from ai-harness 2026-05-11.

set -euo pipefail

# Read the hook input
INPUT=$(cat)
MATCHER=$(echo "$INPUT" | jq -r '.matcher // "auto"' 2>/dev/null || echo "auto")

# Only count auto-compactions (manual /compact is always allowed)
if [ "$MATCHER" != "auto" ]; then
  exit 0
fi

# Track compaction count per session — try hook input first, then env var
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
SESSION_ID="${SESSION_ID:-${CLAUDE_SESSION_ID:-unknown}}"
COUNT_FILE="/tmp/claude-compact-count-${SESSION_ID}"

# Read current count
COUNT=0
if [ -f "$COUNT_FILE" ]; then
  COUNT=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
fi

# Increment
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNT_FILE"

# After 3 auto-compactions, block and suggest clearing
if [ "$COUNT" -gt 3 ]; then
  cat <<EOF
{
  "continue": false,
  "stopReason": "Auto-compact blocked after 3 compactions this session. Context is heavily compressed — run /clear to start fresh, or /half-clone to keep recent work. Use /compact manually if you really need to continue."
}
EOF
  exit 0
fi

# Otherwise, inject a system message reminding to create handoff
cat <<EOF
{
  "systemMessage": "Auto-compact #${COUNT}/3 triggered. IMPORTANT: Before this compaction completes, create or update HANDOFF.md with current progress, decisions made, and next steps. This is compaction ${COUNT} of 3 — after 3, auto-compact will be blocked and you'll need to /clear."
}
EOF
