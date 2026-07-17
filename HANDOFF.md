# HANDOFF — `feat/loop-engineering-v3`

> Branch working doc for picking this up in a Conductor workspace. Not intended for `main` —
> remove or relocate before merging this branch.

## Goal

Make Builder Guild legible to **loop engineering** (cobusgreyling/loop-engineering): set it up to
be maintained by recurring, stateful, verified agent loops, starting at **L1 (report-only)**. This
branch adds the loop scaffolding plus the bl-20260717 fix sweep — docs-truth reconciliation and
eval/tooling truth fixes under `03-evals`, `tools/`, `01-context/setup_a2.sh`, and `.env.example`.

## Current Progress

L1 loop setup committed on this branch (`feat/loop-engineering-v3`, commit `8d71cf9`, 8 files, +341
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

## Tracker Delta (beads)

- Opened this session: **0** · Closed this session: **0**.
- The loop-engineering work was not tracked in beads. Pre-existing open issues are unrelated to this
  branch and live in the gitignored `.beads/` tracker.
