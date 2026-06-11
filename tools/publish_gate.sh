#!/usr/bin/env bash
# Publish gate: blocks any commit of public content containing secrets or private residue.
# Generic patterns live here; add personal patterns (names, org terms) in an overlay file
# OUTSIDE the repo and pass it as $1. Any hit -> exit 1 with file:line.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PATTERNS='sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|xox[bp]-|BEGIN (RSA|OPENSSH) PRIVATE KEY|/Users/[a-z]+/'
OVERLAY="${1:-}"
FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
[ -z "$FILES" ] && FILES=$(git ls-files '01-*' '02-*' '03-*' 'docs' 'README.md' 2>/dev/null)
fail=0
for f in $FILES; do
  [ -f "$f" ] || continue
  if out=$(grep -nE "$PATTERNS" "$f" 2>/dev/null); then echo "BLOCK $f"; echo "$out" | head -3; fail=1; fi
  if [ -n "$OVERLAY" ] && [ -f "$OVERLAY" ] && out=$(grep -nEf "$OVERLAY" "$f" 2>/dev/null); then
    echo "BLOCK(private-overlay) $f"; echo "$out" | head -3; fail=1; fi
done
[ "$fail" -eq 0 ] && echo "publish gate: CLEAN" || echo "publish gate: BLOCKED"
exit $fail
