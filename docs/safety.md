# Loop Safety & Guardrails — Builder Guild

Minimum bar for any loop that touches Builder Guild code or the graph. Loops are report-only
(L1) by default; these guardrails gate every step toward autonomy.

## Path / Surface Denylist

A loop must **never** auto-edit these without explicit human approval:

```
# Online enforcement — runs every request; a bad edit ships to all reads
01-context/src/serve.py
01-context/src/abstain.py
01-context/src/ladder.py
01-context/schema/**            # ontology + write semantics
# Calibration & autonomy — code may revoke autonomy, never grant it
03-evals/src/cal*.py
03-evals/**/CALIBRATED*
# Secrets / infra
.env
.env.*
**/*_key*
**/*_secret*
01-context/docker-compose.yml   # ports / creds / volumes
```

Encode in any implementer / fix skill: *do not modify denylist files; escalate to human with context.*

## Auto-Merge Policy

**Default: no auto-merge.** Builder Guild is a public AGPL repo with hard invariants; a weak
verifier must not be able to ship behavior changes.

| Allowed (with verifier) | Never auto |
|---|---|
| Typo in comment / docs | Any `01-context` enforcement change |
| Lint / format in test files only | Any `03-evals` calibration change |
| Doc-only edits in allowlisted `docs/` | Schema / `relations.yaml` |
| | Dependency / lockfile bumps |
| | Anything on the denylist |

## Invariant Gates (Builder Guild specific)

Escalate to a human for any change that could:
- let an LLM write a fact (vs deterministic ETL),
- weaken namespace isolation (node or edge),
- break bi-temporal as-of semantics,
- grant `CALIBRATED[role] = True` (autonomy is founder-gated, not loop-grantable).

## MCP Connector Least Privilege

| Connector | Read | Write |
|---|---|---|
| GitHub | issues, PRs, checks, CI | comment, label — **not merge** |
| Neo4j | — | **no loop writes to the graph** (ETL is human-run / deterministic) |

## Human Gates (always)

Security / auth · the graph write path · calibration / autonomy · schema · namespace isolation ·
changes touching >10 files · third failed attempt on the same item.

## Kill Switch

`loop-pause-all` label or a flag in STATE.md High Priority. Resume only after a human clears it.

## Pre-Flight (before L3 / unattended)

- [ ] Denylist encoded in skills
- [ ] Auto-merge off (or strict allowlist)
- [ ] Connector scopes reviewed (GitHub read + comment; no graph writes)
- [ ] Human gates documented (above)
- [ ] Kill switch documented
- [ ] A **real** loop run logged in `loop-run-log.md` (not a heuristic activity match)
