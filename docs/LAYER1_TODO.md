# LAYER 1 TODO — context engineering + context management foundation

Date: 2026-06-01. The first working slice of the agent KB: **a queryable, bi-temporal, traceable knowledge graph built from structured company data via the deterministic MATCH engine** — before free-text/PageIndex complexity. Reflects all findings + the codex fixes. Index of the whole layer: **`CONTEXT_LAYER_INDEX.md`**. Source docs: `HYBRID_RETRIEVAL_ARCHITECTURE.md` (PART 0–4 + §3–9), `EVIDENCE_LOG.md`.

**Layer-1 goal:** ingest Paperclip structured state (issues/agents/repos/commits/goals) into Neo4j as a tiered, bi-temporal graph; serve role-scoped, validity-stamped context at read; all mutations deterministic Cypher. Free-text extraction + PageIndex are piloted in parallel but NOT on the Layer-1 critical path.

**Legend:** ⚙️ deterministic (MATCH/MERGE, $0, no LLM) · 🧠 LLM step · 🔬 validate/eval · ⛔ blocked-by.

## A. Substrate
- [ ] **A1** ⚙️ Stand up **Neo4j Community** via Docker (local), volume-persisted. Confirm vector + range + full-text indexes available in Community.
- [ ] **A2** ⚙️ Wire Python client (`neo4j-graphrag-python`) into the Hermes/Paperclip env; smoke-test a write+read.

## B. Ontology schema (PART 0) — the MATCH-engine rules  ⛔A1
- [ ] **B1** ⚙️ Encode tiers as schema: **T0** 6 CXO domains · **T1** sub-domains per CXO (enumerate by charter) · **T2** entity-type labels (`Project/Repo/Decision/Issue/Task/Capability/Agent/Policy/ExternalSource` + `Vote/DecisionRecord`). Node-key uniqueness constraints.
- [ ] **B2** ⚙️ **Declare per-relation rules** (the table that DRIVES the mutation engine): for each relation type → `cardinality` (functional→supersede | additive→MERGE), `temporal` (bi-temporal | static), `contradiction` (structural | semantic). This is the load-bearing artifact — get it right. **Output B1+B2 as `ONTOLOGY_SCHEMA.md`** (the canonical schema doc named in the index).
- [ ] **B3** ⚙️ Create indexes: token-lookup (labels) · **RANGE on `valid_at`/`created_at`** (bi-temporal as-of) · full-text · **vector on the content embedding**.

