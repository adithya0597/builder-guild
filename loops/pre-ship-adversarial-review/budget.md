max_runs_per_day: 2
max_tokens_per_day: 30000
# "today" means the UTC date of run_id.
on exceed: EARLY-EXIT and log a run-log entry with outcome no-op, reason budget-exceeded
