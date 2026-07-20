# Loop State — Builder Guild

Last run: 2026-07-20T20:03:23Z · daily-triage · L1 report-only (manual run; first on the relocated `loops/` structure) · branch `feat/loop-engineering-v3`

Durable memory spine for Builder Guild's maintenance loops. The daily-triage loop reads and
rewrites this file each run. Humans review it; the loop never acts on code without a human
gate (see LOOP.md, loops/safety.md).

## High Priority (loop acting or waiting on human)

(none) — no red CI gate (branch + main both green), no failing invariant sweep, no calibration
regression as of this run.

## Watch List

<!-- Lower urgency; report-only. -->

- [ ] **PR #21 merge decision (human-gate)** — OPEN/MERGEABLE; CI green through the `loops/`
  restructure (run `29773277829`, smoke + graph, sha `2546e25`). Pre-merge blockers named in
  HANDOFF.md: remove/relocate HANDOFF.md; resolve the `.claude/` symlink-vs-tracked collision.
  Suggested loop action: report-only; founder decision.
- [ ] **Loop-operationalization epic open, unstarted (founder-gated)** — `builder-guild-tic` +
  9 children (scheduler, kill-switch if-guard, required PR checks, verifier invocation, run
  evidence/digest, citation-checker hardening, STATE.md hash preconditions, risk-tier
  classifier, settings-tamper alarm). Suggested loop action: none until founder go.
- [ ] **Issues #15 + #16 open** — #15 `cal2_erag.py` golden-set defaults (touches `cal*` =
  denylist), #16 missing `.key` uniqueness constraints (StatusValue/Decision). Both pre-existing,
  mapped to excluded bug beads. Suggested loop action: **human-gate**; never auto-fix.
- [ ] **loop-audit heuristic vs relocated files** — external scorers pattern-matching root-level
  `STATE.md`/`LOOP.md` may mis-score after the 2026-07-20 move (documented in loops/README.md).
  Suggested loop action: none; informational.

## Graph & Invariant Health
<!-- Source of truth = ci.yml graph job (real Neo4j). Job success ⟹ every gate's grep matched (set -e). -->
- Source: CI run `29773277829` (success · 2026-07-20T19:49Z · sha `2546e25` = branch HEAD at run
  time; PR #21 run — first green gate battery ON the relocated structure).
- Namespace isolation (node + edge): green — mutate/namespace-isolation gate (`E1_MUT_OK`).
- Bi-temporal validity (current = `invalid_at > now`): green — stamp/reconcile gates.
- Single-current + cycle sweeps: green — invariant_check + cycle_check (+ self-tests).
- Deterministic-write invariant (no LLM-authored facts): green — write-gateway gate (`WRITE_GATEWAY_OK`).

## Eval / Calibration Status (03-evals)
<!-- Denylist path — human-gate, never loop-act. Autonomy off until a role is calibrated in code. -->
- CALIBRATED roles: **none** — `01-context/src/abstain.py:26` per-namespace dict, all roles
  `False` (verified this run: 0 `True` entries). Suggest-only everywhere; grants are human-only,
  code revokes only.
- Guards present: `cal4_sweep.py`, `h2b1_calib.py` (03-evals/src). Healthy.
- No calibration regression this run.

## CI Gates
<!-- ci.yml (smoke DB-free + graph Neo4j) + cla.yml + pr-gate.yml. -->
- Branch `feat/loop-engineering-v3`: run `29773277829` **success** (smoke + graph) ·
  2026-07-20T19:49Z · sha `2546e25`; cla run `29773274550` success.
- `main`: run `29653108642` **success** · 2026-07-18T17:02Z · sha `3096310`.

## Recent Noise (ignored this run)

- Untracked `.claude/.claude` nested symlink — known collision artifact (see HANDOFF Watch);
  unchanged, not committed.
- `git add` advisory "paths ignored" on tracked `.claude/skills/loop-triage/SKILL.md` —
  advisory only; the file committed fine (see `2546e25` stat).
- Two mid-session API-stall notices — no state impact; all writes verified on disk after each.

---
Run log: see `run-log.md` | (timestamp) | findings | actions | escalations