## C. Node + temporal topology (PART 1 §3 + PART 3, codex-corrected)  ⛔B1
- [ ] **C1** ⚙️ Topology: `:Episodic` (source unit; `created_at`+`valid_at`) · `:Entity` (T2-labelled) · `:RELATES_TO` (bi-temporal fact: `valid_at/invalid_at/created_at/expired_at` + `episodes[]`) · `:MENTIONS` (provenance) · `:NEXT_EPISODE` (timeline).
- [ ] **C2** ⚙️ Node props: `short_context` · **`long_context` = FACT-FREE content abstract** (codex fix — facts are edges, NOT baked in) · `chunks[]` · `chunk_count` · freshness stamps (`embedded_at`/`embedding_model`/`content_rev`/`dirty`) · **`pageindex_ref`/`tree_built_at` on long-doc node types only** (handle to that node's PageIndex tree — the graph↔RAG seam; structured nodes get none).

## D. Context engineering — ingest (build)
- [ ] **D1** ⚙️ **Structured ETL FIRST (the $0 spine):** Paperclip API → `MERGE` entities (keyed) + `MATCH…SET` edges, per B2 rules. No LLM, no extraction, no PageIndex. Proves the whole spine cheaply. ⛔C1,B2
- [ ] **D2** ⚙️ Provenance on every write: create/attach `:Episodic` + `:MENTIONS` + `episodes[]` on facts.
- [ ] **D3** ⚙️ Embed **intrinsic content** (EmbeddingGemma-300M local, $0) → content vector (0-hop). Dual chunking (prose=contextual, code=AST) → `chunks[]`. ⛔C2
- [ ] **D4** 🧠 Free-text extraction (LLM → typed triples) → MERGE entities + facts. **After D1** (not Layer-1-critical). ⛔D1
- [ ] **D5** ⚙️ Write-time dedup (exact + semantic); measure recall effect.

## E. MATCH mutation engine (PART 3-D)  ⛔B2,C1
- [ ] **E1** ⚙️ Parameterized Cypher per relation rule: **resolve** (MERGE on canonical key) · **supersede** (MATCH+SET on functional) · **dirty-flag** (on content edit).
- [ ] **E2** ⚙️ **Episode re-ingest / doc-edit path → negative-delta retraction** (MATCH on `episodes[]`, drop source, tombstone if orphaned). Closes the Graphiti editable-doc gap. (For free-text, downstream of D4's re-extraction.)

## F. Context management — serve (PART 2)  ⛔C1,B3
- [ ] **F1** ⚙️ **Node-card assembly at READ** = `long_context` + **live** bi-temporal edge query (always current; nothing fact-inclusive cached). Codex-correct design.
- [ ] **F2** ⚙️ Retrieval ladder: **graph index = default** (structural, instant) → vector (semantic) → PageIndex (deferred, see H1). Eval-gated escalation. **Graph↔RAG seam:** graph/vector select the node; PageIndex drills into that one node's tree via `pageindex_ref` (long-doc nodes only) — PageIndex never scans the corpus, the graph scopes it. Returned sections → evidence schema → validity/freshness flags propagate from the node.
- [ ] **F3** ⚙️ 2-D scoping: role-axis (CXO namespace slice) × query-axis; per-role token budget; iteration cap **start T=3, tune** (NOT a proven optimum).
- [ ] **F4** ⚙️ Retrieval-time stamping: every item `{validity: current|historical|superseded, fresh: clean|dirty}`; freshness judge drops superseded; **action gate refuses to act on stale/superseded** (ties to APC gate).

## G. Freshness lifecycle (PART 3-B/C)  ⛔E1
- [ ] **G1** ⚙️ Dirty-on-content-edit → **lazy re-embed sweep** (Grunt-tier model); 0-hop, batched.
- [ ] **G2** ⚙️/🧠 Cascading cases lazy + query-frequency-prioritized: entity **merge/split** + community refresh (deferred until communities are introduced).

## H. Validation (parallel, not blocking the spine)
- [ ] **H1** 🔬 **PageIndex pilot** (`PAGEINDEX_PILOT.md`) — standalone, 1 long doc, decide if it joins F2. Runnable now; do NOT run folder-wide.
- [x] **H2a** 🔬 **`CONTEXT_EVALS.md` WRITTEN (2026-06-02, 3-research-stream grounded)** — the eval methodology: 11-dimension matrix + §2 calibration table (HOW each provisional param is set) + the LLM-judge debiasing mandate + tooling map (Langfuse = online seam) + golden-set spec + honest gaps + DoD. Thesis: **relevance ≠ answer quality** (eRAG τ 0.505 vs 0.179) → sufficiency+faithfulness gate, not relevance. The doc specifies the method; H2b runs it.
- [ ] **H2b** 🔬 **RUN the calibration** (the numbers, not the doc): per-CXO golden sets (RAGAS TestsetGen) → **eRAG** source weights (query-type-conditional) → **sufficiency×confidence** abstain threshold (never sufficiency alone) → drift-τ via context-perplexity → baseline-relative gates (precision/recall/faithfulness ~80% band/isolation=0/conflict) → all judge-gates with position-swap + length-control + ≥25 trials. Per `CONTEXT_EVALS.md §7 DoD`. ⛔D1,F2
- [ ] **H3** 🔬 Phase A instrument (schema + scoring logs, no behavior change) → Phase B dual-run (current vs KB) → set H2's gate numbers.

## Critical path (do in this order)
**A1 → A2 → B1 → B2 → B3 → C1 → C2 → D1 (the $0 structured spine works here) → D2/D3 → E1 → F1 → F2(graph+vector) → F3 → F4.**
Everything LLM (D4) or unbounded (G2 communities, PageIndex H1) is deferred past the spine. **D1 is the milestone**: a queryable, bi-temporal, role-scoped KB from structured company data, all deterministic, $0 — proves Layer 1 before any extraction/PageIndex cost.

## Open decisions to resolve during Layer 1
- B2 relation-rule trichotomy (functional/additive/semantic) — does every relation fit cleanly? (codex flagged; resolve per-relation during B2.)
- τ (embedding-drift threshold) + T-cap — set empirically in H2b (method now specified in `CONTEXT_EVALS.md §2`: τ via context-perplexity/FLARE θ=0.8; T≈3 as a hard ceiling since per-query complexity-routers are only 0.31–0.66 accurate), not assumed.
- Whether communities (and thus G2/cascading refresh) are needed at all at Layer-1 scale — likely defer.
