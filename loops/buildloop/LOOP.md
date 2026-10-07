# loop: buildloop

## Purpose
Report loop findings; evidence lives in the miner ledger by run-id, without quotes.

## Cadence
event: issue labeled build:ready | timer: daily 06:00 UTC

## Level
L1 report-only — escalation to L2 is a separate human-gated decision

## Invocation (current mode)
Manual, as a skill: `/buildloop`. The triggers below are DECLARED and land with the workflow;
until that workflow is on the default branch neither fires, and the rubric reports
`FAIL scheduling` — which is the accurate state, not a defect to paper over.

## Scheduling locality (local vs cloud)
- **Choice: cloud** — `.github/workflows/loop-dispatch.yml` (GitHub Actions). This loop reads
  repo-side state only; nothing in its discovery set is glued to one machine.
- **Cost accepted:** one-hour minimum interval, clean clone per run. Cadence is daily 06:00 UTC, so
  neither binds.
- **Not local `/loop`:** that needs the machine on and a session open, so it would run only
  when someone is already at the keyboard — the days least likely to need it.
- **Both trigger kinds declared**, because a timer alone misses the event and an event alone
  misses the quiet week:
  - event: `issues: [labeled]`
  - timer: `daily 06:00 UTC`
  - `workflow_dispatch` is present for manual runs but does NOT count as a trigger — a button
    a human must remember to press is the Manual loop with extra steps.

## Allowed writes
- loops/buildloop/STATE.md
- loops/buildloop/run-log.md

## Done condition
```
grep -q "\"run_id\": \"$(date -u +%Y-%m-%d)" loops/buildloop/run-log.md
```

## Evaluator behavior
The done condition above is EXECUTED, not read: its exit status decides the verdict, and
findings cite the command output. A checker that only reads judges "does this look right"; one
that runs judges "does it hold". The evaluator defaults to doubt — it assumes the result is
wrong until the command proves otherwise — and is a different agent from the one that produced
the work, because an author cannot step outside its own perspective.

## Stop (the boundary this loop cannot infer)
The loop faithfully does everything stated and nothing omitted, so this section is not
boilerplate — it is where the operator's intent about keeping control is made permanent.
- **Never merge.** Not a PR, not a branch, at any level.
- **Never delete.** Supersede by appending; never erase.
- **Never write outside** the allowed paths above.
- **Never escalate autonomy.** Code may revoke a grant; it may never issue one.
- **When confidence is below certain, escalate rather than act** — uncertain items go to the
  STATE High-Priority section for a human, not into a change.

## Sample read (comprehension-rot guard)
Verification debt has an evaluator behind it and token blowout has a cap; comprehension rot is
the debt with no natural alarm.
- Each run, the operator reads ONE representative finding and writes a one-line explanation of
  what changed and why, into the run-log entry's `sample_read` field.
- Inability to explain a sampled change means the map is behind the codebase — the signal.
- A filled `sample_read` is a precondition for any promotion review.

## Kill switch
pause flag in STATE.md High-Priority section — abort run if present
