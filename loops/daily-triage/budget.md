# Loop Budget — Builder Guild

## Daily limits

| Loop | Max runs/day | Max tokens/day | Max sub-agent spawns/run |
|------|--------------|----------------|--------------------------|
| Daily Triage | 2 | 100k | 0 (L1) / 2 (L2) |

Triage is cheap by design: read CI + invariant sweep + state, classify, rewrite STATE.md.
If no high-priority items, exit immediately (early-exit < 5k tokens). Spawn sub-agents
(implementer / verifier) only when STATE.md says actionable **and** the loop is L2.

**How these caps are enforced when scheduled** (`.github/workflows/loop-triage.yml`):
`timeout-minutes: 15` bounds wall-clock and `--max-turns 25` bounds agent iterations —
together they cap the two runaway modes (a hung step, an infinite think-loop). Neither is a
hard **API-dollar** cap: max-turns limits conversation turns, not tokens-per-turn or tool
runtime. Set an actual spend ceiling in **Anthropic org billing**; the run-log's per-run
token estimate is observability, not a limiter.

## On budget exceed

1. Pause schedulers (disable the Action / `/loop` / Conductor automation).
2. Append a `budget-exceeded` event to `run-log.md`.
3. Notify human (STATE.md High Priority).

## Kill switch

Three layers:

1. `LOOP_PAUSE_ALL` repo variable = scheduler-side graceful pause (job `if:` refuses to start).
   **Exact semantics:** pauses only on the literal lowercase string `true`; any other value
   (unset, `TRUE`, `1`, whitespace) fails **open** and the loop runs. This is deliberate — a
   graceful pause, not the emergency stop. For a guaranteed halt use layer 2.
2. `gh workflow disable loop-triage` = platform hard-off (unconditional; GitHub stops all triggers).
3. STATE.md High-Priority flag = in-band skill check (existing).

Resume only after a human clears the flag / re-enables the workflow.
