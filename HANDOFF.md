# HANDOFF — `feat/loop-engineering-v3`

> Branch working doc for picking this up in a Conductor workspace. Not intended for `main` —
> remove or relocate before merging this branch.

## Goal

Make Builder Guild legible to **loop engineering** (cobusgreyling/loop-engineering): set it up to
be maintained by recurring, stateful, verified agent loops, starting at **L1 (report-only)**. This
branch adds the loop scaffolding plus the bl-20260717 fix sweep — docs-truth reconciliation and
eval/tooling truth fixes under `03-evals`, `tools/`, `01-context/setup_a2.sh`, and `.env.example`.

## Current Progress

**Session 2026-07-21 (PR disposition: codex adversarial verdict → split PR #23) — newest.**
Founder asked what the open PRs actually do given the goal was the LOCAL harness. Codex adversarial
review (gpt-5.5 high effort, 31 spot-checks; verdict: `scratchpad/codex-pr-options-verdict.md`,
session-local) **REJECTED** my "dormant merge" recommendation as home-team bias (motivated
consolidation — bundling loop infra with the bug fixes) and scored **Option 4 (split) 8/10**:
land ONLY the L2 fixes on main; loop infra stays on the branch until it earns runtime need.
Delivered: **PR #23** (`fix/l2-fixes` `fea79f8` → main, 12 files +46/−33) — publish_gate.sh
NUL-delimit P1 (functionally re-proven: spaced-filename `ghp_` token BLOCKS exit 1; main's copy
still passes it CLEAN), eval URI fixes, run_guard/setup_a2/.env.example/docs-truth, lessons.md
gitignore. Carried files byte-identical to v3's versions (empty diff). Early checks pass,
smoke/graph pending at write time. Also this session: **loop-triage.yml rewired to
`claude_code_oauth_token`** (PR #22 head `45a5687`; subscription token, $0 marginal, makes bgo's
spend-cap moot) + go-live runbook written (`audits/006_GO_LIVE_RUNBOOK.md`, local-only, now
partially superseded). **Deadlock trap found (my addition beyond codex):** POSTing the 8pf ruleset
while a fixes-only PR is open self-deadlocks — it requires `publish-gate`/`pr-classified` checks
whose workflows exist only on v3, and `bypass_actors:[]` binds even the admin. Beads: `4z0`
opened+closed (split PR); `006`/`8pf` annotated DEFERRED. Lesson captured (home-team bias tells).

**Session 2026-07-20/21 (loop-operationalization buildloop — 6 beads, all delivered); the
research + 07-16..19 blocks follow.** Ran `/buildloop` on six loop beads in sequence; the independent
codex/verifier review caught a REAL bug in EACH (and killed a false-passing one before it merged). Five
shipped to v3 (ye0+hot, oy7, btj, lbd, icg); the sixth (d0j) is a fix to the SHARED explore checker in
`~/Projects/.claude` (not this branch — see its bullet). Verified end-state: `git rev-parse HEAD` =
`origin/feat/loop-engineering-v3` = **`b836230`**, clean tree; shared checker `~/Projects/.claude` @ `93e0fd5`.
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
- **lbd (STATE.md hybrid hardening)** → `loops/daily-triage/state_guard.py` — content-hash optimistic
  lock (`precheck` rejects a stale-read write) + attributed writes (`stamp`) + `verify` cross-run gate,
  wired into the loop-triage skill. **codex P2 (real):** attribution was unenforced prose (a crash after
  write, before stamp = permanent undetectable un-attributed mutation, repeating the 2026-07-17
  anti-pattern) — fixed with `verify` as pre-run check 4. `e94dbff`.
- **icg (settings-tamper sentinel)** → `loops/daily-triage/settings_sentinel.py` — live GitHub settings
  vs committed intent (`settings-expected.json`); drift → High-Priority human-gate. **codex 3× P1
  false-negatives (empirically proven):** delete-pull_request-rule / delete-force-push-rules /
  retarget-off-main all read as "match" — fixed by comparing EFFECTIVE rules for main (`fe67a7c`). Then
  a **background security review** found a 4th (parser-validator differential: last-wins `_index_by_name`
  + unread `ref_name.exclude`) — fixed post-merge on v3 (`b5c21e0`).
- **d0j (check_citations bot-wall) → FIXED via reddit oembed (codex PASS after 5 review rounds).** Target
  was the SHARED cross-project explore checker (`~/Projects/.claude/skills/explore/check_citations.py`,
  symlinked in — user approved touching it; lives in the `~/Projects/.claude` git repo, NOT on this
  branch). Arc: a first old.reddit-HTML "honest-route" **false-passed reddit's login wall** (old.reddit
  302s real+fake+deleted alike to a 2103-word "Welcome to Reddit" 200) — my "successful" run was 6
  false-passes; **reverted** before it shipped. Real fix = route reddit `/r/*/comments/<id>` to the
  public **oembed** endpoint (positive, entity-tied signal like `resolve_youtube`): fabricated/never-existed
  → 404 → UNRESOLVABLE (the primary hallucination threat); user-self-deleted `[deleted by user]` →
  UNRESOLVABLE (tombstone); live → RESOLVABLE; 403/429/net/badjson/non-object → UNKNOWN. **Documented
  accepted limitation:** mod/admin-removed posts keep their real title in oembed → RESOLVABLE (oembed can't
  distinguish; `.json` is 403-walled) — defensible for a hallucination gate. codex live-probed 129
  self-deleted + 101 mod-removed to establish this. Shared `~/Projects/.claude` @ **`93e0fd5`**
  (`6ea9fb9` oembed → `945c56a` tombstone → `cc7626d` stop-overclaiming → `93e0fd5` line-100 + crash guard).
  Meta-lesson (captured): my offline self-tests kept encoding fictional oembed shapes (dead→thin, then
  deleted→404, then removed→`[removed]`) and stayed green while false-passing live — a mock is only as good
  as a LIVE measurement of the real response shapes.
