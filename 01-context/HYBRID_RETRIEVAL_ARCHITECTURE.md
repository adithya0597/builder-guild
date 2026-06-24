# HYBRID_RETRIEVAL_ARCHITECTURE.md

Date: 2026-06-01 (rev 4 — graph-primary substrate; tiered company ontology; APC-derived decision/challenge layer)
Owner: Bala Adithya
Scope: **the agent-fleet infrastructure only.** The knowledge base ("company brain") the agent army builds, manages, retrieves from. NOT a personal note system. **Zero the-personal-store primitives** by lock. Only the FEA *pattern* + shared evidence base carry over.

Companions: `MODEL_ROUTING.md` (which model + coupling), `RETRIEVAL.md` (retrieval levers + grounded numbers).

> **Stance: multi-method retrieval over ONE property-graph substrate, eval-gated, with a hard faithfulness+action gate — NOT one "smart retriever" and NOT six co-equal legs.** The graph is primary; sparse/dense/reasoning are index types + a reasoning layer *on the graph nodes*.

## Validation provenance (rev 2 → 3 → 4)
- rev 3: 3-expert Opus panel (IR-math / DL-retrieval / context-eng) — fixed RRF, code-aware chunking, ontology, 2-D routing, abstain→action gate, eval rigor.
- **rev 4** (user architecture corrections, 2 grounded research streams): (a) **graph-primary single store** replaces the 6-leg model — graph index is the instant deterministic default, vector + PageIndex layer over node-properties, eval-gated (Case 3); (b) **tiered static company ontology** replaces flat anchors (Case 1); (c) **APC-derived scoring / final-say / challenge layer** added to the faithfulness gate (Case 2, real tested code in `ai-product-council`); (d) context-eval methodology flagged as active research (Case 4).
- **rev 4 paper-walk (6-agent verifier panel, results-table level):** corrected wrong numbers (BRIGHT, CRAG, GraphRAG win-rates, PageIndex baseline), downgraded **T=3 from "measured peak" → "estimated default"**, flagged **GraphRAG (LLM-built/sensemaking) ≠ our hand-defined ontology**, **PageIndex 98.7% = vendor self-report (unproven)**, and **graph-memory loses to flat-vector on simple recall**. The structure survived; the *evidence labels* are now honest. See per-doc inline `[paper-walked]` tags.

## Goal
A working "company brain" KB via **context engineering** (ingest → tiered ontology → node-property chunking → index) + **context management** (role×query-scoped slice under a token budget), retrieved through a graph-primary hybrid, gated by an APC-style decision layer.

---

## PART 0 — The tiered company ontology (Case 1: static, define-don't-discover)

Generic edges don't manage company use-cases; a real ontology does. Built **top-down, human-defined, small + stable** (FEA discipline). Tiers = node-label levels in the graph; roll-up/drill-down is a graph-index traversal (instant, no LLM).

| Tier | What | Static? | Source |
|---|---|---|---|
| **T0 Domains** | Engineering · Product · Finance · Market/GTM · Operations · Governance/Risk | static | = your CXO org (the army you hired) — the fishbone, already defined |
| **T1 Sub-domains** | per-domain, e.g. Engineering→{Architecture, Repos, Infra, Releases, Incidents}; Finance→{Budget, Revenue, Costs, Runway} | static | manually enumerated per CXO charter; mirrors APC per-role `artifacts` + 5 stages |
| **T2 Entity types** (node labels) | `Project · Repo · Decision · Issue · Task/Action · Capability · Agent/Role · Policy · ExternalSource` + governance types `Vote · DecisionRecord · ForceEntryCondition` (borrowed from APC `types.ts`) | static schema | the 9 anchors + APC governance entities |
| **T3 Instances** | actual nodes (this repo, this decision, this task) | **dynamic** | auto-attach: FEA cosine to nearest T2 type, then fixed edges roll up T3→T2→T1→T0 |

**How to get it (construction):** define T0 from the org chart (done — 6 CXO domains), enumerate T1 by hand per CXO (small, stable), fix T2 as the node-label schema, then let T3 grow by cosine-anchoring + graph edges. Tiering does NOT break FEA determinism: an instance anchors to its T2 type by cosine, and the T2→T1→T0 roll-up is fixed graph edges resolved by the graph index — no per-doc LLM call. Keep T0–T2 small; only T3 grows.

### Node-type rationale + why tiered = traceable
Two orthogonal structures combine: the **tier hierarchy** (T0–T3, classification) and the **temporal topology** (Episodic/Entity/fact, PART 3). Each element earns its place:

| Element | Why it exists | What breaks without it | Trace role |
|---|---|---|---|
| `:Episodic` | source unit = "what we ingested + when" | no provenance, no event-time, no replay/audit | **bottom of every trace** — fact → source doc/commit/author |
| `:Entity` (T2-labelled) | stable identity while facts churn (version-the-edge needs an anchor) | forced into heavier whole-node snapshots; lose the classification pivot | **classification pivot** — entity → T2 → T1 → T0 |
| `:RELATES_TO` (fact, bi-temporal) | the unit of truth AND change; validity windows live here | no as-of, no supersession, no "what changed" | **the claim being traced** (carries `valid_at` + `episodes[]`) |
| `:MENTIONS` | graph-traversable provenance (episode→entity) | provenance trapped in an array property, not walkable | provenance traversal |
| `:NEXT_EPISODE` | ordered timeline | no "events between T1–T2 in order" | temporal trace |

