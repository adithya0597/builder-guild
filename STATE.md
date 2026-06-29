# Loop State — Builder Guild

Last run: 2026-06-29T15:57:35Z · daily-triage · L1 report-only · branch `feat/loop-engineering-v1`

Durable memory spine for Builder Guild's maintenance loops. The daily-triage loop reads and
rewrites this file each run. Humans review it; the loop never acts on code without a human
gate (see LOOP.md, docs/safety.md).

## High Priority (loop acting or waiting on human)

(none) — no red CI gate, no failing invariant sweep, no calibration regression as of this run.

## Watch List

<!-- Lower urgency; report-only. -->

- [ ] **Loop branch unmerged + `.claude/` tracking collision** — `feat/loop-engineering-v1` is 2 commits
  ahead of `origin/main` (docs-only, +428 lines / 9 files), no open PR; HANDOFF.md flags a `.claude/`
  symlink-vs-tracked collision to resolve before merging to `main`. Observed artifact: untracked
  `.claude/.claude` nested symlink.
  Suggested loop action: report-only; **human-gate** (merge decision + `.claude/` ownership). Do not auto-resolve.
- [ ] **Open PR #13** `docs(roadmap): reconcile gate-state numbers to CASE_STUDY` — different branch,
  CI green 6/6, awaiting human merge.
  Suggested loop action: none; **human-merge**. Read-only watch.

## Graph & Invariant Health
<!-- Source of truth = ci.yml graph job (real Neo4j). Job success ⟹ every gate's grep matched (set -e). -->
- Source: CI run `28139965679` (success · 2026-06-25T01:06Z · sha `61f7395` = current `origin/main` HEAD).
- Namespace isolation (node + edge): green — mutate/namespace-isolation gate (ci.yml:89, `E1_MUT_OK`).
- Bi-temporal validity (current = `invalid_at > now`): green — stamp/reconcile gates (ci.yml:115-118).
- Single-current + cycle sweeps: green — invariant_check + cycle_check (+ self-tests) (ci.yml:93-100).
- Deterministic-write invariant (no LLM-authored facts): green — write-gateway gate (ci.yml:52, `WRITE_GATEWAY_OK`).
- Not re-run on loop branch: loop delta is docs/scaffolding only (0 files under `01-context`/`02-agents`/`03-evals`).

## Eval / Calibration Status (03-evals)
<!-- Denylist path — human-gate, never loop-act. Autonomy off until a role is calibrated in code. -->
- CALIBRATED roles: **none** — `abstain.CALIBRATED` per-namespace dict defaults every role `False` (suggest-only).
- Guards enforce all-False: `cal4_sweep.py` (CAL4_FAIL on flip), `h2b1_calib.py` (must-not-flip). Healthy.
- Last calibration verdict: see `03-evals/CASE_STUDY_calibration.md`. No regression this run.

## CI Gates
<!-- ci.yml = only gate workflow on this branch: smoke (DB-free) + graph (Neo4j). -->
- Last main CI: **success** — run `28139965679` · 2026-06-25T01:06Z · sha `61f7395`.
- Per-layer gates in the green run: import smoke, DB-free contract demos (evidence/pageindex), write-gateway,
  spine/mutate/deadedge, invariant + cycle sweeps (+ self-tests), sentinel guard, read-path gates
  (scope/epist/abstain/gate/stamp/reconcile), recall + retention self-tests.
- Loop branch `feat/loop-engineering-v1`: **no CI run** (CI fires on `push:main` + `pull_request`; no open PR).
  Acceptable — docs-only delta, no product code.

## Recent Noise (ignored this run)

- Untracked `.claude/.claude` nested symlink — artifact of the documented `.claude/` collision (tied to Watch
  item above; not committed — this run's commit is scoped to STATE.md + loop-run-log.md).
- Merged PRs #4–#12 — historical, all CI-green; no action.
- "Scheduled" entry in `gh run list` history — not part of ci.yml gates on this branch; not a finding.

---
Run log: see `loop-run-log.md` | (timestamp) | findings | actions | escalations
