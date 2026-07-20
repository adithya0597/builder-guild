# HANDOFF — `feat/loop-engineering-v3`

> Branch working doc for picking this up in a Conductor workspace. Not intended for `main` —
> remove or relocate before merging this branch.

## Goal

Make Builder Guild legible to **loop engineering** (cobusgreyling/loop-engineering): set it up to
be maintained by recurring, stateful, verified agent loops, starting at **L1 (report-only)**. This
branch adds the loop scaffolding plus the bl-20260717 fix sweep — docs-truth reconciliation and
eval/tooling truth fixes under `03-evals`, `tools/`, `01-context/setup_a2.sh`, and `.env.example`.

## Current Progress

**Session 2026-07-16..19 (bl-20260717 + adversarial review) — the branch is now: rebase onto main
`3096310` + L1 scaffolding + an 8-commit verified fix sweep, pushed, PR #21 OPEN/MERGEABLE
(github.com/adithya0597/builder-guild/pull/21), CI green on two consecutive attempts (smoke + graph,
attempt 2 rerun deliberately).** What ran, in order: (1) deep scan — 5 lens finders + merge + codex
refuter, 25 findings, 25/25 CONFIRMED; (2) `/explore` run `loopconv-20260716a` — FULL CLOSE PASS,
5 local lanes over the 14-day conversation corpus (report: `.explore/REPORT-loopconv-20260716a.md`);
(3) `/buildloop` `bl-20260717` — 7 beads (epic `g9r`), all gates, close-check exit 0, two review-round
fix commits after 4 independent finders converged on self-invalidating git-state snapshots in the
docs-truth sweep itself; (4) devil's-advocate review of the Loops Creator Kit vs this stack —
**Kit 3.7/10, ours 4.8/10, both 2/10 operational** — full teardown + adjudication in
`audits/LOOPS_KIT_VS_BUILDER_GUILD.md` (local-only, git-excluded per founder decision 2026-07-01).

L1 loop setup committed on this branch (originally commit `8d71cf9`, 8 files, +341
lines), scoped to Builder Guild's real domain (layer boundary + invariants + calibration), grounded
in the loop-engineering repo's own templates:

- `loops/daily-triage/STATE.md` — durable loop memory (graph/invariant health, eval/calibration status, CI gates).
- `loops/daily-triage/LOOP.md` — daily-triage **L1 report-only** config: human gates, worktrees, MCP scope, budget, safety.
- `AGENTS.md` — build/verify commands, core invariants, review norms, loop operation.
- `.claude/skills/loop-triage/SKILL.md` — signal-only triage skill (rewrites `STATE.md`, never edits code).
- `.claude/agents/loop-verifier.md` — maker/checker, default **REJECT**, runs the narrowest proof.
- `loops/safety.md` — denylist (`01-context` enforcement, `03-evals` calibration), no-auto-merge, human gates, MCP least-privilege, kill switch.
- `loops/daily-triage/budget.md` + `run-log.md` — cost-observability spine. **Run log holds two honest entries (2026-06-29T15:57:35Z, 2026-07-20T20:03:23Z).**

## Status (honest)

**L1, two manual runs logged.** Report-only runs 2026-06-29T15:57:35Z and 2026-07-20T20:03:23Z (the latter = first run on the relocated `loops/` structure); no scheduled runs yet.
`loop-audit` would score this ~100/100 and may read **L3**, because its activity heuristic counts
the words "triage"/"last run" found in `STATE.md` prose — a known false positive. The run log holds
only those honest entries so the heuristic isn't laundered into an L3 claim. **It is genuinely L1.**

## What Worked

- Grounding every artifact in the loop-engineering repo's actual templates — names match what
  `loop-audit` detects (`loop-triage`, `loop-verifier`, `STATE.md`, `LOOP.md`, …).
- Branching from `main` (clean, independently mergeable) rather than from the docs branch.
- Keeping `loops/daily-triage/run-log.md` limited to real entries + the `LOOP.md` maturity note honest about L1-vs-L3.

## What Didn't Work / Avoid

- Do NOT seed `loops/daily-triage/run-log.md` with fake entries to reach L3 — that is the framework's own
  anti-pattern ("L3 before L1 quality") and defeats the purpose.
- Do NOT let the triage loop touch `01-context` enforcement or `03-evals` calibration — human-gate
  only (see `loops/safety.md`).

## Next Steps