**Why tiered specifically improves tracing:** each tier is a NAMED, queryable boundary, so a trace runs both directions at any granularity — **UP** (accountability): fact → entity → T2 → T1 → **T0 domain = which CXO owns it**; **DOWN** (provenance): fact → `:MENTIONS` → `:Episodic` → source. Scoped queries become trivial: "all Engineering-domain facts" (T0), "Architecture decisions as-of March" (T1+T2+bi-temporal), "this decision's full supersession history" (T3 + invalidated edges). A *flat* graph CAN scope traces given enough labels + indexes (codex: it's not impossible) — but tiers make it **native and cheap**: each level is a ready-made boundary, so roll-up/drill-down is a fixed traversal instead of an ad-hoc hand-crafted query, and accountability ("which CXO owns this") is one hop up rather than inferred. Tiers also align the blast radius (PART 3-C): a refresh/community set ≈ a T1 sub-domain, so lazy recompute is tier-bounded. **So: keep it tiered — not because flat can't trace, but because tiers make tracing the default, not a query you must engineer each time.**

---

## PART 1 — Context engineering (build the KB)
1. **Ingest** — capture provenance at write: path, commit/URL, author-agent, timestamp, namespace.
2. **Ontology-anchor** — cosine the doc to its nearest T2 type (PART 0); create the T3 node, wire fixed roll-up edges.
3. **Node-property schema** — description tier + content tier are DISTINCT:
   - **short_context** — short description: title, type, 1-line "what this node is about". → graph index + cheapest context injection.
   - **long_context** — *longer description*: a fuller summary/abstract of the node (more than short; still a description, **NOT** the raw chunks). → node-level vector recall (embed this) + mid-tier injection. **PageIndex does NOT use `long_context`** — it builds its own ToC tree over `chunks`/source doc via `pageindex_ref` (PART 2). [residual fix, post-the agent fleet-review]
   - **chunks** — *separate* property holding the actual source content: a **single chunk** if the node fit one, or a **group of N chunks** if split (`chunk_count`). → fine-grained retrieval target (chunk-level vector / PageIndex leaves). Single-chunk → return directly; multi-chunk → vector/PageIndex *within* the group.
   - **temporal (BI-TEMPORAL, on facts/edges + node validity)** — `valid_at`/`invalid_at` (**event time**: when the fact became true / stopped being true *in the world*) + `created_at`/`expired_at` (**transaction time**: when *we* ingested / retracted it). Graphiti's exact 4-field model (arxiv 2501.13956 + `graphiti_core/edges.py`, paper-walked); = the canonical SQL:2011 bitemporal pattern. → **"as-of T"** = range filter `valid_at ≤ T AND invalid_at > T` (SENTINEL contract: a current edge's invalid_at = 9999-12-31, so no NULL branch) on the graph range-index — instant, no LLM. **Supersession = invalidate-don't-delete**: a contradicting fact sets the old edge's `invalid_at = new.valid_at` (+ `expired_at = now()`), keeping full history queryable. This REPLACES the bare `source_timestamp` (which captured only transaction time and couldn't answer "valid as-of" or "what superseded what").
   - **freshness stamps (for semantic-drift tracking — PART 3-B)** — `summary_at`, `embedded_at`, `embedding_model`, `dirty:bool`, `fact_rev:int`. The derived artifacts (short/long_context, embedding) are computed at ingest from the node's OWN content and decay only when that content is edited — PART 3-B §3 makes the embedding fact-free/0-hop, so a fact/edge change re-embeds nothing; these stamps let the freshness sweep detect + lazily refresh stale meaning. `dirty` is set when the node's content is edited (`mutate.mark_dirty`), **NOT** when an edge changes (a `:RELATES_TO` add/invalidate touches no node stamp; see PART 3-B §3 + the 0-hop table).
4. **Chunking by source type:** prose/docs → **contextual chunking** (−49% failure, −67% +rerank; Anthropic); code → **AST/symbol-boundary** (never split a function — split-facts failure). Alt to benchmark: **late chunking** (Jina). Chunks land in `chunks`; `long_context` remains summary/abstract only.
5. **Embed — two granularities:** (a) embed **long_context** (the description) → node-level vector for coarse "which node" recall; (b) embed **chunks** → chunk-level vector for fine "which passage" recall. EmbeddingGemma-300M local ($0) default; gemini-embedding-001 when quality > cost. Vectors stored **on the node** (single store).
6. **Dedup** at write (exact + semantic); measure effect on recall.

Invariant: **a node is well-formed iff short_context + long_context + provenance + ontology-anchor are populated at ingest.** Chunk-level indexing (chunk-vector/PageIndex) is added per eval need (Case 3 ladder); a single-chunk node may need none.

---

## PART 2 — Context management (serve the right slice)
RCR-Router role-aware routing under token budget (`MODEL_ROUTING.md`, −25–47% tokens). **2-D:**
- **Role axis (who)** — each CXO gets only its namespace + role slice (CTO→eng/arch/repo; CFO→company/finance). Scoped-context-handoff coupling.
- **Query axis (what)** — the retrieval-method ladder below.
- **Per-role token budget** (provisional, calibrate Phase B): role-slice ≤40% / retrieved-evidence ≤40% / scratch ≤20%.
- **Iteration cap = 3** (RCR-Router *default*, NOT a measured optimum — paper-walk: only T=3 was actually run, neighbors estimated; the paper's real claim is "3–4 / K=3 suffices" on 3-hop QA. Use 3 as a starting cap; let the eval track tune it per query-class — don't treat it as a law).

### Retrieval = ONE property-graph store, 3 methods, eval-gated ladder (Case 3)
Substrate: a **property graph DB** holding structure + FTS + vectors in one store (Neo4j: token-lookup/range/text/vector indexes; or Kuzu: embedded, Cypher, native FTS + disk-HNSW). Single-store hybrid pattern = Neo4j GraphRAG / LlamaIndex `PropertyGraphIndex` (both doc-read; `ImplicitPathExtractor` needs no LLM).
> **⚠ Grounding caveat (paper-walk):** Microsoft GraphRAG's 72–83% comprehensiveness win is for an **LLM-BUILT entity graph + LLM-pregenerated community summaries**, on **global sensemaking** queries, with an expensive full-corpus LLM index pass. Our substrate is a **hand-defined tiered ontology** (PART 0) — a *different artifact*. Cite GraphRAG for "a graph layer helps global/multi-hop synthesis," **NOT** for "a hand-authored ontology graph beats vector RAG" (unproven). The graph-primary case rests on **determinism + instant structural indexing + cost** (Neo4j/Kuzu index docs), not on GraphRAG's win-rates.

| Method | Binds to | Fires when | Cost | Grounding |
|---|---|---|---|---|
| **1. Graph index** (label/property/range/FTS) | `short_context` + structure | **structural** query — match by type/property/relationship/keyword ("Decisions linked to CTO", "Tasks blocking Issue X", exact IDs/paths) | **instant, no LLM, no embeddings** | Neo4j token-lookup default; `ImplicitPathExtractor` no LLM (LlamaIndex) |
| **2a. Node-vector** (coarse) | `long_context` descriptions | "which node" — fuzzy fan-out to candidate nodes, no clean graph pattern | HNSW, cheap | Neo4j `CREATE VECTOR INDEX … ON (n.embedding)`; Kuzu vector ext |
| **2b. Chunk-vector** (fine) | `chunks` (multi-chunk nodes) | "which passage" inside candidate nodes; single-chunk node → skip, return directly | HNSW, cheap | same |
| **3. PageIndex** | uses `pageindex_ref` to navigate its own ToC/section tree over the node's source doc / `chunks` | node holds a **long structured doc**; reasoning where similarity ≠ relevance | LLM per tree-nav — high-value, low-QPS only | vectorless reasoning-tree (mechanism confirmed); 98.7% FinanceBench is **vendor self-reported** — see ⚠ below |

**Default = graph index.** It is the instant deterministic path — this replaces the old "LLM decides retrieve-or-not." Escalate to vector, then PageIndex, **only for query classes where the eval gate (§4 below) shows graph-index-alone underperforms** ("create a new index if the evals for that case don't work"). Realistic enterprise query uses all three: graph index prunes structurally (instant) → vector fans out to candidate passages → PageIndex reasons inside each long node.

> **⚠ PageIndex evidence (paper-walk, treat as promising-but-unproven):** the *mechanism* (vectorless reasoning-tree over a ToC) is confirmed; the **98.7% FinanceBench is a vendor (Vectify) self-scored result and exceeds even the paper's 85% oracle** ceiling — a tell that it's not apples-to-apples (Vectify re-annotates contested answers + runs newer base models than the 2023 paper). The *defensible* primary-source baselines on the same 150-case set: **vector RAG 19% (shared store, realistic) → 50% (single-store); long-context 76–79%; oracle 85%** (FinanceBench, arxiv 2311.11944, paper-walked). So the sound claim is **"tree-RAG ≫ naive vector store for long filings" (19% is genuinely poor)** — adopt PageIndex on that basis, NOT on the exact 98.7% figure. Pilot it on our own long-doc nodes before trusting it.

**How PageIndex connects to the graph (the seam):** PageIndex is NOT a competing RAG — it's the **deep in-doc reader, scoped by the graph**. Roles meet at the node: graph/MATCH = router (*which* node), vector = coarse matcher, PageIndex = *which passage inside* a selected long-doc node.
- **Connection handle:** a long-doc node carries `pageindex_ref` (tree id/path) + `tree_built_at`. PageIndex builds its **own** ToC tree (its own per-section summaries) over the node's **full source doc** (`chunks[]`/source file) — NOT over our `long_context` (which post-codex-fix is the short fact-free *abstract*, the vector-recall target). No naming collision: `long_context`→vector; `chunks[]`+`pageindex_ref`→PageIndex.
- **Flow:** graph index/vector locate the node(s) → if a node is a long structured doc AND the query needs in-doc reasoning, drill via its PageIndex tree → returned sections become evidence (page/section refs → evidence schema `source_path`/`chunk_span` → trace to `:Episodic`). PageIndex never scans the corpus — the graph scopes it to one node.
- **Split:** relational facts (edges) = graph/MATCH, PageIndex never touches them; in-document prose = PageIndex. A both-query: graph resolves entities + current bi-temporal facts, PageIndex reads the doc section, fusion merges.
- **Freshness:** the tree is just another per-node derived artifact → surgical rebuild only when that node's doc content changes (`tree_built_at < content_rev` → dirty → rebuild; blast radius = 1 doc). A `superseded`/`dirty` node propagates the flag to its PageIndex results — the action gate still refuses to act on a section from a stale doc.
- **Scope:** only **long-doc node types** get a tree (design docs/runbooks/long markdown). Structured nodes (issues/agents/repos — short, keyed) are pure graph/MATCH, no tree. PageIndex is a **pluggable top rung gated by the pilot** — pass → method 3 on long-doc nodes; tie/lose → chunk-vector covers them. Either way the Layer-1 graph spine is unchanged.

### Query router (which methods per class)
Retrieve path resolves first to a **graph pattern**; if it does → method 1 only. Else:
- **Factual/known-item** → graph FTS + vector → rerank (MRR metric).
- **Reasoning/multi-hop** → **CoT decompose** → per-sub-question: graph traversal + vector → **CRAG evaluator** (re-search low-`retrieval_score`) → aggregate → rerank. (Cosine alone 18.3 nDCG on reasoning; CoT lifts BM25 14.8→26.5 — BRIGHT; CRAG +7–36.6%.)
- **Long-doc reasoning** → graph locates the node → **PageIndex** via `pageindex_ref` over that node's source doc / `chunks`.
- **Sensitive/cross-namespace** → policy filter first, then scoped above.

## PART 3 — Temporal nodes/edges + validity & freshness lifecycle
*How we know retrieved context is still valid.* Two distinct kinds of change must be tracked: **(A) truth change** — a fact gets contradicted/superseded (bi-temporal, Graphiti-grounded); **(B) semantic drift** — the node's *meaning* (summary/embedding) goes stale as new context accrues, even if the underlying fact didn't flip (design-synthesis). Retrieval must stamp BOTH on every evidence item, and the action gate must refuse to act on stale/invalid context.

### Topology (Graphiti-confirmed, source-read `nodes.py`/`edges.py`)
| Element | Label / type | Temporal fields | Role |
|---|---|---|---|
| Episode node | `:Episodic` | `created_at` (txn), `valid_at` (event time of the raw unit) | timestamped ingestion unit (a doc/message/commit) |
| Entity node | `:Entity` (+ T2 ontology label) | `created_at`, **+ derived-artifact stamps (B)** | the thing itself (stable identity) |
| **Fact edge** | `(:Entity)-[:RELATES_TO]->(:Entity)` | **`valid_at`/`invalid_at` (event) + `created_at`/`expired_at` (txn)** | the bi-temporal fact — the ONLY element carrying the full 4-field pair |
| Provenance | `(:Episodic)-[:MENTIONS]->(:Entity)` + fact `.episodes[]` | `created_at` | which episode a fact came from + when observed |
| Sequence | `(:Episodic)-[:NEXT_EPISODE]->(:Episodic)` | `created_at` | timeline adjacency |

**Versioning = version the EDGE, not the node** (Graphiti): on contradiction, the old fact edge is invalidated *in place* (`invalid_at = new.valid_at`, `expired_at = now()`) and **kept**; a new edge is added. Our change-grain is the fact/relationship, so edge-validity beats node-snapshots (lighter, native `WHERE valid_at <= T < invalid_at`).

### (A) Validity lifecycle — truth change [Graphiti-grounded]
- **On ingest:** new episode → resolve entities → extract candidate facts → **contradiction-detect** against existing CURRENT edges (same subject+relation) → invalidate superseded (set `invalid_at`+`expired_at`, keep for history) → add new edge.
- **At retrieval:** every fact stamped `validity ∈ {current (invalid_at > now, sentinel-stamped), historical (invalid_at <= now), as-of-T}`. Default queries return CURRENT only; "as-of T" and "what changed" use the bi-temporal filter (Cypher below).

### (B) Freshness lifecycle — semantic drift [design-synthesis; revised after adversarial review]
*As new context accrues, a node's meaning can drift.* **Resolution (fixes the embedding-hop-count contradiction the codex pass caught): split the STABLE semantic layer from the VOLATILE relational layer, so the embedding is genuinely 0-hop and a whole staleness class disappears:**
- **Embed intrinsic content ONLY.** `long_context` = a **fact-free** abstract of the node's own text; relational facts are NOT baked into it — they live as `:RELATES_TO` edges. So the content embedding depends on the node's own text alone → a fact/edge change does NOT touch it (genuinely 0-hop).
- **Assemble the node-card at READ time** = `long_context` (stable) + current valid facts pulled **live** from edges (bi-temporal as-of). Because facts are queried live, the injected context is always current — **there is no stored fact-inclusive summary to go stale** (removes the prior draft's summary-vs-facts staleness entirely).
- **Version stamps** (`embedded_at`, `embedding_model`, `content_rev`, `dirty`): `dirty=true` is set when the node's **content is edited** — NOT when an edge changes.
- **Drift checks (on content-changed/dirty nodes; batched/lazy, never block ingest):**
  1. **Embedding drift** — re-embed current content; cosine vs stored `< τ` → refresh.
  2. **Entity-resolution drift** — merge (two nodes co-refer) / split (one conflates two); re-run on dirty clusters. NOTE: this is a *cascading* case (it reassigns facts across nodes) — see (C).
- **Lazy recompute** on the Grunt-tier model.

### (C) Surgical refresh — the blast radius IS bounded [IVM-grounded]
The worry "you never know what connection could be made → must recompute everything" is **false for recompute**, because each derived artifact has a shallow, explicit dependency. Treat artifacts as **materialized views** (Incremental View Maintenance / DBSP / Differential Dataflow) and recompute only the delta:

| Artifact | Depends on | Blast radius | Recompute trigger |
|---|---|---|---|
| **node embedding** | **intrinsic content ONLY** (facts are edges, NOT in the vector) | **0-hop** | content edit. Fact/edge change → re-embed NOTHING. (content embeddings; GNN embeddings would be L-hop) |
| **node-card (injection)** | content + **live** edge query | **not stored → never stale** | assembled at read; facts pulled current |
| **community summary** | the member SET | community-bounded → global on re-cluster | membership change; drift-threshold trip |
| **entity merge/split** | a resolved cluster | **cascading** (reassigns facts across nodes) | entity-resolution drift |
| **new-edge discovery** | top-k k-NN candidates, NOT all nodes | bounds **COST** to O(k) | new content arrives |
| **PageIndex tree** (long-doc nodes only) | that node's source-doc content | **1 doc** | doc content edit (`tree_built_at < content_rev`) — rebuild that tree, never the folder |

**The rule (given a change):** edge/fact change → **0 re-embeds** (facts aren't in the vector) and the node-card is assembled live, so it's already current; content edit → re-embed that node (0-hop) + the next read re-assembles its card. New content discovers edges only against its top-k ANN candidates (Graphiti: `NODE_DEDUP_CANDIDATE_LIMIT=15`, `COSINE_MIN_SCORE=0.6` — source-confirmed, NOT all-pairs). Grounded: Graphiti re-embeds only resolved nodes (never neighbors); InkStream's L-hop dirty-set result is for **GNN** embeddings (arXiv:2309.11071 — a GNN-inference paper; cite ONLY for the GNN case, our content-embeddings are 0-hop); IVM/DBSP (arXiv:2203.16684) is the canonical frame.
**Two cascading cases escape 1-hop** (the "ONLY communities" claim was wrong — codex caught it): (1) **community/cluster summaries** (set-membership → global re-cluster); (2) **entity merge/split** (reassigns facts across nodes). Both handled the one lazy way: recompute only the changed set, defer global re-cluster to a drift threshold, batch, **prioritize the refresh queue by query-frequency** (hot first; cold stay stale until read).
**Recall caveat (codex):** the k-NN gate bounds *cost* to O(k) but trades *recall* — a true connection outside the top-k candidate set is **missed, not saved**. Tune k / candidate retrieval (hybrid cosine+FTS) for recall on the discovery path; this is a quality knob, not a free lunch.

### (D) MATCH-driven mutation layer — confine the LLM to extraction; everything else is Cypher
Graphiti is **contradiction-only + first-source remove** (source-read `graphiti.py`/`edge_operations.py`): `add_episode` never re-diffs an episode against what it previously produced, so **an edited doc that silently drops a fact leaves a stale CURRENT edge**. Fine for immutable chat messages (Graphiti's target), insufficient for **editable docs** (ours). Fix + principle: **decompose every mutation into LLM-needed vs MATCH-able — almost all of it is MATCH** (FEA applied to updates).

| Operation | LLM or MATCH |
|---|---|
| extract entities/facts from free-text prose | **LLM** — the only irreducible step (prose→typed triples), confined to per-doc ingest, cacheable |
| resolve a **keyed** entity (id/path/name) | **MERGE** on canonical key — deterministic |
| resolve un-keyed free-text entity | LLM/embedding (unless aliases declared) |
| supersede a **functional** relation | **MATCH + SET** by schema rule |
| retract a dropped fact (negative delta) | **MATCH on `episodes[]` + SET** (provenance-diff) |
| dirty-flag · roll-up edges · as-of/timeline | **MATCH** |
| semantic contradiction of free-text facts | LLM (only mutation-time LLM case) |

**Unlock — declare per-relation rules in the ontology (T2):** each relation type carries `cardinality` (functional→supersede | additive→MERGE) + `temporal` (bi-temporal | static) + `contradiction` (structural | semantic). The whole mutation layer becomes a fixed set of parameterized Cypher driven by these rules — deterministic, instant, reproducible, $0.
- **Structured company data (tracker issues/agents/repos/commits/goals) → ≈100% MATCH, zero LLM** for already-keyed/typed fields (pure `MERGE`/`MATCH…SET` ETL). Edge cases that still need light deterministic logic or a one-off pass: entity normalization (alias/casing), relation inference from semi-structured free-text fields (an issue *body*), and schema drift when the API adds fields. So "zero LLM" holds for the keyed core, not every byte.
- **Free-text docs → LLM only at extraction; resolution/supersession/retraction all MATCH.**

**Negative-delta retraction (editable-doc fix — the retraction is MATCH, but it runs DOWNSTREAM of the re-extraction that produces `$still_supported`; for free-text that extraction is an LLM step, so the end-to-end update is "MATCH given an LLM extraction," not pure Cypher):**
```cypher
// re-ingest doc e: retract facts e used to source but no longer supports
MATCH (s)-[r:RELATES_TO]->(o) WHERE $e IN r.episodes AND NOT r.uuid IN $still_supported
SET r.episodes=[x IN r.episodes WHERE x<>$e]
WITH r WHERE size(r.episodes)=0
SET r.invalid_at=datetime($t), r.expired_at=datetime();   // tombstone, keep history
```
```cypher
// functional supersession — rule-driven, no LLM
MATCH (s {key:$s})-[old:STATUS]->() WHERE old.invalid_at > datetime($t)
SET old.invalid_at=datetime($t), old.expired_at=datetime()
WITH s MERGE (n:Status {key:$new}) MERGE (s)-[:STATUS {valid_at:datetime($t)}]->(n);
```
Bounded: provenance-scoped to `$e`'s footprint; k-NN ≤10 (`RELEVANT_SCHEMA_LIMIT`) for any LLM resolution that does run.

**Honest labels:** Graphiti contradiction-only + first-source = source-read confirmed; DBSP negative-delta/Z-set retraction = doc-read (IVM deletion); MERGE/MATCH-SET capability = known Cypher; the **declarative-cardinality-rule update engine = design-synthesis** (generalizes the "all via MATCH" idea). Irreducible LLM cases: free-text extraction + free-text semantic contradiction. So "entirely MATCH" holds for **structured data**, and "MATCH except a confined per-doc extraction call" for free-text — the most deterministic/cheapest design available, fully FEA-consistent.

### Retrieval-time stamping (ties A+B to the gate)
Every evidence item returns `{validity: current|historical|superseded, fresh: clean|dirty, valid_at, invalid_at, summary_at}`. The **freshness judge** (DAG §6 step 4) drops `superseded` + flags `dirty` (force a refresh-then-reretrieve on dirty-and-load-bearing). The **action gate** (§4) refuses to ACT on `historical/superseded` OR `dirty` context for a categorical action — acting on a stale fact is the exact failure mode this whole part exists to prevent. This is the concrete answer to "is the retrieved context still valid?": **validity (truth) + freshness (meaning) stamped per item, enforced at the gate.**

### Cypher (Neo4j; design-synthesis in Graphiti style — verify against your version)
```cypher
// Supersede (truth change): invalidate old fact in place + add new + mark node dirty
MATCH (s:Entity {uuid:$subj})-[old:RELATES_TO {name:$rel}]->(:Entity)
WHERE old.invalid_at > datetime($t) AND old.expired_at IS NULL
SET old.invalid_at=datetime($t), old.expired_at=datetime()
WITH s MATCH (o:Entity {uuid:$new_obj})
CREATE (s)-[:RELATES_TO {uuid:$f, name:$rel, fact:$fact,
   valid_at:datetime($t), invalid_at:datetime('9999-12-31T00:00:00Z'), created_at:datetime(), expired_at:null}]->(o)
SET s.dirty=true, s.fact_rev=coalesce(s.fact_rev,0)+1, o.dirty=true;

// As-of T (validity): facts true at event-time T
MATCH (s:Entity)-[f:RELATES_TO]->(o:Entity)
WHERE f.valid_at <= datetime($T) AND f.invalid_at > datetime($T)
RETURN s,f,o;

// Freshness sweep: nodes whose meaning may have drifted since last embed
MATCH (e:Entity) WHERE e.dirty = true OR e.embedded_at < e.summary_at
RETURN e.uuid, e.fact_rev ORDER BY e.fact_rev DESC;   // feed to lazy re-embed/re-summary
```

### Honest gaps
- **Graphiti-confirmed:** topology, bi-temporal on `:RELATES_TO`, supersession = invalidate-in-place + add, `:MENTIONS`/`episodes[]` provenance, `:NEXT_EPISODE`.
- **Design-synthesis (mine):** the entire **(B) freshness lifecycle** (version stamps, dirty-flag triggers, 3 drift checks, lazy recompute) and the retrieval-time freshness stamp — standard data-engineering (cache invalidation + concept drift), not from a paper. Validate the drift thresholds empirically (a `CONTEXT_EVALS.md` sub-track).
- **Open:** entity-resolution MERGE key — dedupe semantically on a resolved `uuid`, NOT on `name` (Graphiti resolves by embedding+LLM).

## 3) Fusion + rerank (only when ≥2 methods fire)
Normalize → **RRF** `score(d)=Σ 1/(k+rank)`, **k=60** (Cormack & Clarke SIGIR 2009; rank-based = scale-free, solves BM25-vs-cosine normalization) → **cross-encoder rerank** (bge-reranker-v2 / Qwen3-reranker / Cohere class; +11% nDCG BEIR; implemented in fuse.cross_encoder_rerank() but NOT wired into the default serve() path — roadmap item 6; latency-budgeted in §5) → source-diversity. Pure structural (method 1 only) skips fusion.
Evidence schema (at ingest, every candidate): `evidence_id · source_id · source_path · source_type · node_id · chunk_span · retrieved_at · valid_at · invalid_at · created_at · expired_at · freshness_state · namespace · retrieval_method · raw_score · retrieval_score`.

> **Naming convention (FIX-RECON / S6 — "confidence" disambiguated).** Bare `confidence` previously named three distinct quantities across layers; they are now always qualified (codified in `01-context/src/reconcile.py:RECALL_NAMING`):
> - **`retrieval_score`** — evidence relevance from the retriever (calibrated, vs the uncalibrated `raw_score`). *Was the evidence-schema `confidence` field above.*
> - **`generator_self_confidence`** — the model's stated confidence in its own generation (the `DecisionRouter` `≥70` gate, `VoteCalculator` `/100`).
> - **`claim_faithfulness`** — per-claim support-by-evidence (the §4 faithfulness score).

## 4) Decision + challenge + faithfulness layer (Case 2 — ported from `ai-product-council`, real tested code)
The "who scores / who decides / who challenges" brain. APC's TS governance engine is pure logic, zero model deps → portable as a library.

**a) Scoring** (`VoteCalculator.ts:33-72`): proposal score = Σ `weight × (generator_self_confidence/100)`, normalized to [0,1]; weight is **role-expertise × stage-dependent** (`council-data.ts` VOTING_WEIGHTS, capped 0–0.20). 4-factor RelevanceScore (stageAlign 40/topic 30/impact 20/precedent 10, `StageManager.ts:99-134`) decides whose score counts. → **Adopt: `claim_faithfulness` replaces the bare-`confidence` term; weight reviewers by domain-expertise.**

**b) Final say** (`DecisionRouter.ts:36-74`, tiered): impact≤3 → highest-weighted agent decides solo (anti-bikeshedding); generator_self_confidence≥70 ∧ impact≤5 → autonomous; else weighted vote vs **impact-scaled threshold** (routine 0.50 / architectural 0.67 / security 0.80 / irreversible 0.90) **+ required-agent gate** (security needs ethics + security-eng approval); 3 failed rounds → **escalate to human** with auto recommendation + dissent (`checkStalemateProtocol VoteCalculator.ts:140-219`). → **This IS the action gate's decision logic. Threshold-scales-with-impact + required-reviewer maps onto the categorical gate** (`MODEL_ROUTING.md`): reversible→solo agent; irreversible→0.90 threshold + mandatory auditor + human.

**c) Challenge** (`SycophancyDetector.ts:91-195`): circuit-breaker detecting convergence-without-evidence (confidence-monotonicity 0.30 + diversity-collapse-cosine 0.30 + position-switch-sans-evidence 0.25 + unanimous-escalation 0.15; composite≥0.60 → pause-and-challenge → perspective-take → revert-to-round-1). + **DebateAnonymizer** (Alpha/Beta/Gamma, kills authority bias). + **ForceEntryEvaluator** (safety roles auto-join, can't be voted down). → **Adopt: faithfulness-auditor that cannot be silenced on flagged claims; anonymize source-agent before peer scoring; force re-grounding when reviewers converge without new evidence.**

**Faithfulness rules:** structured answer contract `{claims:[{claim_id,text,evidence_ids[],support_status}], unsupported[], conflicts[], abstain}`. No citation, no claim. Unsupported → one CRAG requery → abstain/partial. **Abstain blocks the ACTION**: any `support_status < SUPPORTED` feeding a categorical-gate action (push/send/money/secrets/migration) → forced human escalation, regardless of generator_self_confidence. Isolation = categorical, leakage 0.

> APC honesty caveats: live 3-round agent rebuttal is **doc-only** (code analyzes `Vote[][]` post-hoc); calibration layers 2/3 partly aspirational; swarms LLM-judge is a vendored lib, not APC's engine. Port the vote-math + router + circuit-breaker (real, tested); rebuild live debate if needed.

## PART 4 — Multi-source epistemics: weighting · summarization · conflict
The 3 sources are not interchangeable relevance scores — they have different **epistemic roles**. Weighting, summarization, and conflict all follow from that.

### Weighting — by EPISTEMIC ROLE × query type, not a fixed number
| Source | Epistemic role | Authoritative for | NOT authoritative for |
|---|---|---|---|
| **Graph / MATCH** | **fact authority** — deterministic, provenanced, bi-temporal (you know it's valid-as-of + where it came from) | facts, relations, current/historical status, "what's linked to X" | prose nuance, open-ended meaning |
| **PageIndex** | **prose authority** — reasoning over a single doc, section-traceable | "what does doc D argue about Y", in-doc multi-section synthesis | cross-entity facts, anything outside that doc |
| **Vector** | **RECALL / discovery only — NOT authority** (similarity ≠ truth; BRIGHT: top embedder 18.3 on reasoning-retrieval) | finding candidate nodes/passages, fuzzy "about Y" | *winning any factual claim on its own* |

**Scenario → primary:** factual/relational/as-of → **graph**; "find/similar/about" → **vector** (graph filters by namespace+validity); "what does this doc say / explain the reasoning" → **PageIndex** (graph scopes which doc); multi-hop → **graph** (structural hops) + **PageIndex** (in-doc), vector fans out.
**When ≥2 fire (fusion):** RRF (rank-based, scale-free) + cross-encoder rerank for ORDERING — but the **epistemic rule overrides rank for trust**: a vector hit never outranks a graph fact for a *factual* claim (it contributes recall, not truth). **Numeric weights are RRF-`k` + eval-calibrated (Phase B), never asserted** (per the no-handwaving discipline). The principle is fixed (roles); the numbers are measured.

### Summarized context — summarize the CONVENIENCE layer, never the EVIDENCE layer
Summarization (to fit the token budget / RCR-Router) is lossy — it can silently drop provenance, validity, and conflict, which is exactly **authority-laundering** (a smooth summary reads as settled fact). Rules:
- **Graph facts are pulled EXACT, never summarized** — each carries `valid_at` + `episodes[]`. Summarizing facts into prose loses validity/provenance and can hide a conflict.
- **Only the stable `long_context` abstract is a summary**; the node-card = abstract + **live exact facts**.
- **PageIndex:** use the extracted SECTION (page/section-traceable) as evidence, NOT PageIndex's own gloss-summary.
- **The faithfulness contract survives summarization:** claim→evidence_ids + support_status + provenance stay attached. A summary is a VIEW; **the action gate checks the underlying evidence, not the summary.** Never act on the summary.
- A multi-item summary that merges sources **must flag conflicts, not smooth them** (see below).

### Contradicting contexts — a resolution ladder (most "conflicts" aren't real)
1. **Temporal first.** If one fact is superseded (`invalid_at` set), it's not a live conflict — the CURRENT one wins, the other is just history. The bi-temporal filter resolves most apparent conflicts *before* fusion (stale-vs-current ≠ contradiction).
2. **Epistemic role.** **Vector cannot win a contradiction** — it's recall, not authority; drop it as a tiebreaker. Graph-fact vs PageIndex-prose are usually about *different* claim types (a relation vs what a doc says); if they concern the SAME underlying fact, run **provenance-diff**: did the fact's source doc change? → the graph fact may be stale → trigger negative-delta retraction (PART 3-D). The doc (via PageIndex) is fresher than a fact extracted from an older version.
3. **Provenance / recency.** Between two genuinely-current facts from different sources, prefer stronger/more-recent provenance.
4. **Unresolved genuine conflict → SURFACE, never silently pick** (the §4 faithfulness `conflicts[]` rule). For an **ANSWER**: present both with provenance + claim_faithfulness + a conflict flag. For an **ACTION**: a conflict on a claim feeding a categorical-gate action → **abstain/escalate to human** (the action gate; acting on contested info is the failure mode). The **APC DecisionRouter** arbitrates when multiple agents are involved (impact-scaled threshold → escalate); the **SycophancyDetector** stops false-consensus from papering over it.
5. **Never let summarization (Q2) hide the conflict** — the conflict flag propagates through the summary to the gate.

**Net:** weight by role (graph=facts, PageIndex=prose, vector=recall-only); summarize the view but check the evidence; resolve conflict by temporal→role→provenance→surface-&-gate. The machinery already exists (bi-temporal validity, conflict-surfacing faithfulness, action gate, APC voting) — PART 4 just specifies how the 3 sources feed it. [design-synthesis on grounded parts: BRIGHT 18.3 = vector≠authority; bi-temporal + APC + faithfulness = already in-doc; weights = eval-calibrated, not asserted]

## 5) Eval gates — baseline-relative + statistically valid (+ Case 4: methodology is active research)
Absolute thresholds are ungrounded/corpus-dependent (top embedder 18.3 nDCG on reasoning → a fixed 0.78 fails by construction). **Gates = deltas vs measured baseline, set in Phase B dual-run**, significance-tested: paired bootstrap on per-query nDCG, report **n + 95% CI** (TREC/BEIR/RAGAS convention).
Metrics: nDCG@10 (primary) · recall@100/1000 (first-stage ceiling) · isolated rerank ablation · evidence coverage · faithfulness-error · citation-correctness · freshness · isolation-leakage · token/latency — **per query-class**, not pooled. Hard absolutes (security): isolation leakage = 0; zero stale critical facts. Provisional calibration targets (LABELED-ESTIMATE): precision ~0.80, recall ~0.85, citation ~0.95, unsupported ≤0.05.
**Case 4 — open research:** context-eval methodology (what "right context" means per route, how rerank-loop builds it when a gate fails) needs its own experimentation track. Treat §5 numbers as provisional until that track runs. The rerank loop is the corrective mechanism: gate fail → rerank/requery (≤T=3) → re-eval. Companion spec: `CONTEXT_EVALS.md` (to write).

## 6) Source-system DAG
1. Planner/Classifier (resolve to graph pattern? → method ladder) → 2. Retriever(s) (graph-index default; +vector/PageIndex per eval) → 3. RRF + rerank (if ≥2) → 4. Freshness judge → 5. Synthesizer → 6. **APC scoring + decision router** → 7. Sycophancy/challenge + isolation gate → 8. **Action gate** (pass/partial/abstain/escalate).
Shared state: `query_id · route · role · namespace_policy · freshness_sla · candidate_evidence[] · fused_evidence[] · vote_result · eval_scores{} · retry_count · final_decision`.

## 7) Store decision (§8.1 — now informed)
**DECIDED: Neo4j (Community Edition)** [grounded 2026-06-01]. A property-graph DB with structure + vector + FTS + bi-temporal range index in one store. Neo4j Community gives all of it $0 self-host: vector index (GA since 5.13, via `LIST<FLOAT>` props) + **RANGE index on DATETIME** (the bi-temporal as-of filter) + full-text, plus the richest GraphRAG/Python ecosystem (`neo4j-graphrag-python`, LlamaIndex `Neo4jPropertyGraphStore`). **Kuzu was rejected on two independent dealbreakers:** (1) **abandoned Oct 2025 — Apple-acquired, repo archived, frozen at 0.11.3** (The Register / BetaKit / MacRumors / HN); (2) **no scalar/range index** — as-of temporal filtering would be a full scan, fatal for the bi-temporal model. Kuzu *would* have been the better-fit architecture if alive (embedded single-file, MIT, zero-ops) — the abandonment is what kills it. Cost of Neo4j = JVM ops burden (run via Docker locally or Aura free tier). Memory leg (engram/claude-mem) folds in as timestamped nodes. **Temporal = bi-temporal properties on the graph (PART 1 §3), NOT a time-series DB.** A TSDB (InfluxDB/Prometheus/TimescaleDB) is built for regularly-sampled numeric metrics + window-aggregation/downsampling — it cannot model discrete-fact validity, supersession, or multi-hop, so it's the wrong tool for knowledge-temporal. Neo4j (DATE/DATETIME + range index) and Kuzu (DATE/TIMESTAMP + comparison ops) both range-filter temporal properties natively — adopting bi-temporal edges = adopting the Graphiti pattern in-store, which collapses the temporal + memory legs into the graph. **The ONLY genuine time-series need is operational metrics** (token/latency/cost/eval-score over time) — those go to **Langfuse** (already mandated by `tracing.md`), or **TimescaleDB** (a Postgres extension → co-locate with any relational state, no separate store) if you outgrow Langfuse. Metrics are observability, NOT KB content — keep them out of the knowledge graph. **Store decided (Neo4j) — the build can proceed.**

## 8) Immediate next actions
1. ~~Store~~ **DECIDED: Neo4j Community** (Docker local / Aura free). 2. Define T0–T2 ontology (PART 0) as the Neo4j schema (labels + range/vector/FTS indexes) + the **temporal model (PART 3 below)**. 3. Ingest pipeline: provenance + ontology-anchor + node-property (short/long/chunks/bi-temporal) + dual chunking + episode/fact split. 4. Graph indexes (label/range/FTS) — the instant default path. 5. Vector index on long_context + chunks. 6. **PageIndex pilot** (`PAGEINDEX_PILOT.md`) — runnable NOW, standalone, de-risks the ladder's top rung. 7. Port APC governance lib (VoteCalculator + DecisionRouter + SycophancyDetector). 8. Eval harness + Phase B dual-run; stand up the `CONTEXT_EVALS.md` track.

## 9) Definition of done
- Tiered ontology live as graph schema; T3 auto-attaches. Graph-index structural path instant. Vector/PageIndex added per eval need.
- APC decision+challenge layer ported; abstain wired to action gate; isolation leakage 0.
- Eval gates beat measured baseline (significance-tested, n+CI) at ≤ baseline cost; context-eval track producing per-route criteria.
- Canary stable 7 days; drift dashboards live.

## Evidence base
`RETRIEVAL.md` (rerank +11% BEIR; contextual chunking −49/−67% Anthropic; BRIGHT 18.3/CoT 14.8→26.5; CRAG +7–36.6%; RCR-Router T=3) · `MODEL_ROUTING.md` (couplings, categorical gate) · RRF: Cormack & Clarke SIGIR 2009 · PageIndex: github.com/VectifyAI/PageIndex (mechanism confirmed; 98.7% FinanceBench = vendor self-report, exceeds 85% oracle → unproven). FinanceBench 2311.11944 (paper-walked): vector-RAG 19% shared-store / 50% single-store, long-context 79%, oracle 85% · Neo4j/Kuzu index docs (doc-read; Kuzu vector page DNS-blocked, verify in-session) · GraphRAG 2404.16130 (paper-walked: 72–83% comprehensiveness / 62–82% diversity — but LLM-built graph for SENSEMAKING, ≠ hand-defined ontology) / LlamaIndex PropertyGraphIndex (reference pattern) · APC governance: `ai-product-council/packages/apc-governance/src/{VoteCalculator,DecisionRouter,SycophancyDetector,ForceEntryEvaluator}.ts` (real tested code; live-debate + calib L2/3 doc-only). Depth: graph/PageIndex docs read in-session; APC verified file:line; arxiv abstract-level except BEIR/ColBERTv2/EmbeddingGemma paper-walked. Panel: 3× Opus + 2 grounded research streams, 2026-06-01.

---

## Multimodal RAG — OCR-first design choice (G2)

**Source:** Most et al., "Lost in OCR Translation? Vision-Based Approaches to Robust Document
Retrieval", arXiv 2505.05666 (2025). The abstract-supported claim: **OCR-based retrieval generalizes
better to unseen / varying-quality documents, while vision-native (ColPali) does well on
in-domain / fine-tuned documents.** For a heterogeneous, mostly-unseen company document mix,
that generalization edge → **default to OCR-first**; reach for vision-native only with a
fine-tuned in-domain corpus. (NOT a blanket "OCR wins everywhere" claim.)

**What this means for PART 1 (context engineering) — rasterised documents:**
Scanned PDFs / photographed pages arrive as images. The retrieval-architecture choice is:

| Option | Mechanism | When it wins (per 2505.05666 + this stack's $0/local rationale) |
|---|---|---|
| **OCR-first (DEFAULT)** | tesseract → text → `long_context` → existing embed→vector path | General/unseen/varying-quality docs (paper: OCR generalizes better); also $0/local + reuses the text ladder with no new retrieval machinery |
| Vision-native (ColPali / CLIP) | image-embedding directly, bypasses the text graph | In-domain / fine-tuned corpora (paper: vision-native does well there); no structural-edge support; not $0/local |

**Integration (the $0/local + reuse rationale):** OCR text lands in `long_context` exactly like any
other node description. The full pipeline — `embed.py` (EmbeddingGemma-300M, 768-dim),
`ladder.vector_rung()`, `serve.py` fusion/gate, namespace isolation — runs **unchanged**. The only
new seam is the OCR ingestion path (`01-context/src/ocr_adapter.py`, `etl.ingest_ocr_doc()`), which
sits upstream of `upsert_entity()`. Acceptance (`03-evals/src/eval_ocr.py`) proves this end-to-end:
T4 ingests an OCR'd page into the engineering namespace and shows `serve("engineering")` retrieves
it through its own ladder while `serve("finance")` does not (cross-role isolation).

**Born-digital PDFs:** poppler/pdf2image (rasterise PDF pages to PNG, then OCR) is the
documented add-on. Not installed by default ($0/offline constraint); add when needed.

**Depth label: LABELED-ESTIMATE (abstract-level; full results table not walked).** The
generalization-vs-in-domain direction is the load-bearing claim; specific per-benchmark margins
are deliberately not quoted here — re-verify against the paper before citing numbers.

---

## GraphRAG community summaries — closed gap vs Microsoft GraphRAG (GraphRAG communities)

**The gap (from rev 4 paper-walk):** Microsoft GraphRAG (2404.16130) wins on comprehensiveness and
diversity by running Leiden community detection over the full graph, then generating per-community
LLM summaries that are used at query time. Our hand-defined ontology (PART 0) gives structural
traversal that GraphRAG lacks — but we had no community-level summaries, so long-range thematic
questions (spanning many nodes without a clear structural path) had no summary target to retrieve
against. This was the named gap: "GraphRAG-style community sensemaking" absent from our stack.

**What GraphRAG communities delivers:**

| Component | What it does |
|---|---|
| `communities.py — build_communities()` | Per-namespace Leiden (`leidenalg` + `python-igraph`, networkx fallback) over each namespace's intra-namespace subgraph. Writes `:Community` + `:IN_COMMUNITY` edges, both namespace-stamped. |
| `communities.py — community_summary()` | Role-scoped read — `c.namespace IN $allowed` filter at read time; returns None if namespace not allowed. |
| `communities.py — assert_no_cross_namespace_community()` | Structural isolation proof — returns `[]` iff no `:Community` has members from >1 namespace. The cardinal bug is a cross-namespace community baked in at build; this catches it. |
| `summarize_adapter.py` | Pluggable $0-or-STOP one-shot CLI adapter (mirrors `judge_adapter.py`). `SUMMARY_CMD` unset → detection-only. STOPs on `auth\|api[ _-]?key\|payment\|billing\|quota`. |

**Why our GraphRAG is better on isolation:** Microsoft GraphRAG builds communities over a flat
graph and relies on post-hoc filtering. Our build-time isolation (ONTOLOGY §7) means a
cross-namespace community is **structurally impossible** — Leiden never sees cross-namespace edges.
This is stronger than a read-time filter that might be forgotten.

**What we still lack vs Microsoft GraphRAG:** LLM-built graphs from unstructured text (theirs
does LLM extraction; ours is hand-defined ontology + structured ETL). For sensemaking over
free-text corpora their approach is better; for structured KB with deterministic
ontology ours is more faithful and $0 on graph-building.

**Implemented:** 2026-06-14, GraphRAG communities. Demo: `communities.py demo()` prints `COMMUNITIES_OK`
against the local Neo4j ACME graph. Acceptance: T1–T7 (spec §5) all pass.
Unblocks: the Freshness epic (community refresh).
