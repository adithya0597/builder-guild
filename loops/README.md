# loops/ — all loop scaffolding, one folder per loop

Every maintenance loop in this repo lives here, one subfolder per loop — the same shape as
`.claude/skills/<name>/`. Nothing loop-related sits scattered at the repo root.

```
loops/
  README.md            ← this file
  safety.md            ← SHARED safety contract: denylist, no-auto-merge, human gates, kill switch
  daily-triage/        ← one folder per loop
    LOOP.md            ← loop config: cadence, maturity level, gates, connectors
    STATE.md           ← durable state the loop reads + rewrites each run
    run-log.md         ← append-only run history (one honest entry per real run)
    budget.md          ← caps (runs/day, tokens/day) + on-exceed protocol
  pre-ship-adversarial-review/ ← manually-invoked L1 reviewer-gap detector (report-only)
    LOOP.md / STATE.md / run-log.md / budget.md ← same per-loop contract
```

## The per-loop contract

A loop is these four files. Adding a loop = `mkdir loops/<name>/` + the four files
(copy `daily-triage/` as the template), then registering its trigger:

1. `LOOP.md` — what it does, cadence, maturity (L1 report-only → L2 assisted → L3 unattended),
   human gates, MCP scopes.
2. `STATE.md` — the state spine it rewrites. Control fields are getting content-hash
   preconditions + attributed writes (bead `builder-guild-lbd`) — Markdown content,
   deterministic harness enforcement.
3. `run-log.md` — append-only evidence. A loop with no run-log entries is configured, not
   operational. Entries are written per run (workflow-authored once bead `builder-guild-oy7` lands).
4. `budget.md` — caps the loop cannot exceed; enforcement moves into workflow config
   (`timeout-minutes`, max-turns) with bead `builder-guild-phy`.

Shared across all loops: `safety.md` (denylist paths, no-auto-merge, always-on human-gate
triggers, the `loop-pause-all` kill switch).

## What deliberately does NOT live here

- `.claude/skills/loop-triage/`, `.claude/agents/loop-verifier.md` — harness-discovered;
  Claude Code only finds skills/agents under `.claude/`.
- `AGENTS.md` — repo-root convention, read by any agent harness.
- Schedulers — `.github/workflows/` (beads `builder-guild-phy`/`8cj` wire cron + kill-switch there).
- Run ledgers of the meta-loops (`.buildloop/`, `.explore/`) — author-local, git-ignored.

## Note on loop-audit heuristics

External loop-audit tooling that pattern-matches root-level `STATE.md`/`LOOP.md` may score this
repo lower after the 2026-07-20 relocation. That heuristic was already documented as a false-positive
machine (it read one manual run as L3 activity); the run-log, not file placement, is the honest
maturity signal.
