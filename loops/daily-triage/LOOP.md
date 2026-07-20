# Loop Configuration — Builder Guild

How Builder Guild is maintained with loop-engineering patterns. The repo is a graph-primary,
bi-temporal, role-scoped knowledge base; loops here are **report-only by default** and never
touch online enforcement (`01-context`) or calibration (`03-evals`) without a human gate.

## Active Loops

| Pattern | Cadence | Status | Command |
|---------|---------|--------|---------|
| Daily Triage | 1d | **L1 report-only** | `/loop 1d Run loop-triage. Update loops/daily-triage/STATE.md. No code edits.` |

Phased rollout: L1 report → L2 assisted (verifier + worktree) → L3 unattended (only after
budget + run log + safety + a real, committed run). **One report-only run logged
(2026-06-29T15:57:35Z, see run-log.md); loop dormant since — L1.**

## Human Gates (always required)

- Any change to `01-context/` online enforcement (namespace filters, the abstain/execute gate).
- Any change to `03-evals/` calibration logic or `CALIBRATED[role]` grants — code may revoke autonomy, never grant it.
- Schema / write semantics (`01-context/schema/relations.yaml`, ONTOLOGY).
- Anything on the denylist in [loops/safety.md](../safety.md).

## Worktrees

- Any unattended code-change experiment (L2+) runs in an isolated git worktree, one per attempt.
- Discard the worktree after a verifier REJECT or human escalation.

## Connectors (MCP)

- L1 report-only needs none.
- L2+: GitHub MCP read-only for CI/issue/PR discovery; scope to read + comment until trusted. No merge from a loop; no graph writes from a loop.

## Budget & Observability

- Token caps + kill switch: [budget.md](budget.md)
- Run history (append per run): [run-log.md](run-log.md)
- Kill switch: `loop-pause-all` label or a flag in STATE.md High Priority.

## Safety & Gates

- Default: **no auto-merge.** Denylist + auto-merge policy + MCP least-privilege in [loops/safety.md](../safety.md).
- Live state spine: STATE.md in this folder (`loops/daily-triage/`).

## Maturity (honest)

Operational level: **L1** — report-only, one logged run, dormant since. The artifacts here structurally enable L2;
L3 requires *real proven activity*, not file presence (see loop-engineering anti-pattern
"L3 before L1 quality"). A heuristic git-history match on words like "audit" is not a run.
