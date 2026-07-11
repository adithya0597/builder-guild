# Security Policy

## Reporting a vulnerability

Please **don't open a public issue** for a security problem. Use GitHub's private
vulnerability reporting instead: go to the **Security** tab on this repo →
**Report a vulnerability**. That opens a private thread with the maintainer only.

## Response time

This is a solo-maintained project — expect an acknowledgment within **7 days**,
matching the same weekly cadence the repo uses to triage regular issues.

## What counts as highest severity

Builder Guild's whole pitch is a set of enforced invariants. A report that breaks
one of these is the highest-severity class:

- A namespace isolation leak — one role reading facts scoped to another role.
- Any path that lets an LLM write a fact instead of a human-reviewed edge.
- An edge write that bypasses the write gateway (`tools/check_write_gateway.py`).
- A staging-gate bypass — a `:Candidate` fact reaching `:RELATES_TO` without a
  human `promote()`.
- Forged or spoofed provenance in `serve()` output.

## Scope

Pre-1.0. All supported code lives on `main` — there are no maintained release
branches to worry about.

## Bug bounty

None. This is unpaid, solo open-source work.
