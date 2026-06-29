# AGENTS.md — Builder Guild

Conventions for humans and loops working in this repository. See also `README.md` (product +
status), `CONTRIBUTING.md` (invariants), and `LOOP.md` (how loops operate here).

## What this repo is

Graph-primary, bi-temporal, role-scoped knowledge base for AI agents, with a calibrated
evaluation layer. Hard layer boundary — do not blur:
- `01-context/` = online context + retrieval + **enforcement** (runs every request)
- `02-agents/` = agent consumer layer / trust boundary
- `03-evals/` = **offline** evaluation + calibration (never wired as a live decision signal)

## Core invariants (never violate)

- Never let an LLM write a fact. Facts enter via deterministic `MERGE` / `MATCH … SET` ETL only.
- Namespace on node **and** edge; preserve read isolation.
- Bi-temporal by default (`valid_at` / `invalid_at`); functional edges supersede, additive accumulate.
- Uncalibrated roles are suggest-only. Do not imply autonomy is leased unless `CALIBRATED[role]` is true in code.
- No secrets in commits (env vars only; the repo ships only a local-dev Neo4j password).

## Build & verify

```bash
cd 01-context && docker compose up -d        # Neo4j (community)
bash setup_a2.sh                             # venv + driver + smoke
pip install -r requirements.txt -r requirements-dev.txt
python 01-context/smoke_test.py              # fastest write/read sanity
```

No single application test suite; quality gates are per-layer (invariant sweep, recall
selftest, abstain contract — see `.github/workflows/ci.yml`).

## Review norms (loops and humans)

- Keep changes focused; explain the *why*.
- Touch a write path → verify determinism + idempotency (same input twice = same graph).
- Touch isolation → verify subject + edge + object scoping, not just one surface.
- Touch temporal behavior → verify as-of semantics explicitly.
- Touch calibration / autonomy → separate mechanism from grant; code may revoke, never silently grant.
- If behavior is only documented, say so; if executed, say what command proved it.

## Loop operation (this repo)

- Daily triage: `loop-triage` skill → `STATE.md` (report-only, L1).
- Assisted fixes (L2): `loop-verifier` agent (maker/checker, default REJECT) + isolated worktree; PR with human review.
- Never auto-merge to denylist paths (`docs/safety.md`). No loop touches `01-context` enforcement or `03-evals` calibration without a human gate.
