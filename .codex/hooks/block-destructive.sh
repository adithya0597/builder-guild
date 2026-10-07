#!/bin/bash

# PreToolUse hook for Bash: blocks destructive operations.
# Ported from ai-harness 2026-05-11.

input=$(cat)

command=$(echo "$input" | jq -r '.tool_input.command // empty')

if [[ -z "$command" ]]; then
    exit 0
fi

if echo "$command" | grep -qE '^\s*rm\s+-rf\s+/\s*$' || \
   echo "$command" | grep -qE '^\s*rm\s+-rf\s+/\*'; then
    echo '{"decision": "block", "reason": "Blocked: rm -rf / is never safe to run."}'
    exit 0
fi

if echo "$command" | grep -qE 'git\s+push\s+.*--force.*\s+(main|master)' || \
   echo "$command" | grep -qE 'git\s+push\s+.*-f\s+.*(main|master)' || \
   echo "$command" | grep -qE 'git\s+push\s+--force\s+(main|master)' || \
   echo "$command" | grep -qE 'git\s+push\s+-f\s+(main|master)'; then
    echo '{"decision": "block", "reason": "Blocked: force push to main/master is not allowed."}'
    exit 0
fi

if echo "$command" | grep -qiE '(DROP\s+TABLE|DROP\s+DATABASE)'; then
    echo '{"decision": "block", "reason": "Blocked: DROP TABLE/DATABASE detected."}'
    exit 0
fi

if echo "$command" | grep -qiE 'TRUNCATE\s+TABLE'; then
    echo '{"decision": "block", "reason": "Blocked: TRUNCATE TABLE detected."}'
    exit 0
fi

exit 0
