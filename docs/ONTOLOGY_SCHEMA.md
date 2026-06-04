# ONTOLOGY_SCHEMA.md — the canonical company-brain ontology + schema

Date: 2026-06-03. Status: **being built** (beads epic `cb-6a1` Substrate & Schema). This is the reference the MATCH mutation engine reads. Source of truth for tiers + node labels + (forthcoming) per-relation rules + namespace.

Grounding: `HYBRID_RETRIEVAL_ARCHITECTURE.md` PART 0 (tiers), PART 1 (node-property schema), PART 3 (topology + MATCH-driven mutation). Store: **Neo4j Community** (§7 of HYBRID).

> **Community-edition constraint:** Neo4j Community supports **property uniqueness** constraints (`REQUIRE n.x IS UNIQUE`) only. `IS NODE KEY` and existence constraints are **Enterprise-only** — do not use them. Uniqueness + indexes (range/FTS/vector) are all available in Community.

Build-task map (beads): **T0/T1/T2 + uniqueness → this doc + `cb-6a1.3` (B1-onto, §1–§5)** · per-relation rule table → `cb-6a1.4` (B2-rules, §6) · `namespace`/ACL field → `cb-6a1.5` (FIX-NS, §7) · indexes → `cb-6a1.6` (B3-idx) · topology/relationships → `cb-6a1.7` (C1-topo) · node-property schema → `cb-6a1.8` (C2-props). DDL lives in `company-brain/schema/`.

---

## §1 — T0 Domains (6, static = the CXO org / fishbone)

The six top-level domains = the CXO org the agent army mirrors. Static; defined, not discovered.

| T0 domain | Owning CXO | Covers |
|---|---|---|
| **Engineering** | CTO | systems, code, infra, reliability |
| **Product** | CPO | what gets built and why |
| **Finance** | CFO | money in/out, runway |
| **Market/GTM** | CMO | positioning, demand, customers |
| **Operations** | COO | how the company runs day-to-day |
| **Governance/Risk** | CEO/Chief-of-Staff | decisions, policy, risk, audit |

Encoded as a fixed enum (a `:Domain {key}` node per row, or a label) — the roll-up target for every entity. T0 is the namespace root for role-scoping (PART 2 role axis).

## §2 — T1 Sub-domains (per-CXO, static, manually enumerated)

Initial charter-based enumeration (small + stable; tunable per CXO charter — this is the "define" step, not a discovered set). Each `:SubDomain {key}` rolls up to one T0 domain.

| T0 | T1 sub-domains |
|---|---|
| Engineering | Architecture · Repos · Infra · Releases · Incidents |
| Product | Roadmap · Features · Specs · UX · Research |
| Finance | Budget · Revenue · Costs · Runway |
| Market/GTM | Positioning · Campaigns · Pipeline · Customers · Competitors |
| Operations | Processes · Vendors · Support · Compliance-Ops · Logistics |
| Governance/Risk | Policies · Decisions · Risks · Audits · Security |

(Engineering + Finance rows are from HYBRID PART 0 verbatim; the other four are the initial enumeration to refine against each CXO charter.)

## §3 — T2 Entity types (node labels, static schema)

Every instance node carries the base label `:Entity` **plus** exactly one T2 label. The 9 domain anchors + 3 APC-borrowed governance types:

| T2 label | What | Typical T0 home | Canonical `key` format (MERGE target) |
|---|---|---|---|
| `Project` | a body of work | any | `project:<slug>` |
| `Repo` | a code repository | Engineering | `repo:<owner>/<name>` |
| `Decision` | a made decision | Governance/Risk | `decision:<uuid|slug>` |
| `Issue` | a tracked issue | any | `issue:<tracker>:<id>` |
| `Task` | an action/work item | any | `task:<tracker>:<id>` |
| `Capability` | a skill/capacity | any | `capability:<name>` |
| `Agent` | an agent/role | any | `agent:<role>` |
| `Policy` | a rule/policy | Governance/Risk | `policy:<slug>` |
| `ExternalSource` | an external doc/URL | any | `extsrc:<uri-hash>` |
| `Vote` | an APC vote record | Governance/Risk | `vote:<uuid>` |
| `DecisionRecord` | an APC decision record | Governance/Risk | `decrec:<uuid>` |
| `ForceEntryCondition` | a safety force-entry rule | Governance/Risk | `force:<slug>` |

