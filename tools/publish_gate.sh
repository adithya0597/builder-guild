#!/usr/bin/env bash
# Publish gate: blocks any commit of public content containing secrets or private residue.
# Generic patterns live here; add personal patterns (names, org terms) in an overlay file
# OUTSIDE the repo and pass it as $1. Any hit -> exit 1 with file:line.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PATTERNS='sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|xox[bp]-|BEGIN (RSA|OPENSSH) PRIVATE KEY|/Users/[a-z]+/'
OVERLAY="${1:-}"
fail=0
scan() {  # $1 = path; sets outer `fail` on a hit. Filenames with spaces are safe: quoted throughout.
  [ -f "$1" ] || return 0
  if out=$(grep -nE "$PATTERNS" "$1" 2>/dev/null); then echo "BLOCK $1"; echo "$out" | head -3; fail=1; fi
  if [ -n "$OVERLAY" ] && [ -f "$OVERLAY" ] && out=$(grep -nEf "$OVERLAY" "$1" 2>/dev/null); then
    echo "BLOCK(private-overlay) $1"; echo "$out" | head -3; fail=1; fi
}
# NUL-delimited so a filename containing a space/newline can't word-split out of the scan.
# Process substitution (not a pipe) keeps the loop in this shell, so `fail`/`staged` persist.
staged=0
while IFS= read -r -d '' f; do scan "$f"; staged=1; done \
  < <(git diff --cached -z --name-only --diff-filter=ACM 2>/dev/null || true)
if [ "$staged" -eq 0 ]; then
  while IFS= read -r -d '' f; do scan "$f"; done \
    < <(git ls-files -z '01-*' '02-*' '03-*' 'docs' 'README.md' 2>/dev/null || true)
fi
[ "$fail" -eq 0 ] && echo "publish gate: CLEAN" || echo "publish gate: BLOCKED"
exit $fail
