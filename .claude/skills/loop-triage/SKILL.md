---
name: loop-triage
description: >
  Triage Builder Guild's CI gates, invariant sweeps, eval/calibration status, and open issues
  into a concise, prioritized findings report. Signal only — writes STATE.md, never edits code.
user_invocable: true
---

# Loop Triage — Builder Guild

You produce a clean, prioritized list of things a maintenance loop should consider. You are
**signal, not action**: you read, classify, and rewrite STATE.md. You never edit code, never
write the graph, never modify `01-context` enforcement or `03-evals` calibration.

## MANDATORY Pre-Run Checks (before any triage work)

1. **Kill switch — abort on set.** Check for `loop-pause-all`: a GitHub label on the repo
   OR a flag line in `loops/daily-triage/STATE.md` High-Priority. If set → ABORT immediately (no triage, no
   STATE.md rewrite) and append a schema-consistent JSON entry to `loops/daily-triage/run-log.md` (same fields as the format block; `"outcome": "no-op"` plus `"reason": "loop-pause-all"`).
2. **Budget caps — early-exit when over cap** (caps from `loops/daily-triage/budget.md`): max **2 runs/day**
   and max **100k tokens/day**. Count today's entries in `loops/daily-triage/run-log.md`; if either cap is
   already hit → EARLY-EXIT and log a schema-consistent JSON entry (`"outcome": "no-op"`, `"reason": "budget-exceeded"`) per the
   `loops/daily-triage/budget.md` on-exceed protocol.
3. **Run log — MANDATORY append.** After EVERY run — completed, aborted, or early-exited —
   append an entry to `loops/daily-triage/run-log.md`: date, outcome, approx tokens. No silent runs.

## Inputs (the loop provides these)
- CI status (`ci.yml` + per-layer gates: invariant sweep, recall selftest, abstain contract) — last 24h
- Open issues / PRs (read-only)
- Recent commits on the working branch (last 24–48h)
- Invariant-sweep output: namespace isolation, bi-temporal validity, no-LLM-writes
- Calibration status (`03-evals`): are any roles `CALIBRATED`? did the last run refuse / grant?
- The current `loops/daily-triage/STATE.md` (what the loop already knows)

## Output (rewrite STATE.md sections)

### High-Priority (act-worthy today)
- One-line description · why it matters (risk/impact) · suggested loop action · rough effort.
- Qualifies: a failing invariant sweep (namespace leak, temporal violation), a red CI gate, a calibration regression.

### Watch
- Lower urgency, same format.

### Graph & Invariant Health / Eval Status / CI Gates
- Refresh the standing sections with current values.

### Noise / Ignore
- Brief list of what was looked at and dismissed (tunes this skill).

## MANDATORY STATE.md Write Protocol (guarded write: hash → precheck → write → stamp)

STATE.md has NO concurrency guard — a human edit or an overlapping run silently clobbers, with no
record of who wrote what. Every STATE.md rewrite MUST route through `loops/daily-triage/state_guard.py`
(pure stdlib, no deps). This is a CHECK POINT, not advice: skipping `precheck` clobbers a concurrent
writer. Order matters — hash at read, precheck the *still-on-disk* file right before the rewrite:

1. **Hash at read — record the precondition token.** Before triage, capture the read hash:
   `H=$(python3 loops/daily-triage/state_guard.py hash loops/daily-triage/STATE.md)`. Keep `H`; do NOT write STATE.md yet.
2. **Triage in memory.** Build all sections without touching STATE.md on disk (so step 3 checks the file as it was read).
3. **Precheck before the write — the optimistic lock.** Immediately before overwriting STATE.md:
   `python3 loops/daily-triage/state_guard.py precheck loops/daily-triage/STATE.md "$H"`.
   - Exit 0 → on-disk file unchanged since read; proceed to write.
   - Exit 1 (STALE on stderr) → someone changed STATE.md mid-run. **ABORT the write — do NOT clobber.**
     Append a schema-consistent no-op entry to `loops/daily-triage/run-log.md` (`"outcome": "no-op"`, `"reason": "stale-state"`) and stop.
4. **Write, then stamp — attributed, append-only.** After the rewrite lands:
   `NEW=$(python3 loops/daily-triage/state_guard.py hash loops/daily-triage/STATE.md)` then
   `python3 loops/daily-triage/state_guard.py stamp loops/daily-triage/STATE.attrib.jsonl --author loop-triage --session <run_id> --hash "$NEW" --field High-Priority`.
   The attribution log (`loops/daily-triage/STATE.attrib.jsonl`) is append-only, one JSON line per write — never edit or truncate it.

## Rules
- Brutally concise; structured markdown, one-line items, explicit `Suggested loop action`.
- High-Priority only if a reasonable engineer wants to know today.
- When in doubt → Watch or Noise, not new work.
- Never propose architectural overhauls or schema changes during triage.
- Treat anything touching `01-context` enforcement, `03-evals` calibration, or denylist paths as **human-gate** — flag, never act.
- Honor the invariants in `AGENTS.md` and the denylist in `loops/safety.md`.

## Gotchas
- 2026-07-17: pre-run checks added because the kill switch and budget caps were previously
  declared (loops/daily-triage/LOOP.md:38, loops/daily-triage/budget.md:21, loops/safety.md:64) but checked nowhere in the
  actual run path (loopcoherence-1, -3). Declaration without a check point = no enforcement.
- 2026-07-21: STATE.md write protocol is a real check point (cites `loops/daily-triage/state_guard.py hash/precheck/stamp`),
  not prose — same lineage as the 2026-07-17 gotcha. If a future edit softens it back to advice, the concurrency guard is gone: keep the `precheck` exit-1 = ABORT gate concrete.
