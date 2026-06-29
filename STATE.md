# Loop State — Builder Guild

Last run: — (no automated run yet; L1 setup committed on feat/loop-engineering)

Durable memory spine for Builder Guild's maintenance loops. The daily-triage loop reads and
rewrites this file each run. Humans review it; the loop never acts on code without a human
gate (see LOOP.md, docs/safety.md).

## High Priority (loop acting or waiting on human)

<!--
- [ ] ID — one-line description
  Loop action: what the loop did last
  Human decision: (if any)
-->

(none yet)

## Watch List

<!-- Monitor, do not act yet -->

(none yet)

## Graph & Invariant Health
<!-- From 01-context invariant sweeps. -->
- Namespace isolation (node + edge): —
- Bi-temporal validity (current = `invalid_at > now`): —
- Deterministic-write invariant (no LLM-authored facts): —

## Eval / Calibration Status (03-evals)
<!-- Autonomy stays off until a role is calibrated in code. -->
- CALIBRATED roles: none (suggest-only)
- Last calibration verdict: see `03-evals/CASE_STUDY_calibration.md`

## CI Gates
<!-- ci.yml + invariant sweep + recall selftest + abstain contract. -->
- Last CI status: —

## Recent Noise (ignored this run)

<!-- Brief list — helps tune the triage skill -->

---
Run log: see `loop-run-log.md` | (timestamp) | findings | actions | escalations
