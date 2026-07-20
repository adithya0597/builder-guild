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

- `STATE.md` — durable loop memory (graph/invariant health, eval/calibration status, CI gates).
- `LOOP.md` — daily-triage **L1 report-only** config: human gates, worktrees, MCP scope, budget, safety.
- `AGENTS.md` — build/verify commands, core invariants, review norms, loop operation.
- `.claude/skills/loop-triage/SKILL.md` — signal-only triage skill (rewrites `STATE.md`, never edits code).
- `.claude/agents/loop-verifier.md` — maker/checker, default **REJECT**, runs the narrowest proof.
- `docs/safety.md` — denylist (`01-context` enforcement, `03-evals` calibration), no-auto-merge, human gates, MCP least-privilege, kill switch.
- `loop-budget.md` + `loop-run-log.md` — cost-observability spine. **Run log holds one honest entry (2026-06-29T15:57:35Z).**

## Status (honest)

**L1, one run logged.** One report-only run logged 2026-06-29T15:57:35Z; no automated runs since.
`loop-audit` would score this ~100/100 and may read **L3**, because its activity heuristic counts
the words "triage"/"last run" found in `STATE.md` prose — a known false positive. The run log holds
only that one honest entry so the heuristic isn't laundered into an L3 claim. **It is genuinely L1.**

## What Worked

- Grounding every artifact in the loop-engineering repo's actual templates — names match what
  `loop-audit` detects (`loop-triage`, `loop-verifier`, `STATE.md`, `LOOP.md`, …).
- Branching from `main` (clean, independently mergeable) rather than from the docs branch.
- Keeping `loop-run-log.md` limited to real entries + the `LOOP.md` maturity note honest about L1-vs-L3.

## What Didn't Work / Avoid

- Do NOT seed `loop-run-log.md` with fake entries to reach L3 — that is the framework's own
  anti-pattern ("L3 before L1 quality") and defeats the purpose.
- Do NOT let the triage loop touch `01-context` enforcement or `03-evals` calibration — human-gate
  only (see `docs/safety.md`).

## Next Steps

0. **USER DECISIONS PENDING (in priority order):** (a) merge PR #21 — CI green ×2, review pending;
   (b) remove/relocate this HANDOFF.md before merge (its own header's rule); (c) approve creating
   the **5 wiring beads** from the devil's-advocate adjudication — external scheduler (GitHub
   Action cron or cloud routine) for daily-triage; kill-switch check moved into the scheduler
   (`if: !contains(labels, 'loop-pause-all')`) so it's external to the loop; close-check +
   publish-gate wired into CI on loop PRs (gate INTO the merge path); first real loop-verifier
   invocation on an actual diff; committed run evidence. These five convert the DA teardown's
   "2/10 operational, self-certification" findings into enforced properties.
1. **Run the loop again to earn operational L1** (the single logged run, 2026-06-29T15:57:35Z, predates this branch). In a Conductor workspace on this branch:
   `/loop 1d Run loop-triage. Update STATE.md. No code edits.` Let it rewrite `STATE.md`, then append
   one honest entry to `loop-run-log.md` and commit. That converts "L1 setup" into "L1 operational".
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

- Keep the loop scaffolding (`STATE.md`, `LOOP.md`, …) at the repo root of a public product repo, or
  relocate under a `loop/` or `.conductor/` namespace before merge?
- Once `.claude/` is repo-owned, do you still want the monorepo `~/.claude` harness in worktrees (it
  travels via the global layer anyway), or fully retire the symlink?

## Key Files Modified

This branch only; `main` and `docs/reconcile-roadmap-calibration` untouched. Added (loop scaffolding):
`STATE.md`, `LOOP.md`, `AGENTS.md`, `loop-budget.md`, `loop-run-log.md`, `docs/safety.md`,
`.claude/skills/loop-triage/SKILL.md`, `.claude/agents/loop-verifier.md`. Modified (bl-20260717 fix
sweep): the scaffolding docs above plus `03-evals/src/{eval_corrective,eval_planner,eval_ocr,h3_instr,test_g3,golden_v1_draft}.py`,
`03-evals/golden_v1_review.md`, `tools/run_guard.py`, `01-context/setup_a2.sh`, `.env.example`.

## Branch graph (as of the bl-20260717 close; exact tip = `git rev-parse HEAD`)

- `feat/loop-engineering-v3` — this work: `main` (`3096310`) + loop scaffolding (`8d71cf9`, `d2ef3b2`, `0aff6ed`) + the bl-20260717 fix commits.
- `main` → `3096310`.
- `docs/reconcile-roadmap-calibration` → `6382779` — CLAUDE.md + Conductor setup; pushed.

## Tracker Delta (beads — live `bd list`/`bd stats` at write time, 2026-07-19)

- Opened session 2026-07-16..17: **8** (`builder-guild-g9r` epic + `g9r.1`–`g9r.7`, the bl-20260717
  fix sweep) · Closed same session: **all 8** (close-check PASS, reason recorded per bead).
- Current open: **13 of 132 total** — the 3 excluded bugs (`78o`, `6mg`, `dju`), the deferred
  TrustGraph epic (`7vj` + 2 children), `pnd`, `2tn`, `11b` (FOUNDER-GATED), `9bi`, `w7y`, `6a2`,
  `kqo`. Bead text of `2tn`/`pnd`/`7vj.1` was refreshed to current serve.py line refs (g9r.7).
- Tracker lives in the gitignored `.beads/` (author-local; not visible to PR reviewers).