**Topology labels** (PART 3, classification-orthogonal): `:Episodic` (source/ingestion unit) and `:Entity` (stable identity). A T3 instance = `:Entity:<T2>` + edges. See `cb-6a1.7` (C1-topo) for the relationship types.

## §4 — Tier roll-up (T3 → T2 → T1 → T0)

T3 instances attach by **cosine-anchor to nearest T2 type** (FEA), then **fixed roll-up edges** resolved by the graph index (no LLM):

```
(:Entity:<T2>)-[:IS_A]->(:T2Type {key})        // instance → its type (or via the label itself)
(:T2Type)-[:IN_SUBDOMAIN]->(:SubDomain {key})  // T2 → T1
(:SubDomain)-[:IN_DOMAIN]->(:Domain {key})     // T1 → T0
```
Roll-up is a fixed traversal → "all Engineering-domain facts" / "which CXO owns this" is one-hop-up. Keep T0–T2 small; only T3 grows.

## §5 — Node-key uniqueness (the B1-onto deliverable)

DDL: `company-brain/schema/01_constraints.cypher`. Community-compatible `IS UNIQUE` only.

- `:Entity.uuid` UNIQUE — internal stable identity (Graphiti pattern; MERGE on `uuid` for resolved entities).
- `:Episodic.uuid` UNIQUE — ingestion-unit identity.
- Per T2 label: `.key` UNIQUE — the **canonical business key**, the deterministic `MERGE` target (PART 3-D "resolve a keyed entity → MERGE on canonical key").

This makes structured ETL (D1) idempotent: re-ingesting the same Paperclip row `MERGE`s on `key`, never duplicates.

## §6 — Per-relation rule table (the mutation-engine contract)

Each relation type carries three axes (PART 3-D). The MATCH engine (`cb-dfv.4` E1-mut) reads these to pick the parameterized Cypher: **cardinality** `functional` (≤1 current → MATCH+SET supersede) | `additive` (many → MERGE its own edge); **temporal** `bi-temporal` (validity windows, can end) | `static` (permanent historical record, never superseded); **contradiction** `structural` (same subject+relation collision, detectable by Cypher, $0) | `semantic` (needs LLM) | `n/a`. Machine-readable form: `company-brain/schema/relations.yaml`.

| Relation | From → To | cardinality | temporal | contradiction |
|---|---|---|---|---|
| `ASSIGNED_TO` | Issue/Task → Agent | functional | bi-temporal | structural |
| `HAS_STATUS` | Issue/Task → status value | functional | bi-temporal | structural |
| `HAS_PRIORITY` | Issue/Task → priority value | functional | bi-temporal | structural |
| `BLOCKS` | Issue → Issue | additive | bi-temporal | structural |
| `DEPENDS_ON` | Task → Task | additive | bi-temporal | structural |
| `PART_OF` | Issue/Task/Repo → Project | functional | static | structural |
| `OWNS` | Agent → Project/Repo | additive | bi-temporal | structural |
| `IMPLEMENTS` | Commit/PR → Decision/Issue | additive | static | structural |
| `AUTHORED` | Agent → Commit | functional | static | structural |
| `DECIDED` | Agent → Decision | additive | static | structural |
| `VOTED_ON` | Agent → Decision (via Vote) | additive | static | structural |
| `SUPERSEDES` | Decision → Decision | additive | static | structural |
| `IN_SUBDOMAIN`/`IN_DOMAIN`/`IS_A` | tier roll-up | functional | static | structural |
| `MENTIONS` | Episodic → Entity | additive | static | n/a (provenance) |
| `RELATED_TO` | Entity → Entity (free-text) | additive | bi-temporal | **semantic** |

Only `RELATED_TO` (free-text) needs an LLM for contradiction; everything in the structured spine is `structural` → $0 deterministic Cypher. **Coverage gap (S7) — RESOLVED, see §10.**

## §10 — S7 resolution: the trichotomy generalizes to a 5-axis descriptor

The 4 "unfit" shapes (bounded-N, set-valued, time-windowed, numeric/range) do NOT need 4 new categories. Root cause (CPO lens): the `cardinality` axis **conflated two orthogonal questions** — *arity* (how many objects) and *overflow policy* (evict vs coexist). And (CPO+all): the contradiction check assumed conflict is **local to one subject+predicate slot**. Split arity from policy + make the collision-key a parameter, and the gaps close — plus 3 shapes S7 missed (ordered, weighted, hierarchical/cycle).

