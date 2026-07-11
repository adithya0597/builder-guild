# Builder Guild — Documentation

Builder Guild is a **graph-primary, bi-temporal, role-scoped knowledge base** for AI agents. Facts live as typed, time-stamped edges in Neo4j — never as free text an LLM can rewrite — and every read runs through a trust gate that returns an answer *or abstains* rather than guessing. The design bet: for organizational memory, a deterministic graph you can audit beats a vector store you can only sample.

This directory is the navigable reference for the whole project. Each doc below is grounded in source (every substantive claim cites a `file:function`) and cross-links to the deeper design docs that live beside the code.

## Start here

New to the codebase? Read in this order:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — the mental model: the three layers, the data model (bi-temporal edges, the three kinds of truth, namespace isolation, the `relations.yaml` typed contract), the design principles, and the end-to-end data flow. Read this first; the others link back into it.
2. **[INGEST_AND_WRITE_PATH.md](INGEST_AND_WRITE_PATH.md)** — how facts get *into* the graph deterministically: ETL, `apply_edge` (the sole edge writer), the staging truth-gate for LLM-proposed facts, and the guards that keep the invariant.
3. **[RETRIEVAL_AND_SERVE.md](RETRIEVAL_AND_SERVE.md)** — how a query becomes an answer: the retrieval rungs, RRF fusion + rerank, evidence composition, the corrective-RAG loop, and the `serve()` response contract.
4. **[AGENTS_AND_MCP.md](AGENTS_AND_MCP.md)** — the agent layer and the external surface: the agentic planner loop and the MCP servers. Agents **read and suggest only** — they never write facts.
5. **[EVALS_AND_TRUST.md](EVALS_AND_TRUST.md)** — the evaluation and trust track: calibration, the abstain/autonomy gate, golden sets, judges, and the calibration case study. This is where "should the system be trusted to act on its own?" is answered — and today the honest answer is *not yet*.

Plus **[ROADMAP.md](ROADMAP.md)** — capability goals (G1/G2/G3) and their current gate state.

## The three layers

| Layer | Dir | Role |
|---|---|---|
| Context + Retrieval | `01-context/` | The graph, the deterministic write path, and hybrid retrieval → `serve()` |
| Agents | `02-agents/` | The agentic planner + the read-only / suggest-only MCP surface |
| AI Evaluation | `03-evals/` | Calibration, golden sets, judges, and the trust gate that decides abstain-vs-act |

A safety rule runs through all three: **online enforcement never mixes with offline evaluation as a live decision signal** (see `README.md` at the repo root).

## Getting started (local dev)

```bash
# 1. Neo4j (local dev). Connection is env-driven; the default is a local-dev credential.
#    NEO4J_URI defaults to bolt://localhost:7688 (see 01-context/src/serve.py).

# 2. Python env + core deps
python -m venv 01-context/.venv && 01-context/.venv/bin/pip install -r requirements.txt

# 3. Apply the schema (constraints, indexes, topology) then seed the demo graph
#    schema files: 01-context/schema/*.cypher
01-context/.venv/bin/python tools/apply_cypher.py 01-context/schema/01_constraints.cypher 01-context/schema/03_indexes.cypher  # prints APPLY_CYPHER_OK
01-context/.venv/bin/python 01-context/src/etl.py            # builds the canonical spine (prints D1_SPINE_OK)
01-context/.venv/bin/python 01-context/src/demo_seed.py      # embeds the demo seed (prints DEMO_SEED_OK)

# 4. Serve a query
01-context/.venv/bin/python 01-context/src/serve.py demo     # prints INT3_OK
```

Every module carries a `demo`/`--selftest` that prints an `*_OK` token — these double as the CI gates (see `.github/workflows/ci.yml`). The evals need the embedding model (`sentence-transformers`, see `requirements-dev.txt`); calibration extras are founder-gated.

## Current state — honest

- **G1 (agentic RAG)** — **CLOSED.** The `planner.plan()` loop is live and agent-callable via MCP.
- **G2 (multimodal / OCR)** — **PARTIAL.** OCR documents are embedded at ingest (`etl.ingest_ocr_doc` → `embed.embed_node`) and retrievable via `serve()`'s vector rung; see `ROADMAP.md` for remaining scope.
- **G3 (calibration / autonomy)** — **OPEN, founder-gated.** `abstain.CALIBRATED` defaults `False`, so **every decision routes to a human — autonomy is not leased.** The calibration machinery is public; granting trust is a deliberate manual step, and the last measured runs did not clear the bar. This is a *feature*: the gate refuses to certify what it can't yet prove (see `EVALS_AND_TRUST.md` and `03-evals/CASE_STUDY_calibration.md`).

## Conventions in these docs

- Every non-trivial claim cites the source (`file.py:function`). If you find a doc claim the code doesn't support, it's a bug — the docs are meant to track source exactly (they were codex-reviewed against it).
- "SHIPPED" vs "ROADMAP" is kept distinct. Nothing here claims autonomy works.
- Licensing: dual AGPL-3.0 / commercial (see `DUAL_LICENSE.md`). Contributions require the deterministic-write ground rules in `CONTRIBUTING.md`.
