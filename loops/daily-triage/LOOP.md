# Loop Configuration — Builder Guild

How Builder Guild is maintained with loop-engineering patterns. The repo is a graph-primary,
bi-temporal, role-scoped knowledge base; loops here are **report-only by default** and never
touch online enforcement (`01-context`) or calibration (`03-evals`) without a human gate.

## Active Loops

| Pattern | Cadence | Status | Command |
|---------|---------|--------|---------|
| Daily Triage | 1d | **L1 report-only** | `/loop 1d Run loop-triage. Update loops/daily-triage/STATE.md. No code edits.` |

Phased rollout: L1 report → L2 assisted (verifier + worktree) → L3 unattended (only after
budget + run log + safety + a real, committed run). **Two report-only runs logged
(2026-06-29T15:57:35Z, 2026-07-20T20:03:23Z — see run-log.md); scheduler workflow authored
2026-07-20 (`.github/workflows/loop-triage.yml`); cron fires only from the default branch —
inert until merged. Runs to date: manual — L1.**

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
- Kill switch (three layers): `LOOP_PAUSE_ALL` repo variable = scheduler-side graceful pause
  (job `if:` refuses to start) · `gh workflow disable loop-triage` = platform hard-off ·
  STATE.md High-Priority flag = in-band skill check.

## Safety & Gates

- Default: **no auto-merge.** Denylist + auto-merge policy + MCP least-privilege in [loops/safety.md](../safety.md).
- Live state spine: STATE.md in this folder (`loops/daily-triage/`).
- STATE.md writes are guarded: every rewrite runs `state_guard.py` hash→precheck→write→stamp (content-hash optimistic lock rejects a stale read; append-only `STATE.attrib.jsonl` attributes each write) — see the loop-triage skill's Write Protocol.

## Scheduling locality (local vs cloud)

- **Choice: cloud** (`.github/workflows/loop-triage.yml`, GitHub Actions `schedule:`). Triage reads
  CI results, the invariant sweep, eval scorecards, and issues — all repo-side. Nothing in its
  discovery set is glued to this machine.
- **Cost accepted:** a one-hour minimum interval and a clean clone per run. The cadence is daily,
  so neither binds.
- **Not local `/loop`:** that requires the machine on and a session open. A daily health triage
  that only runs when someone is already at the keyboard reports on the days least likely to need
  it.
- **Live only when the workflow sits on the default branch.** It does not today, so this loop is
  manual and the rubric reports `FAIL scheduling` — correctly.

## Stop (the boundary this loop cannot infer)

Five of the sections above map to the five moves. This one is different: it is where the operator
writes in the limit the loop has no way to derive for itself. Leave it out and the loop acts with
confidence it has not earned.

- **Never merge.** Not a PR, not a branch, not a fast-forward — at any maturity level.
- **Never delete.** No file, branch, bead, or STATE section is removed by the loop; supersede by
  appending, never by erasing.
- **Never grant autonomy.** Code may revoke a `CALIBRATED[role]` grant; it may never issue one.
- **Never write outside** `loops/daily-triage/STATE.md` and `run-log.md` at L1.
- **When confidence is below certain, escalate rather than act** — an item the loop is unsure about
  goes to the STATE High-Priority section for a human, not into a change.

## Sample read (comprehension-rot guard)

Verification debt has an evaluator behind it and token blowout has a cap; comprehension rot is the
cost with no natural alarm — the codebase grows while the operator's map of it stalls, and nothing
signals the gap until a bug surfaces in a corner never read.

- Each run, the operator reads **one** representative item from STATE.md and writes a one-line
  explanation of what changed and why it changed that way, into the run-log entry's `sample_read`
  field.
- An inability to explain a sampled change is the signal — it means the map is behind, and that is
  cheaper to learn here than from a production incident.
- A filled `sample_read` is a precondition for any L1 → L2 promotion review.

## Maturity (honest)

Operational level: **L1** — report-only, two logged manual runs; scheduler workflow authored
2026-07-20 (`.github/workflows/loop-triage.yml`); cron fires only from the default branch —
inert until merged. Runs to date: manual. The artifacts here structurally enable L2;
L3 requires *real proven activity*, not file presence (see loop-engineering anti-pattern
"L3 before L1 quality"). A heuristic git-history match on words like "audit" is not a run.
