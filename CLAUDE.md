# Builder Guild — Project Instructions

## What this repo is
Builder Guild is a graph-primary, bi-temporal, role-scoped knowledge base for AI agents, with a calibrated evaluation layer. The hard product boundary is:
- `01-context/` = online context + retrieval + enforcement
- `02-agents/` = agent consumer layer / trust boundary
- `03-evals/` = offline evaluation and calibration

Do not blur those layers. Online enforcement lives in `01-context`. Offline evaluation lives in `03-evals` and must not become a live decision signal.

## Stage (do not overstate — see README status)
- `01-context` runs end-to-end on the synthetic demo graph, with CI gating an import smoke plus the ingest/write engine and invariant sweeps on a real Neo4j.
- `03-evals` has run its first real calibration, which correctly **refused** to certify autonomy.
- `02-agents` is the design + contract + a demo consumer; fleet orchestration is **roadmap**.

Describe no layer as more finished than that.

## Core invariants
- Never let an LLM write a fact.
- Namespace on node and edge.
- Bi-temporal by default.
- No secrets in commits.
- Current truth, role-scoped truth, and temporal truth are separate concepts. Do not collapse them.
- Uncalibrated roles are suggest-only. Do not imply autonomy is leased unless `CALIBRATED[role]` is actually true in code.

## Repo-specific rules
- Facts enter through deterministic writes only (`MERGE` / `MATCH ... SET` style ETL).
- LLM-generated content belongs only in the recall layer, not in entity properties or factual edges.
- Any new node type or relation must carry `namespace` and preserve read isolation.
- Functional edges supersede old truth; additive edges accumulate. Check `01-context/schema/relations.yaml` before changing write semantics.
- If you touch retrieval, preserve honest role separation:
  - keyword = exact IDs / names
  - graph = structural truth
  - vector = fuzzy recall
- If you touch serving, preserve the abstain / execution boundary. Passing the gate is not enough when the role is uncalibrated.

## What to read first by task
- For overall product and status: `README.md`
- For invariants and contribution constraints: `CONTRIBUTING.md`
- For near/mid/later priorities: `docs/ROADMAP.md`
- For schema and write semantics: `01-context/ONTOLOGY_SCHEMA.md`, `01-context/schema/relations.yaml`
- For retrieval design: `01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md`, `01-context/RETRIEVAL.md`, `01-context/PAGEINDEX_PILOT.md`
- For agent trust boundary: `02-agents/AGENT_ARCHITECTURE.md`
- For calibration status and why autonomy is still blocked: `03-evals/CASE_STUDY_calibration.md`, `03-evals/CONTEXT_EVALS.md`

## Engineering expectations
- Keep changes focused and explain why.
- If you touch a write path, verify determinism and idempotency.
- If you touch isolation, verify subject + edge + object scoping, not just one surface.
- If you touch temporal behavior, verify as-of semantics explicitly.
- If you touch retrieval, preserve namespace safety and disclose fallback behavior honestly.
- If you touch calibration or autonomy, separate mechanism from grant. Code may revoke autonomy; it should not silently grant it.

## Things to avoid
- Do not treat roadmap items as shipped.
- Do not call GraphRAG / Corrective RAG the default live path unless the code path actually proves it.
- Do not add provenance / explainability systems to `01-context` casually; current priority is trust/calibration and temporal evidence.
- Do not move logic from `03-evals` into `01-context` just because it improves scores offline.
- Do not weaken namespace isolation for convenience.

## Testing / verification mindset
Before claiming a change is done:
- run the narrowest relevant proof
- verify the right layer changed
- confirm no invariant was broken
- if behavior is only documented, say that; if it was executed, say what command proved it

## Keep this repo publishable
Public and AGPL-licensed. No secrets (env vars only — see `.env.example`), no personal or operator notes, no cross-project context. Durable project guidance only.
