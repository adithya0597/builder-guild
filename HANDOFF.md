# HANDOFF — `feat/loop-engineering-v3`

> Branch working doc for picking this up in a Conductor workspace. Not intended for `main` —
> remove or relocate before merging this branch.

## Goal

Make Builder Guild legible to **loop engineering** (cobusgreyling/loop-engineering): set it up to
be maintained by recurring, stateful, verified agent loops, starting at **L1 (report-only)**. This
branch adds the loop scaffolding plus the bl-20260717 fix sweep — docs-truth reconciliation and
eval/tooling truth fixes under `03-evals`, `tools/`, `01-context/setup_a2.sh`, and `.env.example`.

## Current Progress

**Session 2026-07-20/21 (loop-operationalization buildloop — 3 sections shipped) — newest; the
research + 07-16..19 blocks follow.** Ran `/buildloop` on three sections in sequence; the independent
codex/verifier review caught a real bug in EACH. All merged fast-forward to v3 (verified end-state:
`git rev-parse HEAD` = `origin/feat/loop-engineering-v3` = **`702a11e`**, clean tree).
- **ye0 + hot (merge gates)** → `.github/workflows/classify.yml` (deterministic t0/t1/t2 risk-tier
  required check, 14/14 tier cases) + `publish-gate.yml` (CI twin of the disclosure gate) +
  `.github/rulesets/loop-merge-gates.json` (payload). **Codex P1-B (real, silent):** `tools/publish_gate.sh`
  did `for f in $FILES` → a filename with a space word-split → the file was skipped → a secret exited
  CLEAN. Fixed NUL-delimited (closes the CI twin AND the live local pre-push hook; proven 5/5).
  Self-editing-workflow ceiling accepted-residual (in-repo `pull_request` checks run from PR-head, can't
  gate own definition; option-2 CODEOWNERS+approvals≥1 is INVALID solo — GitHub forbids self-approval).
  Live ruleset apply + classic-protection retire → founder bead `8pf`; org-ruleset proper fix → `2h9`.
- **oy7 (heartbeat)** → `.github/workflows/loop-heartbeat.yml` dead-man's-switch (alerts when the loop
  misses a run; honors `LOOP_PAUSE_ALL`; MAX 33h). **3 codex passes; P1 (silent):** a future-dated
  `run_id` read FRESH and auto-closed live alerts. Fixed structurally — filter future stamps OUT
  (`newest_valid_run_id(max_iso)`) before selecting newest, so a typo can't be the freshness basis.
  Proven 13/13 incl codex's exact counterexample; final codex confirm PASS.
- **btj (loop-verifier on a real diff)** → dispatched `loop-verifier` on `223b285`: **REJECT** (caught
  STATE.md citing a **CodeQL** run `29653108642` as the *ci.yml smoke+graph* gate — a surface-mismatch;
  real main ci run = `29452819406`). Maker fix `d500757` → re-verify **APPROVE**. Verdict recorded in
  `loops/daily-triage/verifier-log.md`, referenced from `run-log.md`. Maker/checker split validated
  end-to-end (the independent checker caught a defect the actor missed).

**Session 2026-07-20 (research → operationalization wiring) — the 07-16..19 block
follows.** Ran, in order: (1) `/explore` `loopmature-20260720a` — FULL CLOSE PASS, 8-lane external
sweep (websearch/github/academic/reddit/x-twitter/youtube/context7 + last30days-empty), report
`.explore/REPORT-loopmature-20260720a.md`; verdicts = enforce in the platform layer, hybrid
STATE (markdown + deterministic hash/version primitives, NOT wholesale state.json), maturity =
schedule-first + run-count evidence + heartbeat. Two user X links (Anatoli Kopadze / Anthropic AI
DevCon "dreaming" talk) mined locally (yt-dlp transcript + 20 slide frames). (2) Three parallel
reports → git-excluded `audits/`: `SOLO_OPERATOR_AND_L2_SLIMMING.md` (SMOKING GUN, verified via
`gh api`: `main` protection is theatrical — `required_approving_review_count=1` the solo owner can
never self-satisfy + `enforce_admins=false` + `required_status_checks=null`; the solo gate is
required *status checks* + 0 approvals + no-bypass ruleset), `IN_THE_LOOP_OS_REVIEW.md` +
`AGENT_HUB_FIELD_GUIDE_REVIEW.md` (both by **Angus Sewell**, NOT Eric Siu). (3) `loops/` restructure
(commit `2546e25`) — per-loop folders like `.claude/skills/`. (4) Manual loop test run
2026-07-20T20:03:23Z on the relocated structure (commits `223b285`+`21b28c6`). (5) `/buildloop`
`bl-20260720-sched` → **PR #22 OPEN/MERGEABLE, CI green (ci+pr-gate+cla)** — beads `phy` (cron
scheduler) + `8cj` (scheduler-side kill switch) in one PR; the security review (2 codex passes + 1
confirm + RED-TEAM) drove an **L2 route-up re-architecture to two separated jobs** (agent job
`contents:read`+no-token → artifact; fresh-checkout commit job holds the write token) — closes the
"untrusted agent contaminates a later privileged step" class; close-check.sh exit 0.

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

