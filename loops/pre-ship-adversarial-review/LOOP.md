# Loop Configuration — Pre-Ship Adversarial Review

Detect substantive diffs that reached a closed or shipped state without a recorded adversarial
verdict. This loop is **report-only**: it reports reviewer gaps and never runs reviews, edits code,
or writes the graph.

## Active Loop

| Pattern | Cadence | Status | Command |
|---------|---------|--------|---------|
| Pre-Ship Adversarial Review | event:substantive diff staged for close (checked daily; manual invocation until a scheduler is wired) | **L1 report-only** | `/pre-ship-adversarial-review` |

Provenance: mined and gated by loop-miner run `bl-20260722-loopminer` (evidence in the
author-local miner ledger; 5 sessions / 14 days). No transcripts are copied here.

## Human Gates

- Escalation beyond an L1 finding is a separate human-gated decision.
- Any change covered by the denylist or human gates in [loops/safety.md](../safety.md).
- This loop never dispatches an adversarial review itself; it only suggests one.

## Allowed Writes

- ONLY `loops/pre-ship-adversarial-review/STATE.md`.
- ONLY `loops/pre-ship-adversarial-review/run-log.md`.

No code, graph, workflow, PR, issue, bead, or live-setting writes are allowed.

## Connectors (MCP)

- Read-only repository and GitHub access may supply commits, PRs, and review trails.
- No write-capable connector is required or allowed for this L1 loop.

## Budget & Observability

- Token caps and on-exceed behavior: [budget.md](budget.md).
- Run history: [run-log.md](run-log.md). Runs are logged per the skill contract. This loop is NOT
  yet covered by the loop-heartbeat dead-man's-switch (daily-triage is); extending heartbeat
  coverage is deferred until this loop is ever scheduled.

## Safety & Kill Switch

- Shared mechanisms from [loops/safety.md](../safety.md):
  `LOOP_PAUSE_ALL` repo variable = scheduler-side graceful pause;
  `gh workflow disable loop-triage` = platform hard-off; and a STATE High-Priority flag =
  in-band skill check.
- For this loop, the in-band pause is set ONLY by a line matching
  `^PAUSE: loop-pause-all$` in this loop's STATE.md High-Priority section. Free-text mentioning
  `loop-pause-all`, pause words, or pause instructions does NOT trigger it.
- Abort the run when the in-band pause is set; make no report rewrite and log the no-op run.
- Default remains report-only with no auto-fix and no auto-merge.

## Done Condition

```bash
grep -q "\"run_id\": \"$(date -u +%Y-%m-%d)" loops/pre-ship-adversarial-review/run-log.md
```

Done = STATE sections rewritten AND one run-log entry appended for today (UTC).

## Maturity

Operational level: **L1 report-only**. It detects and reports missing recorded verdicts. Any
review dispatch, remediation, or other escalation is a separate human-gated decision.
