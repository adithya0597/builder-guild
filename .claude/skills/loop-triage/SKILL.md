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
