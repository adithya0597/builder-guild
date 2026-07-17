# Loop State — Builder Guild

Last run: 2026-06-29T15:57:35Z · daily-triage · L1 report-only · branch `feat/loop-engineering-v3`

Durable memory spine for Builder Guild's maintenance loops. The daily-triage loop reads and
rewrites this file each run. Humans review it; the loop never acts on code without a human
gate (see LOOP.md, docs/safety.md).

## High Priority (loop acting or waiting on human)

(none) — no red CI gate, no failing invariant sweep, no calibration regression as of this run.

## Watch List

<!-- Lower urgency; report-only. -->

- [ ] **Loop branch unmerged + `.claude/` tracking collision** — `feat/loop-engineering-v3` carries the
  loop scaffolding plus the bl-20260717 fix sweep (docs-truth + eval/tooling fixes under `03-evals`,
  `tools/`, `01-context/setup_a2.sh`, `.env.example`), no open PR; HANDOFF.md flags a `.claude/`
  symlink-vs-tracked collision to resolve before merging to `main`.
  Observed artifact: untracked `.claude/.claude` nested symlink.
  Suggested loop action: report-only; **human-gate** (merge decision + `.claude/` ownership). Do not auto-resolve.
- PR #13 `docs(roadmap): reconcile gate-state numbers to CASE_STUDY` was CLOSED unmerged 2026-07-13 — no watch.

## Graph & Invariant Health
<!-- Source of truth = ci.yml graph job (real Neo4j). Job success ⟹ every gate's grep matched (set -e). -->
- Source: CI run `28139965679` (success · 2026-06-25T01:06Z · sha `61f7395` = then-`origin/main` HEAD;
  current `origin/main` is `3096310`, branch rebased onto it).
- Namespace isolation (node + edge): green — mutate/namespace-isolation gate (ci.yml:106, `E1_MUT_OK`).
- Bi-temporal validity (current = `invalid_at > now`): green — stamp/reconcile gates (ci.yml:137-140).
- Single-current + cycle sweeps: green — invariant_check + cycle_check (+ self-tests) (ci.yml:109-115).
- Deterministic-write invariant (no LLM-authored facts): green — write-gateway gate (ci.yml:56, `WRITE_GATEWAY_OK`).
- Not re-run on loop branch: the bl-20260717 fix sweep touches `03-evals`, `tools/`, and
  `01-context/setup_a2.sh` (diagnostic/doc-truth fixes, `py_compile`-verified locally) — full graph
  gates run on the PR (CI fires on `pull_request`) and must be green before merge.

## Eval / Calibration Status (03-evals)
<!-- Denylist path — human-gate, never loop-act. Autonomy off until a role is calibrated in code. -->
- CALIBRATED roles: **none** — `abstain.CALIBRATED` per-namespace dict defaults every role `False` (suggest-only).
- Guards enforce all-False: `cal4_sweep.py` (CAL4_FAIL on flip), `h2b1_calib.py` (must-not-flip). Healthy.
- Last calibration verdict: see `03-evals/CASE_STUDY_calibration.md`. No regression this run.

## CI Gates
<!-- .github/workflows/ has ci.yml + cla.yml + pr-gate.yml; ci.yml carries the per-layer graph gates: smoke (DB-free) + graph (Neo4j). -->
- Last main CI: **success** — run `28139965679` · 2026-06-25T01:06Z · sha `61f7395` (then-main; current origin/main `3096310`).
- Per-layer gates in the green run: import smoke, DB-free contract demos (evidence/pageindex), write-gateway,
  spine/mutate/deadedge, invariant + cycle sweeps (+ self-tests), sentinel guard, read-path gates
  (scope/epist/abstain/gate/stamp/reconcile), recall + retention self-tests.
- Loop branch `feat/loop-engineering-v3`: **no CI run yet** (CI fires on `push:main` + `pull_request`; no open PR).
  Branch carries eval/tooling fixes (bl-20260717) — the PR's CI run is the gate; locally only
  `py_compile` + targeted greps were run.

## Recent Noise (ignored this run)

- Untracked `.claude/.claude` nested symlink — artifact of the documented `.claude/` collision (tied to Watch
  item above; not committed — this run's commit is scoped to STATE.md + loop-run-log.md).
- Merged PRs #4–#12 — historical, all CI-green; no action.
- "Scheduled" entry in `gh run list` history — not part of ci.yml gates on this branch; not a finding.

---
Run log: see `loop-run-log.md` | (timestamp) | findings | actions | escalations