**L1, two manual runs logged; scheduler + merge-gate + heartbeat workflows authored (on v3), none firing yet.** Report-only runs 2026-06-29T15:57:35Z and 2026-07-20T20:03:23Z. On v3 now: `loop-heartbeat.yml`, `classify.yml`, `publish-gate.yml` (+ ruleset payload); the triage `loop-triage.yml` scheduler is still on PR #22. ALL scheduled/PR workflows fire only from the default branch — inert until v3 merges to main + secret/variable set (bead `006`) + the ruleset is applied (bead `8pf`). The `loop-verifier` has now been exercised for real once (btj). No scheduled runs yet.
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

0. **USER DECISIONS PENDING (in priority order):**
   (a) **Merge PR #22** (`feat/loop-scheduler` → `feat/loop-engineering-v3`) — scheduler + kill
       switch, CI green (ci+pr-gate+cla), close-check exit 0. Then merge PR #21 → main.
   (b) **After #22 merges, bead `builder-guild-006` (merge-gated proofs):** set repo **secret**
       `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) + **variable** `LOOP_PAUSE_ALL=false`;
       then prove on the default branch — a scheduled `loop-triage` run appears in `gh run list`,
       and with `LOOP_PAUSE_ALL=true` the next run's triage job shows *skipped*. This is what turns
       "L1 tested" into "L1 operational".
   (c) **Bead `builder-guild-bgo` (RED-TEAM residual, your threat-model call):** API-key egress from
       the agent job — bounded to credit-burn (rotatable; write token never meets untrusted code).
       Decide: add `harden-runner` egress-allowlist + org spend cap, OR accept-as-residual at L1.
   (d) **Bead `builder-guild-8pf` (LIVE ruleset apply — the ye0/hot payload; founder settings action):**
       `gh api repos/adithya0597/builder-guild/rulesets --method POST --input .github/rulesets/loop-merge-gates.json`
       then drop `required_approving_review_count`→0 AND confirm no-bypass — turns the theatrical live
       config real (see `audits/SOLO_OPERATOR_AND_L2_SLIMMING.md`; the committed JSON is inert until POSTed).
   (e) Remove/relocate this HANDOFF.md before merging the branch to `main` (its own header's rule).
   **Epic `tic` children — DONE this session:** `phy`,`8cj` (scheduler, PR#22), `ye0`,`hot` (merge gates),
   `oy7` (heartbeat), `btj` (verifier-on-real-diff). **Remaining L1 build sections (not started):** `lbd`
   (STATE.md content-hash + attributed writes), `icg` (settings-tamper alarm — trimmed, .github→t2 half now
   done by hot), `d0j` (check_citations bot-wall). **Founder/hardening beads:** `8pf`,`006`,`bgo`,`2h9`,`ave`.
   Suggested next build: `lbd` → then `icg`/`d0j`. NOTE: `lbd`/`icg`/`d0j` prove themselves best once the
   loop is scheduled-LIVE (bead `006` / founder secret) — consider setting that first.
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
`loops/daily-triage/{LOOP.md,STATE.md,run-log.md,budget.md}`, `loops/safety.md`, `loops/README.md`, `AGENTS.md`,
`.claude/skills/loop-triage/SKILL.md`, `.claude/agents/loop-verifier.md`. Modified (bl-20260717 fix
sweep): the scaffolding docs above plus `03-evals/src/{eval_corrective,eval_planner,eval_ocr,h3_instr,test_g3,golden_v1_draft}.py`,
`03-evals/golden_v1_review.md`, `tools/run_guard.py`, `01-context/setup_a2.sh`, `.env.example`.

**Loop-operationalization buildloop (2026-07-20/21, on v3):** NEW `.github/workflows/classify.yml`
(risk-tier required check), `.github/workflows/publish-gate.yml` (disclosure-gate CI twin),
`.github/rulesets/loop-merge-gates.json` (ruleset payload — inert until POSTed, bead `8pf`),
`.github/workflows/loop-heartbeat.yml` (dead-man's-switch), `loops/daily-triage/verifier-log.md` (NEW —
maker/checker audit trail). MODIFIED: `tools/publish_gate.sh` (NUL-delimited scan, codex P1-B fix),
`loops/daily-triage/{STATE.md,run-log.md}` (verifier REJECT fix + verdict reference).
Specs/ledger: `.buildloop/specs/bl-20260720-{gates-ye0,gates-hot,oy7}-plan-v2.md`, `.buildloop/run-ledger.jsonl`.

**On PR #22 branch `feat/loop-scheduler` (NOT yet in this branch — merge via #22):**
`.github/workflows/loop-triage.yml` (NEW — two-job scheduler); `loops/daily-triage/{LOOP.md,budget.md}`
+ `loops/safety.md` (three-layer kill-switch docs + cap/semantics precision). Commits `7a858cc`
(impl) + `c377d4c` (review-hardening).

Local-only (git-excluded `audits/`, 2026-07-20): `SOLO_OPERATOR_AND_L2_SLIMMING.md`,
`IN_THE_LOOP_OS_REVIEW.md`, `AGENT_HUB_FIELD_GUIDE_REVIEW.md`. Explore run:
`.explore/REPORT-loopmature-20260720a.md` + `source-ledger-loopmature.jsonl`.

## Branch graph (exact tip = `git rev-parse HEAD`; verified 2026-07-21)

- `feat/loop-engineering-v3` — `main` (`3096310`) + loop scaffolding + bl-20260717 fixes + `loops/`
  restructure (`2546e25`) + loop run/docs-truth (`223b285`, `21b28c6`, `2b1cbd2`) + **merge-gates**
  (`f815e14`) + **heartbeat** (`3a33176`) + **btj verifier/STATE-fix** (`d500757`, `702a11e`). Tip
  **`702a11e`** = `origin/feat/loop-engineering-v3` (clean tree). PR #21 → main, OPEN/**BLOCKED** — the
  theatrical 1-approval a solo owner can't self-satisfy; beads `8pf`/`006` are the fix.
- `feat/loop-scheduler` — off `21b28c6`: `7a858cc` (scheduler impl) + `c377d4c` (review-hardening).
  PR #22 → `feat/loop-engineering-v3`, OPEN/MERGEABLE, CI green.
- `main` → `3096310`.
- `docs/reconcile-roadmap-calibration` → `6382779` — CLAUDE.md + Conductor setup; pushed.

## Tracker Delta (beads — live `bd list`/`bd stats` at write time, 2026-07-21)

- Session 2026-07-20/21 (buildloop sections): closed **4** — `ye0`, `hot` (merge gates), `oy7`
  (heartbeat), `btj` (verifier-on-real-diff), all via close-check PASS + reason recorded. Opened **3**
  — `8pf` (founder: apply ruleset), `2h9` (org-ruleset proper fix for the self-editing ceiling), `ave`
  (ship SYNC-REGION drift tests to CI). Live count: **22 open of 148 total** (`bd stats`: Closed 126).
- Session 2026-07-20 (earlier): opened **13** — `nfy` (explore loopmature, CLOSED), epic `tic`, `phy`
  (CLOSED), `8cj` (CLOSED), `ye0`, `btj`, `oy7`, `d0j`, `lbd`, `hot`, `icg`, `006`, `bgo`.
  Closed **3** (`nfy`, `phy`, `8cj`). Live count: **23 open of 145 total** (`bd stats`:
  Closed 122, In Progress 0). Epic `tic` open, blocked by its 9 unstarted children + `006`+`bgo`.
- (superseded line kept for history) earlier same-session snapshot read 11 opened / 23 of 143;
  the +2 are `006`+`bgo` created during the buildloop run.
- Session 2026-07-16..17: opened **8** (`builder-guild-g9r` epic + `g9r.1`–`g9r.7`, the bl-20260717
  fix sweep) · Closed same session: **all 8** (close-check PASS, reason recorded per bead).
- Current open: **13 of 132 total** — the 3 excluded bugs (`78o`, `6mg`, `dju`), the deferred
  TrustGraph epic (`7vj` + 2 children), `pnd`, `2tn`, `11b` (FOUNDER-GATED), `9bi`, `w7y`, `6a2`,
  `kqo`. Bead text of `2tn`/`pnd`/`7vj.1` was refreshed to current serve.py line refs (g9r.7).
- Tracker lives in the gitignored `.beads/` (author-local; not visible to PR reviewers).
