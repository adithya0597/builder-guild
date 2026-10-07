#!/bin/bash
# Smart skill extraction trigger — fires on Stop hook only.
# Replaces Claudeception's blunt UserPromptSubmit approach.
# Only activates when session involved debugging, discovery, or non-trivial workarounds.
# Token cost: ~50 tokens (classification injection) vs ~200 tokens every prompt.
# Ported from ai-harness 2026-05-11.

input=$(cat)

# Don't trigger if stop hook is already active (prevent loops)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false')
if [[ "$stop_hook_active" == "true" ]]; then
  exit 0
fi

transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')

if [[ -z "$transcript_path" || ! -f "$transcript_path" ]]; then
  exit 0
fi

# Quick heuristic: did this session involve error resolution or discovery?
# Check for error/debugging patterns in assistant messages
error_signals=$(jq -s '
  [.[] | select(.type == "assistant") |
   select(.message.content | tostring |
   test("error|fix|bug|workaround|gotcha|tricky|undocumented|unexpected|the issue was|root cause|turns out"; "i"))] |
  length
' < "$transcript_path" 2>/dev/null || echo "0")

# Check for multiple tool retries (sign of debugging)
retry_signals=$(jq -s '
  [.[] | select(.type == "assistant") |
   select(.message.content | tostring |
   test("retry|try again|different approach|that didn.t work|let me try|actually.*instead"; "i"))] |
  length
' < "$transcript_path" 2>/dev/null || echo "0")

# Check for configuration struggles
config_signals=$(jq -s '
  [.[] | select(.type == "assistant") |
   select(.message.content | tostring |
   test("config|setting|environment variable|permission|not documented|had to"; "i"))] |
  length
' < "$transcript_path" 2>/dev/null || echo "0")

total_signals=$((error_signals + retry_signals + config_signals))

# Threshold: at least 2 signals to avoid false positives on routine work
if [[ $total_signals -ge 2 ]]; then
  cat << 'EXTRACTION_MSG'
{"systemMessage": "SKILL EXTRACTION OPPORTUNITY: This session contained debugging, discovery, or configuration work (detected signals: error resolution, retries, or config struggles). Before ending, evaluate whether any non-obvious solutions were found. If so, extract them as reusable skills by running the skill extraction pipeline. If all solutions were routine, note 'no extractable knowledge' and proceed."}
EXTRACTION_MSG
fi
