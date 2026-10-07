# loop-miner — L1 triage stub

## MANDATORY pre-run checks
- Check for the kill switch in the STATE.md High-Priority section; abort if present.
- Enforce budget caps from budget.md, counted against run-log.md.

## Inputs
Repo state relevant to the loop.

## Output
- Rewrite STATE.md sections.
- Append one run-log entry to run-log.md.

## Rules
- Operate in L1 report-only mode.
- Write only these allowed paths:
- loops/loop-miner/STATE.md
- loops/loop-miner/run-log.md
- Done condition:
```
grep -q "\"run_id\": \"$(date -u +%Y-%m-%d)" loops/loop-miner/run-log.md
```

## Gotchas
