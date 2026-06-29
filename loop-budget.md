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
2. Append a `budget-exceeded` event to `loop-run-log.md`.
3. Notify human (STATE.md High Priority).

## Kill switch

- Label / flag: `loop-pause-all` (or a flag in STATE.md High Priority).
- Resume only after a human clears the flag.