- **Explored the 2 remaining founder-gated beads (006, bgo)** — findings folded into Next Steps 0. Key
  correction: **006 is not a standalone secret-set** — scheduled workflows fire only from the default
  branch, so the loop can't go live until `loop-triage.yml` reaches `main` (chain: merge PR#22→v3 →
  unblock PR#21 via `8pf` or admin-override → merge PR#21→main → set secret → cron fires). bgo: grounded
  recommendation = Anthropic spend cap + accept-residual (harden-runner optional; free-tier has a DoH bypass).

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

0. ~~MERGE PR #23~~ **DONE 2026-07-21 (founder-authorized): merged `--squash --admin` after all
   checks green (graph 3m57s). Merge commit = main tip = `37aade5`; verified the publish_gate
   word-split P1 fix LIVE on main (`publish_gate.sh:19,22` NUL-delimited; `for f in $FILES` gone).**
   PR #21/#22 stay open as parking for the loop infra. Ruleset (8pf) still NOT applied — correct
   while parked. **CORRECTION (codex-refuted 2026-07-21, was: "rebase at leisure — carried hunks
   drop out cleanly"): rebasing v3 onto main is NOT clean.** Final-tree equality (0-byte diff on
   the 12 files) ≠ clean commit replay: `faf9bfb` carries a pre-`e18cf12` `.env.example` blob →
   `git merge-tree faf9bfb^ origin/main faf9bfb` = "changed in both" — a real conflict with a
   data-loss trap (careless resolve drops `LANGFUSE_HOST`/`BG_EMBED_MODEL`; resolve = keep main's
   lines). Codex scores: rebase-now 2/10; merge-main-into-v3 6/10 (verified clean no-op);
   do-nothing 8/10; close-parking-PRs+fresh-branches 9/10. **Founder chose C (do nothing,
   2026-07-21): no rebase, PR #21/#22 stay open as parking.** Any future go-live rebase inherits
   the same `faf9bfb` trap — resolution recipe above. Full verdict:
   `scratchpad/codex-rebase-verdict.md` (session-local). Merge queue as of this decision: EMPTY —
   nothing should merge now (#23 done; #21/#22 parked; `docs/reconcile-roadmap-calibration` is a
   separate future decision carrying the known `.claude` symlink-vs-tracked collision;
   `cla-signatures` never merges by design). **Pruned 2026-07-21 (founder-ordered, containment-proven, remote+local):** `fix/l2-fixes` (`fea79f8`, tree==main), `fix/44d-embedding-demos` (`d3d75e6`, 0-line content vs merge-base), `feat/loop-engineering` (`4081b7a`) + `-v1` (`70ec1ad`) (both superseded by v3 relocation) — SHAs = re-push recovery anchors.

