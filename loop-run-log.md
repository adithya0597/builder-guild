# Loop Run Log — Builder Guild

Append one JSON entry per loop run. Prune entries older than 30 days.

One run logged (2026-06-29T15:57:35Z, report-only); zero automated runs since. This is the
run-history spine for the daily-triage loop; entries append below. A heuristic "activity"
signal (e.g. the word "audit" in git history) is **not** a run and must not be recorded as one.

## Format

```json
{
  "run_id": "<ISO-8601 UTC>",
  "pattern": "daily-triage",
  "duration_s": 0,
  "items_found": 0,
  "actions_taken": 0,
  "escalations": 0,
  "tokens_estimate": 0,
  "outcome": "report-only | fix-proposed | escalated | no-op",
  "reason": "<optional; only on aborted/early-exited runs: loop-pause-all | budget-exceeded>"
}
```

## Recent Runs

<!-- Loop appends below this line. tokens_estimate is unmetered (no live token meter exposed to the loop). -->

```json
{"run_id": "2026-06-29T15:57:35Z", "pattern": "daily-triage", "duration_s": 276, "items_found": 2, "actions_taken": 0, "escalations": 0, "tokens_estimate": 30000, "outcome": "report-only"}
```
