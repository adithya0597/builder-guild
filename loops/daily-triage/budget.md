# Loop Budget — Builder Guild

## Daily limits

| Loop | Max runs/day | Max tokens/day | Max sub-agent spawns/run |
|------|--------------|----------------|--------------------------|
| Daily Triage | 2 | 100k | 0 (L1) / 2 (L2) |

Triage is cheap by design: read CI + invariant sweep + state, classify, rewrite STATE.md.
If no high-priority items, exit immediately (early-exit < 5k tokens). Spawn sub-agents
(implementer / verifier) only when STATE.md says actionable **and** the loop is L2.

## On budget exceed

1. Pause schedulers (disable the Action / `/loop` / Conductor automation).
2. Append a `budget-exceeded` event to `run-log.md`.
3. Notify human (STATE.md High Priority).

## Kill switch

Three layers:

1. `LOOP_PAUSE_ALL` repo variable = scheduler-side graceful pause (job `if:` refuses to start).
2. `gh workflow disable loop-triage` = platform hard-off.
3. STATE.md High-Priority flag = in-band skill check (existing).

Resume only after a human clears the flag / re-enables the workflow.