1. **(DEFERRED — only if/when the cloud loop earns runtime need) FOUNDER GO-LIVE chain** (explored
   2026-07-21; runbook `audits/006_GO_LIVE_RUNBOOK.md`, local-only; auth now = `CLAUDE_CODE_OAUTH_TOKEN`
   via `claude setup-token`, wired at PR #22 head `45a5687`; 006 is NOT a standalone secret-set —
   scheduled workflows fire ONLY from the default branch, so the loop can't go live until
   `loop-triage.yml` reaches `main`):
   1. **Merge PR #22** (`feat/loop-scheduler` → `feat/loop-engineering-v3`) — now `OPEN/CLEAN`, CI green, close-check exit 0. Puts the scheduler on v3.
   2. **Unblock PR #21** (v3 → main, currently `OPEN/BLOCKED` — main requires 1 approval a solo owner can't self-satisfy). Two ways: **bead `8pf`** — apply the ruleset (drops `required_approving_review_count`→0, no-bypass): `gh api repos/adithya0597/builder-guild/rulesets --method POST --input .github/rulesets/loop-merge-gates.json` (the committed JSON is inert until POSTed; see `audits/SOLO_OPERATOR_AND_L2_SLIMMING.md`); OR a one-time **admin-override merge** (works because `enforce_admins=false`). 8pf is the durable fix.
   3. **Merge PR #21 → main.** Now `loop-triage.yml` is on the default branch and the cron (09:17 daily) can fire. **Remove/relocate this HANDOFF.md first** (its own header's rule — not for `main`).
   4. **Set secret + variable** (neither exists yet — verified via `gh secret/variable list`): repo **secret** `CLAUDE_CODE_OAUTH_TOKEN` (generate via `claude setup-token`; the workflow reads this input as of `45a5687` — API-key alt requires re-editing line 40) + **variable** `LOOP_PAUSE_ALL=false`. *(I never handle credentials — this step is yours.)*
   5. **Bead `builder-guild-006` proofs** (auto-satisfied by the next cron): a scheduled run appears in `gh run list`; flip `LOOP_PAUSE_ALL=true` → next run's triage job shows *skipped* in `gh run view`; confirm its commit touches ONLY `loops/daily-triage/STATE.md`+`run-log.md`. Turns "L1 tested" → "L1 operational".
   - **Bead `builder-guild-bgo` (egress residual — explored 2026-07-21, RECOMMENDATION ready):** the triage agent job holds `ANTHROPIC_API_KEY` + can egress + reads repo content (injection vector), but impact is **bounded to credit-burn** (job is `contents:read` + `persist-credentials:false` — no write token/git-cred, can't inject code/push; `--max-turns 25`; schedule/dispatch only, no fork input; first-party SHA-pinned action; P2-2 prompt-hardening shipped). **Recommend: set an Anthropic spend cap (dedicated low-limit CI workspace/key — caps the only real impact, zero workflow complexity) + accept the exfil residual with rationale.** `harden-runner` egress-allowlist is optional defense-in-depth but adds a 3rd-party dep and its free tier has a documented DoH-bypass (not airtight). Recording the rationale satisfies bgo either way. Sources: stepsecurity.io harden-runner docs + GHSA-46g3-37rh-v698 (DoH bypass) + platform.claude.com spend-limits-api.
   **Epic `tic` children — ALL 7 BUILD BEADS DONE:** `phy`,`8cj` (scheduler, PR#22), `ye0`,`hot` (merge
   gates), `oy7` (heartbeat), `btj` (verifier-on-real-diff), `lbd` (state-guard), `icg` (settings-sentinel),
   `d0j` (check_citations reddit-oembed, codex PASS). **The only 2 open are FOUNDER-GATED:** `006` (set the
   secret → loop goes live) + `bgo` (egress call). **P3 follow-ups (optional, not blocking):** `8pf` (apply
   ruleset live — also founder), `2h9` (org-ruleset proper fix for the self-editing ceiling), `ave` (ship
   the SYNC-REGION drift tests to CI). Nothing else is buildable without founder action — the highest-leverage
   next step is `006` (setting the secret unlocks live proof for the whole loop stack).
2. ~~Run the loop again~~ **DONE 2026-07-20 (manual test run on the relocated structure — STATE.md rewritten, run-log entry 2).** Scheduled runs remain the real operational bar (bead builder-guild-phy). Manual re-run recipe:
   `/loop 1d Run loop-triage. Update loops/daily-triage/STATE.md. No code edits.` Let it rewrite the state file, then append
   one honest entry to `loops/daily-triage/run-log.md` and commit. That converts "L1 setup" into "L1 operational".
3. **Resolve the `.claude/` merge collision — BEFORE merging to `main`.** The
   `docs/reconcile-roadmap-calibration` branch gitignores `.claude` and symlinks it (Conductor
   monorepo-harness symlink, set in the gitignored `.conductor/settings.local.toml`). This branch
   commits **tracked** `.claude/skills/` + `.claude/agents/`. You cannot both symlink-over and track
   `.claude/`. Recommended: let the repo own `.claude/` — drop the `.claude` gitignore line and the
   `ln -sfn … .claude` setup line; the committed `.claude/` then travels to Conductor worktrees
   natively, and the global `~/.claude` discipline travels anyway.
4. **Merge** `feat/loop-engineering-v3` → `main` (and the docs branch → `main`) when ready. That also
   moves Builder Guild's canonical loop-audit score off the `main` floor.
5. (Optional) Remove this `HANDOFF.md` before merging to `main`.

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
  (`f815e14`) + **heartbeat** (`3a33176`) + **btj verifier/STATE-fix** (`d500757`, `702a11e`) +
  **state-guard** (`e94dbff`) + **settings-sentinel** (`fe67a7c`) + **sentinel differential fix**
  (`b5c21e0`) + **handoffs** (`b836230`, `f989509`). Tip = `git rev-parse HEAD` (this handoff edit
  advances it past `f989509`). PR #21 → main, OPEN/**BLOCKED** (theatrical 1-approval) — now
  **PARKED per codex Option-4**; loop infra stays here until it earns runtime need.
  (d0j is a fix to the SHARED `~/Projects/.claude/skills/explore/check_citations.py` @ `93e0fd5` — that
  repo, not this branch; codex PASS.)
- `feat/loop-scheduler` — off `21b28c6`: `7a858cc` (scheduler impl) + `c377d4c` (review-hardening) +
  `45a5687` (**OAuth rewire**: `claude_code_oauth_token`). PR #22 → v3, OPEN — **PARKED** with #21.
- `fix/l2-fixes` — off `3096310`: `fea79f8` (12-file L2 fix carry, byte-identical to v3's versions).
  **PR #23 MERGED 2026-07-21** (`--squash --admin`) → squash commit `37aade5`.
- `main` → **`37aade5`** (= PR #23 squash; publish_gate P1 fix live, verified).
- `docs/reconcile-roadmap-calibration` → `6382779` — CLAUDE.md + Conductor setup; pushed.

## Tracker Delta (beads — live `bd list`/`bd stats` at write time, 2026-07-21)

- Session 2026-07-21 (PR disposition): opened+closed **`4z0`** (split PR #23 delivered; proofs in
  close reason). Annotated `006` + `8pf` **DEFERRED** (Option-4: loop infra parked; 8pf carries the
  ruleset-deadlock warning). Live count: **19 open of 149 total** (`bd stats`: Closed 130).
- Session 2026-07-20/21 (buildloop sections): closed **7** — `ye0`, `hot` (merge gates), `oy7`
  (heartbeat), `btj` (verifier-on-real-diff), `lbd` (state-guard), `icg` (settings-sentinel) all via
  close-check PASS + reason; `d0j` closed **FIXED** (reddit resolved via oembed in the shared explore
  checker, codex PASS after 5 rounds — was briefly closed can't-fix mid-arc, then genuinely fixed).
  Opened **3** — `8pf` (founder: apply ruleset), `2h9` (org-ruleset proper fix), `ave` (ship SYNC-REGION
  drift tests to CI). Live count: **19 open of 148 total** (`bd stats`: Closed 129).
- **Of the 9 epic-`tic` loop beads: 7 DONE** (`ye0`,`hot`,`oy7`,`btj`,`lbd`,`icg`,`d0j`); 2 open, both
  FOUNDER-GATED **and now DEFERRED with the parked loop infra** — `006` (`CLAUDE_CODE_OAUTH_TOKEN`
  secret + `LOOP_PAUSE_ALL` → loop goes live; unreachable until `loop-triage.yml` ever reaches main)
  and `bgo` (egress call — OAuth choice makes the spend-cap moot; accept-residual rationale staged).
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