**Replace the 3 axes with a 5-axis per-relation descriptor:**

| Axis | Values | Resolves |
|---|---|---|
| **arity** | `1` \| `N(bound)` \| `∞` | bounded-N = arity `N`; `functional` = arity `1` |
| **overflow_policy** | `evict_oldest` \| `evict_by_rank` \| `reject` \| `coexist` \| `aggregate(fn)` | the eviction/ordered/weighted choice (split out of cardinality) |
| **verbs** | `add` \| `add+remove` | set-valued = additive + set-diff remove |
| **temporal** | `static` \| `bi-temporal` \| **`windowed`** | time-windowed = closed interval `[valid_at,invalid_at]` supplied at creation (vs bi-temporal's open, invalidated-by-next-write) |
| **contradiction** | `collision_key` ∈ `slot`\|`slot+window`\|`set`\|`path` × `resolution` ∈ `structural`\|`numeric(cmp)`\|`graph_invariant`\|`semantic` | numeric via `cmp`; **`path` collision-key** catches cycle/hierarchy contradictions the slot-local check misses |

**Deterministic ($0) coverage after the delta:** shapes 1–3 (bounded-N, set-valued, time-windowed) fully deterministic; shape 4 (numeric) — *detection* $0, *resolution* $0 whenever a per-relation comparator policy is declared (`latest`/`monotonic`/`range_disjoint`); the residual (ambiguous numeric from unstructured text, no policy — est. ≤20% of numeric relations, LABELED-ESTIMATE) routes to an **LLM-classifier that only proposes a bucket {replace,delta,correct,coexist}; the deterministic engine executes it**.

**Mandatory guardrails (security/Dragon-Judge lens):**
1. **The evaluation clock is an explicit argument, never ambient** — else every temporal mutation breaks reproducibility (same input, different output by wall-time). This is a latent bug in the current bi-temporal path, not just S7.
2. **Numeric supersession is never destructive** — the prior value is always retained bi-temporally, so a wrong classification is recoverable (collapses worst-case blast radius from "irreversible money-fact corruption" to "logged + reversible").
3. **LLM-as-classifier only** — runs in an isolated role with **no edge-write capability**, output is a typed enum (schema-validated), logged `(inputs, model, prompt_hash, confidence)`, confidence-gated → below threshold writes a `Conflict` node for human review (fails closed).
4. Bounded-N resolution must be **order-independent** (total tie-break key); `reject` is the safe default.

**Provenance:** resolved 2026-06-03 by a 3-lens panel (CTO/engineering — concrete Cypher templates + the `bounded`-subsumes-`functional` unification; CPO/data-model — the arity÷policy split + collision-is-local root cause + the 3 missed shapes; security — the smuggle test + the 4 guardrails). Run as Claude sub-agents ($0). The same question to the live Paperclip CTO agent **failed** (`adapter_failed: gpt-5.3-codex unsupported on a ChatGPT account`) — a model-auth misconfig, not a reasoning result. **Implementation of the 5-axis engine is a future task** (the current 15-relation spine stays $0-deterministic as-is).

**Cross-validation (2026-06-03):** after fixing its model (`gpt-5.3-codex`→`gpt-5.4`), the live Paperclip **CTO agent independently converged** on the same resolution — keep the 3 axes, add deterministic policy fields (`capacity{maxCurrent,overflowPolicy}` / `collection.mode=set_snapshot` / `valueSemantics`+typed comparator / `temporal:windowed`), with **default `reject` on bounded-N overflow** ("the engine must never guess which incumbent to supersede" — matching the security lens verbatim). Two independent agent systems reaching the same architecture is strong validation. One divergence: the Paperclip CTO judged numeric **fully** deterministic via a typed comparator, vs the Claude panel's ~20% LLM-residue for ambiguous-from-text numeric — an open question to settle when implementing.

**Field-name lock (2026-06-03):** the 5-axis descriptor is now **locked into `company-brain/schema/relations.yaml`** for all 15 spine relations — `arity {1|N|inf}`, `overflow_policy {evict|reject|coexist|aggregate}` (default `reject`; functional supersede = `arity:1 + overflow:evict`), `verbs {add|add+remove}`, `temporal {static|bi-temporal|windowed}`, `contradiction {collision_key: slot|window|set|path, resolution: structural|numeric|graph_invariant|semantic}` (numeric carries a typed `comparator` `gt|lt|range_overlap` — not a new contradiction family), plus `set_snapshot:true` on set-valued relations. The legacy `cardinality`/scalar-`contradiction` fields are retained alongside for reader orientation. Values document intent for the deferred E1-mut engine; nothing executes yet. **One open question remains** for engine-implementation time, to settle empirically: numeric/range determinism — a typed comparator (Paperclip CTO: fully deterministic) vs ~20% LLM-residue for facts ambiguous-from-text with no declared comparator policy (Claude panel; LABELED-ESTIMATE).

## §7 — `namespace` / ACL (isolation — convergent blocker B1)

Isolation (`leakage = 0`) is a hard security property, so the scope must be a **stored, indexed, queryable field on BOTH nodes and `:RELATES_TO` edges** — not only a routing axis or a fusion-time field (the gap SYSTEM_COHERENCE flagged: the deterministic filter the eval layer leans on was filtering a field that didn't exist).

**Field:**
- `namespace : string` on every `:Entity` node **and** every `:RELATES_TO` edge. Value = the owning T0 domain (`engineering|product|finance|market|operations|governance`) or `shared` for legitimately cross-cutting facts.
- optional `acl : list<string>` — extra domains permitted to read (empty = owner-only + shared).
- Set at INGEST, never null (the ETL stamps it from the source's owning domain). Indexed → B3-idx (`cb-6a1.6`).

**Role-scoped read (the deterministic isolation filter):**
```cypher
// CTO role: $allowed = ['engineering','shared']; both endpoints AND the edge must be in-scope
MATCH (n:Entity)-[r:RELATES_TO]->(m:Entity)
WHERE n.namespace IN $allowed AND r.namespace IN $allowed AND m.namespace IN $allowed
RETURN n, r, m;
```
The edge carries its own namespace, so a `shared` node can still hold role-private facts that stay invisible to other roles.

**Build-time isolation (upstream of any serve filter — the second half of B1):**
- A derived artifact (community summary, PageIndex tree, multi-doc embedding) is built **per-namespace only**. One that would span namespaces is **forbidden at build** unless an explicit `acl` grant authorizes the union — a single namespace tag cannot represent a mixed-role unit, so the serve filter structurally cannot catch a leak baked in at build.
- The ETL **refuses to write a node/edge with null namespace** (code-level invariant in D1/D2 — Community has no existence constraint).

Demonstration: `company-brain/schema/02_namespace_demo.cypher` — a CTO-scoped read returns the engineering fact and **not** the finance fact.

## §8 — Topology (C1: episodic / entity / fact graph)

Orthogonal to the tier hierarchy (PART 3). Five elements; relationship types are created on first write (Neo4j needs no type DDL). Canonical sample: `company-brain/schema/04_topology.cypher`.

| Element | Label / type | Temporal fields | Role |
|---|---|---|---|
| Episode | `:Episodic` | `created_at` (txn) · `valid_at` (event) | ingestion unit (doc/commit/message) |
| Entity | `:Entity` + one T2 label | `created_at` | stable identity |
| **Fact** | `(:Entity)-[:RELATES_TO]->(:Entity)` | **`valid_at`/`invalid_at` (event) + `created_at`/`expired_at` (txn)** + `name`·`namespace`·`episodes[]` | the bi-temporal fact — the only 4-field element |
| Provenance | `(:Episodic)-[:MENTIONS]->(:Entity)` | `created_at` | which episode observed an entity |
| Sequence | `(:Episodic)-[:NEXT_EPISODE]->(:Episodic)` | `created_at` | timeline adjacency |

**Versioning = version the EDGE** (Graphiti): on contradiction the old fact edge is invalidated in place (`invalid_at = new.valid_at`, `expired_at = now()`) and kept; a new edge is added. **As-of-T** = `valid_at <= T AND (invalid_at IS NULL OR invalid_at > T)` on the range index (B3) — instant, no LLM.

> Cypher gotcha: never place a **null** property in a `MERGE` pattern (Neo4j rejects it). "Current fact" ⇒ `invalid_at`/`expired_at` are ABSENT; set the rest via `SET`.

## §9 — Node-property schema (C2: what a well-formed node carries)

Description tier and content tier are DISTINCT (PART 1 §3). A node is **well-formed iff `short_context` + `long_context` + provenance + ontology-anchor + `namespace` are populated at ingest.**

| Property | Type | Meaning | Backed by |
|---|---|---|---|
| `uuid` | string | internal identity | `entity_uuid` unique |
| `key` | string | canonical business key (MERGE target) | per-T2 unique |
| `namespace` | string | owning T0 domain / `shared` (isolation) | `node_namespace` |
| `short_context` | string | title + type + 1-line "what this is" | graph index / FTS |
| `long_context` | string | **fact-free** abstract (facts live as edges) — the vector-recall + mid-tier injection target | `node_text` FTS + `node_embedding` |
| `embedding` | list<float> | content vector of `long_context` (0-hop; EmbeddingGemma-300M, 768-d) | `node_embedding` VECTOR |
| `chunks` | list<string> | actual source content (1, or N if split) | chunk-level recall |
| `chunk_count` | int | N chunks | — |
| `embedded_at`·`embedding_model`·`content_rev`·`dirty`·`summary_at`·`fact_rev` | mixed | freshness stamps (PART 3-B drift sweep) | — |
| `pageindex_ref`·`tree_built_at` | string·datetime | **long-doc node types ONLY** — handle to that node's PageIndex tree (graph↔RAG seam) | — |

Facts are NOT baked into `long_context` (keeps the embedding 0-hop); the node-card is assembled at READ = `long_context` + live bi-temporal edges (PART 3-B). Structured nodes (issues/agents/repos) carry no `pageindex_ref`; only long-doc nodes do. Demo: `company-brain/schema/05_node_props.cypher`.

### §9-R — Recall-layer provenance + index-side hypothetical questions (FORWARD SPEC)

Index-side hypothetical-question vectors (HyDE-style) are a **deferred** recall enhancement. This locks their provenance + quarantine contract now, while the design is fresh, so an LLM-generated search vector can never be confused with a canonical fact. Nothing here is applied yet — no such vectors exist (the recall layer is not built).

**Provenance fields (every search/recall vector):**

| Field | Type | Meaning |
|---|---|---|
| `provenance` | `content` \| `hyde` \| `hypothetical_q` | which generator produced the vector |
| `llm_generated` | boolean | `false` only for the canonical content vector |

- **Canonical content vector** = the `embedding` of `long_context` (`provenance:content`, `llm_generated:false`) — the only fact-bearing vector; unchanged from §9 above.
- **HyDE / hypothetical-question vectors** = `llm_generated:true`, stored on a **separate `:SearchProxy` node** linked to the entity via `(:SearchProxy)-[:SEARCH_PROXY_FOR]->(:Entity)` — **not** as a second embedding property on `:Entity`. *Rationale (minimal option):* D4 fact-extraction and the bi-temporal MATCH engine only ever read `:Entity`, so a generated vector is out of the fact path **by construction**, not by a remembered filter. A second `:Entity` vector property would sit one forgotten `WHERE` clause away from leaking into a fact. One mechanism — do **not** also stand up a parallel vector-index namespace. DDL sketch: `company-brain/schema/05_node_props.cypher`.

**Index-side hypothetical-question design:**

- **Generated from two sources, in one LLM call (both concatenated):**
  - `short_context` → precise, fact-anchored questions (the **precision** axis — "what is issue 42's status / owner").
  - `long_context` → thematic, conceptual questions (the **recall** axis — "what touches bolt-client timeouts"). Because `long_context` is **fact-free** (§9), generating from it is *protective*: there is no fact in it to corrupt.
- **Regenerated** on the **G1-sweep dirty-flag** (same freshness trigger as embeddings; `source_content_rev` tracks the `content_rev` it was built from).
- **Quarantined** — the generated question text/vector is **never** persisted as `long_context`, **never** fed to D4 extraction, and **never** round-trips into a fact edge. It is a search-time proxy only.
- **Eval-gated** — kept only if a **recall@k lift is empirically proven**. The gain is corpus-dependent and **unmeasured here**; if no lift, the `:SearchProxy` layer is simply not built.