0. **USER DECISIONS PENDING (in priority order):** (a) merge PR #21 — CI green (incl. the
   `loops/` restructure commit), review pending; (b) remove/relocate this HANDOFF.md before merge
   (its own header's rule); (c) **wiring beads CREATED 2026-07-20 (not started, founder-gated):**
   epic `builder-guild-tic` + 9 children — `phy` scheduler, `8cj` kill-switch if-guard, `ye0`
   required PR checks (+ approvals→0 + no-bypass ruleset ext.), `btj` verifier invocation (+
   verdict-as-required-check ext.), `oy7` run evidence/digest, `d0j` citation-checker hardening,
   `lbd` STATE.md hash preconditions, `hot` risk-tier classifier, `icg` settings-tamper alarm.
   Evidence spec: `.explore/REPORT-loopmature-20260720a.md` + `audits/SOLO_OPERATOR_AND_L2_SLIMMING.md`.
   Decision needed: green-light implementation order (suggest `phy` → `8cj`/`ye0` → rest).
1. ~~Run the loop again~~ **DONE 2026-07-20 (manual test run on the relocated structure — STATE.md rewritten, run-log entry 2).** Scheduled runs remain the real operational bar (bead builder-guild-phy). Manual re-run recipe:
   `/loop 1d Run loop-triage. Update loops/daily-triage/STATE.md. No code edits.` Let it rewrite the state file, then append
   one honest entry to `loops/daily-triage/run-log.md` and commit. That converts "L1 setup" into "L1 operational".
2. **Resolve the `.claude/` merge collision — BEFORE merging to `main`.** The
   `docs/reconcile-roadmap-calibration` branch gitignores `.claude` and symlinks it (Conductor
   monorepo-harness symlink, set in the gitignored `.conductor/settings.local.toml`). This branch
   commits **tracked** `.claude/skills/` + `.claude/agents/`. You cannot both symlink-over and track
   `.claude/`. Recommended: let the repo own `.claude/` — drop the `.claude` gitignore line and the
   `ln -sfn … .claude` setup line; the committed `.claude/` then travels to Conductor worktrees
   natively, and the global `~/.claude` discipline travels anyway.
3. **Merge** `feat/loop-engineering-v3` → `main` (and the docs branch → `main`) when ready. That also
   moves Builder Guild's canonical loop-audit score off the `main` floor.
4. (Optional) Remove this `HANDOFF.md` before merging to `main`.

## Open Questions

- ~~Keep the loop scaffolding at repo root, or relocate?~~ **RESOLVED 2026-07-20: relocated under `loops/`** — per-loop folder `loops/daily-triage/{LOOP,STATE,run-log,budget}.md` + shared `loops/safety.md`; skills/agents stay under `.claude/` (harness discovery).
- Once `.claude/` is repo-owned, do you still want the monorepo `~/.claude` harness in worktrees (it
  travels via the global layer anyway), or fully retire the symlink?

## Key Files Modified

This branch only; `main` and `docs/reconcile-roadmap-calibration` untouched. Added (loop scaffolding; relocated 2026-07-20 into `loops/`):
`loops/daily-triage/{LOOP.md,STATE.md,run-log.md,budget.md}`, `loops/safety.md`, `AGENTS.md`,
`.claude/skills/loop-triage/SKILL.md`, `.claude/agents/loop-verifier.md`. Modified (bl-20260717 fix
sweep): the scaffolding docs above plus `03-evals/src/{eval_corrective,eval_planner,eval_ocr,h3_instr,test_g3,golden_v1_draft}.py`,
`03-evals/golden_v1_review.md`, `tools/run_guard.py`, `01-context/setup_a2.sh`, `.env.example`.

## Branch graph (as of the bl-20260717 close; exact tip = `git rev-parse HEAD`)

- `feat/loop-engineering-v3` — this work: `main` (`3096310`) + loop scaffolding (`8d71cf9`, `d2ef3b2`, `0aff6ed`) + the bl-20260717 fix commits.
- `main` → `3096310`.
- `docs/reconcile-roadmap-calibration` → `6382779` — CLAUDE.md + Conductor setup; pushed.

## Tracker Delta (beads — live `bd list`/`bd stats` at write time, 2026-07-20)

- Session 2026-07-20: opened **11** (`nfy` explore run — closed same day; epic `tic` + 9 wiring
  children, all open/unstarted) · Current open: **23 of 143 total** (`bd stats`).
- Session 2026-07-16..17: opened **8** (`builder-guild-g9r` epic + `g9r.1`–`g9r.7`, the bl-20260717
  fix sweep) · Closed same session: **all 8** (close-check PASS, reason recorded per bead).
- Current open: **13 of 132 total** — the 3 excluded bugs (`78o`, `6mg`, `dju`), the deferred
  TrustGraph epic (`7vj` + 2 children), `pnd`, `2tn`, `11b` (FOUNDER-GATED), `9bi`, `w7y`, `6a2`,
  `kqo`. Bead text of `2tn`/`pnd`/`7vj.1` was refreshed to current serve.py line refs (g9r.7).
- Tracker lives in the gitignored `.beads/` (author-local; not visible to PR reviewers).
