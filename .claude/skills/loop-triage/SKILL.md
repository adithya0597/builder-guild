---
name: loop-triage
description: >
  Triage Builder Guild's CI gates, invariant sweeps, eval/calibration status, and open issues
  into a concise, prioritized findings report. Signal only — writes STATE.md, never edits code.
user_invocable: true
---

# Loop Triage — Builder Guild

You produce a clean, prioritized list of things a maintenance loop should consider. You are
**signal, not action**: you read, classify, and rewrite STATE.md. You never edit code, never
write the graph, never modify `01-context` enforcement or `03-evals` calibration.

## MANDATORY Pre-Run Checks (before any triage work)

1. **Kill switch — abort on set.** Check for `loop-pause-all`: a GitHub label on the repo
   OR a flag line in `STATE.md` High-Priority. If set → ABORT immediately (no triage, no
   STATE.md rewrite) and append a schema-consistent JSON entry to `loop-run-log.md` (same fields as the format block; `"outcome": "no-op"` plus `"reason": "loop-pause-all"`).
2. **Budget caps — early-exit when over cap** (caps from `loop-budget.md`): max **2 runs/day**
   and max **100k tokens/day**. Count today's entries in `loop-run-log.md`; if either cap is
   already hit → EARLY-EXIT and log a schema-consistent JSON entry (`"outcome": "no-op"`, `"reason": "budget-exceeded"`) per the
   `loop-budget.md` on-exceed protocol.
3. **Run log — MANDATORY append.** After EVERY run — completed, aborted, or early-exited —
   append an entry to `loop-run-log.md`: date, outcome, approx tokens. No silent runs.

## Inputs (the loop provides these)
- CI status (`ci.yml` + per-layer gates: invariant sweep, recall selftest, abstain contract) — last 24h
- Open issues / PRs (read-only)
- Recent commits on the working branch (last 24–48h)
- Invariant-sweep output: namespace isolation, bi-temporal validity, no-LLM-writes
- Calibration status (`03-evals`): are any roles `CALIBRATED`? did the last run refuse / grant?
- The current `STATE.md` (what the loop already knows)

## Output (rewrite STATE.md sections)

### High-Priority (act-worthy today)
- One-line description · why it matters (risk/impact) · suggested loop action · rough effort.
- Qualifies: a failing invariant sweep (namespace leak, temporal violation), a red CI gate, a calibration regression.

### Watch
- Lower urgency, same format.

### Graph & Invariant Health / Eval Status / CI Gates
- Refresh the standing sections with current values.

### Noise / Ignore
- Brief list of what was looked at and dismissed (tunes this skill).

## Rules
- Brutally concise; structured markdown, one-line items, explicit `Suggested loop action`.
- High-Priority only if a reasonable engineer wants to know today.
- When in doubt → Watch or Noise, not new work.
- Never propose architectural overhauls or schema changes during triage.
- Treat anything touching `01-context` enforcement, `03-evals` calibration, or denylist paths as **human-gate** — flag, never act.
- Honor the invariants in `AGENTS.md` and the denylist in `docs/safety.md`.

## Gotchas
- 2026-07-17: pre-run checks added because the kill switch and budget caps were previously
  declared (LOOP.md:38, loop-budget.md:21, docs/safety.md:64) but checked nowhere in the
  actual run path (loopcoherence-1, -3). Declaration without a check point = no enforcement.
