# Architecture

**The system-level mental model for Builder Guild — the front door every other doc links into.**

Builder Guild is a graph-primary, bi-temporal, role-scoped knowledge base that an AI agent fleet reads from and writes to, wrapped in an evaluation layer that refuses to certify what it cannot measure. Two invariants define it: **no LLM ever writes a fact** (zero hallucinated state) and **no metric certifies itself** (every gate threshold is measured against human-validated ground truth, never asserted) — see [`README.md`](../README.md).

## What you'll find here

The three layers and how they compose; the data model (bi-temporal edges, the three kinds of truth, namespace isolation, the typed relation contract); the design principles and *why* each exists; the end-to-end data flow as an ASCII diagram; and the core abstractions (`serve()`, `apply_edge`, the abstain gate, the retrieval ladder). This doc *summarizes and cross-links* — the deep-dive design docs remain the source of detail. Where a claim matters, it cites `file:function` or `file:Lnn`.

---

## 1. The three layers

The repo is three top-level directories, and the layout itself encodes a safety rule ([`README.md`](../README.md) lines 27-30):

```
01-context/   Context + Retrieval — the graph store, deterministic writes,
              hybrid retrieval (keyword → graph → vector, RRF-fused),
              role-scoped serving, and the ONLINE enforcement gates.
02-agents/    Agent layer — agents as consumers of governed context:
              role trust boundary, suggest-only → leased autonomy, action audit.
03-evals/     AI Evaluation — the OFFLINE program: golden sets, debiased
              judges, eRAG source weights, abstain-gate calibration, meta-eval.
```

**The safety rule that the layout enforces:** *online enforcement* — namespace filters and the sufficiency×confidence gate — ships in `01-context/` and runs on every request; *offline evaluation* — judges, golden sets, calibration — lives in `03-evals/` and is **never wired as a live decision signal** ([`03-evals/CONTEXT_EVALS.md`](../03-evals/CONTEXT_EVALS.md) §1). The eval layer measures the gate; it never *is* the gate. Confusing the two is the failure mode the directory split prevents.

They compose top-down: `01-context` serves governed context, `02-agents` consumes it under a role trust boundary, and `03-evals` measures whether the serving gate deserves to grant autonomy — feeding a manual, human-read decision back into `01-context/src/abstain.py`.

---

## 2. The data model

### Bi-temporal edges — two independent clocks

A fact is an edge `(:Entity)-[:RELATES_TO]->(:Entity)`, and it is the only element in the graph that carries **four** temporal fields ([`01-context/ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §8):

| Clock | Fields | Meaning |
|---|---|---|
| **Business / event time** | `valid_at`, `invalid_at` | when the fact was *true in the world* |
| **System / transaction time** | `created_at`, `expired_at` | when the store *recorded / retracted* it |

Versioning happens on the **edge** (the Graphiti pattern): on contradiction the old fact edge is invalidated in place (`invalid_at = new.valid_at`, `expired_at = now()`) and *kept* — a new edge is added alongside. Nothing is destroyed, so history is replayable.

**The SENTINEL contract makes point-in-time queries a single index predicate** ([`ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §8, line 173): a *current* edge carries `invalid_at = datetime('9999-12-31T00:00:00Z')` — never `NULL`. So "current" is `invalid_at > now`, and "as of T" is `valid_at <= T AND invalid_at > T`. A *current* read rides the `rel_invalid_at` range index; an *as-of* read uses both predicates, backed by the separate `rel_valid_at` and `rel_invalid_at` range indexes — instant, no LLM. (Cypher gotcha, worth knowing: never place a literal `null` in a `MERGE` pattern; set end-fields via `SET`.)

### The three kinds of truth, never mixed

Vector RAG answers "what's similar?". It cannot answer the three questions a fleet actually asks ([`README.md`](../README.md) lines 32-48):

1. **Current truth** — who owns X *now*. Resolved by the sentinel: `invalid_at > now`.
2. **Role-scoped truth** — what's visible to *which role*. Resolved by namespace filtering at read (below).
3. **Temporal truth** — what was true *when* we decided F. Resolved by the as-of predicate; the current owner is not necessarily the past owner, and an as-of query requires historical evidence, not current state.

### Namespace isolation — a hard property on node *and* edge

Isolation (`leakage = 0`) is a security property, not a convenience filter, so `namespace` is a **stored, indexed field on every `:Entity` node AND every `:RELATES_TO` edge** ([`ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §7; [`CONTRIBUTING.md`](../CONTRIBUTING.md)). The value is the owning T0 business domain (`engineering|product|finance|market|operations|governance`), the operational `history` namespace (session/provenance data; `governance` may also read it), or `shared`. The role-scoped read requires *both endpoints and the edge* to be in scope:

```cypher
MATCH (n:Entity)-[r:RELATES_TO]->(m:Entity)
WHERE n.namespace IN $allowed AND r.namespace IN $allowed AND m.namespace IN $allowed
```

The edge carrying its own namespace is what lets a `shared` node still hold role-private facts invisible to other roles. Isolation is enforced twice: at **read** (the filter above, in `serve.py` via `scope.py`) and at **build** — derived artifacts (community summaries, PageIndex trees, multi-doc embeddings) are built per-namespace only, because the serve filter structurally cannot catch a leak baked into a cross-namespace artifact at build time. `scope.py:allowed_namespaces` is deny-by-default: an unknown role sees only `shared`; `governance` is the one named cross-cutting auditor that may read every slice.

### The typed relation contract — `relations.yaml`

Facts are not free-form. [`01-context/schema/relations.yaml`](../01-context/schema/relations.yaml) declares **16 typed relation types** (the [`ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §6 table groups the roll-up relations with `IS_A` and so refers to a "15-relation spine" — same contract, different grouping). Each relation carries a **5-axis descriptor** that the mutation engine reads at runtime to pick parameterized Cypher:

| Axis | Values | What it controls |
|---|---|---|
| `arity` | `1` \| `N` \| `inf` | how many current objects allowed |
| `overflow_policy` | `evict` \| `reject` \| `coexist` \| `aggregate` | what happens on overflow (default `reject` — the engine never guesses which incumbent to supersede) |
| `verbs` | `add` \| `add+remove` | accumulate-only vs also retract |
| `temporal` | `static` \| `bi-temporal` \| `windowed` | permanent record vs validity windows |
| `contradiction` | `collision_key` (slot\|window\|set\|path) × `resolution` (structural\|numeric\|graph_invariant\|semantic) | how conflicts are detected and resolved |

A *functional* edge (one current object) is `arity:1 + overflow:evict` — the new fact supersedes the old. An *additive* edge is `arity:inf` — facts accumulate. `DEPENDS_ON` and `SUPERSEDES` use `collision_key:path + resolution:graph_invariant`, a cycle guard. Only `RELATED_TO` (free-text) is *schema-declared* `resolution:semantic` — the axis reserved for LLM contradiction adjudication — but that adjudication is **not implemented**: `mutate.py` has no semantic path, so a `RELATED_TO` write falls through to additive `MERGE` like any other relation (the current write path does no contradiction adjudication). Everything in the structured spine is `structural` → `$0` deterministic Cypher. The engine (`mutate.py`) implements only the value-set the current relations actually exercise — arity `1`/`inf`, `evict`/`reject`, `static`/`bi-temporal`, and the `graph_invariant` cycle guard; declared-but-unused axis values (`coexist`, `aggregate`, `windowed`, `numeric`, `semantic`, bounded-N) are added at first use ([`ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §10).

---

## 3. Design principles (and why)

- **Graph-primary over vector RAG.** Vector similarity cannot answer multi-hop, point-in-time, permissioned questions. The graph makes current / role-scoped / temporal truth first-class; vectors serve *recall only*, never fact authority ([`README.md`](../README.md) lines 32-48).
- **Never let an LLM write a fact.** The fact path (`:Entity` nodes + typed bi-temporal edges) is deterministic. LLM-generated content is quarantined to the *recall layer* (`:SearchProxy` nodes, embeddings, hypothetical questions) — never entity properties or edges ([`CONTRIBUTING.md`](../CONTRIBUTING.md)). Structurally enforced: the ingest-time staging gate's LLM entrypoint (`staging.stage_llm`) holds no reference to the write function, so an extraction *cannot* write an edge directly.
- **Deterministic, idempotent ETL.** Facts enter via `MERGE` / `MATCH…SET` on canonical business keys — the core business types (`Project`, `Repo`, `Issue`, `Decision`, `Task`, `Agent`, …) carry a `.key` UNIQUE constraint ([`schema/01_constraints.cypher`](../01-context/schema/01_constraints.cypher)); a few upsert-only labels (`StatusValue`, OCR `Document`) `MERGE` on `key` without a DB uniqueness constraint. Re-ingesting the same input `MERGE`s, never duplicates — the same input twice produces the same graph ([`ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) §5).
- **Abstain / trust gate.** The serve gate combines **sufficiency × confidence**, never sufficiency alone — LLMs answer correctly 35–62% of the time even on *insufficient* context, so abstaining on low sufficiency alone destroys accuracy ([`01-context/src/abstain.py`](../01-context/src/abstain.py) header). Uncalibrated ⇒ the system only *suggests*.
- **Online enforcement ≠ offline evaluation.** The single most load-bearing boundary: the same *decision gate* runs live in `01-context` (enforcement) and is *measured* in `03-evals` (evaluation), but the eval scores are never fed back as a live signal. The directory split is the guardrail ([`README.md`](../README.md) lines 27-30).

---

## 4. End-to-end data flow

```
   WRITE PATH (deterministic — no LLM writes a fact; apply_edge is the SOLE edge writer)

   (a) TRUSTED structured ETL — writes RELATES_TO edges DIRECTLY, no staging
   ┌────────────────────┐
   │ etl.ingest /       │──────────────────────────────────────┐
   │ etl_history        │                                       │
   └────────────────────┘                                       │
   (b) LLM / low-trust extraction — must STAGE, then be promoted │
   ┌────────────────────┐   ┌─────────────────┐   ┌─────────────▼────────────────┐
   │ extract.py /       │──▶│ staging gate     │─▶│ apply_edge  (mutate.py)      │
   │ agent propose_edge │   │ (:Candidate;     │  │ SOLE edge-write gateway:     │
   │                    │   │  approve/reject/ │  │  MERGE/MATCH-SET, 5-axis rule│
   │                    │   │  promote())      │  │  namespace-scoped, bi-temporal│
   └────────────────────┘   └─────────────────┘  └──────────────┬───────────────┘
        (matches endpoints by KEY only; namespace-ownership      ▼
         precheck is the caller's job, e.g. staging.promote)
                                          ┌──────────────────────────┐
                                          │   Neo4j graph store       │
                                          │ :Entity + :RELATES_TO     │
                                          │ (sentinel invalid_at)     │
                                          └──────────────┬───────────┘
   READ PATH (serve.py: scope → retrieve → fuse → stamp → gate)
                                                        ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ 1. SCOPE     scope.py → allowed namespaces (role trust boundary)│
   │ 2. RETRIEVE  ladder.py rungs, scored SEQUENTIALLY in serve.py:   │
   │              keyword_rung, graph_rung, vector_rung, chunk_rung   │
   │              (all namespace-scoped; no parallelism)              │
   │ 3. FUSE      fuse.rrf (RRF), ties broken by epist authority:     │
   │              keyword > graph > vector > chunk                    │
   │ 4. STAMP     stamp/reconcile: current facts, freshness           │
   │ 5. GATE      gate() faithfulness → abstain.stage_a_decision      │
   │              (sufficiency×confidence) → abstain.execute          │
   └────────────────────────────┬───────────────────────────────────┘
                                ▼
        decision ∈ {pass | partial | abstain | escalate}
        mode ∈ {suggest | autonomous}     execute(): suggest-only ⇒
        even a `pass` is BLOCKED and routed to a human
```

`serve()` scores the keyword, graph, vector, and chunk rungs **sequentially in Python and RRF-fuses** them (never in parallel) — it does *not* use `ladder.retrieve()`'s first-hit escalation, which short-circuits at the first rung that hits (fusion needs every source). These are two deliberate retrieval modes over the one store ([`serve.py:213`](../01-context/src/serve.py) docstring).

---

## 5. Core abstractions (the god-nodes)

**`serve()`** — [`01-context/src/serve.py:213`](../01-context/src/serve.py). The end-to-end read chain. Signature: `serve(query_text, role, pattern=None, action=None, deep_serve=False, rerank=False, include_communities=False, as_of=None)`. Wires scope → retrieve → fuse → epist → stamp → reconcile → gate → execute, and returns a uniform envelope with `decision`, `mode`, `executed`, `provenance`, `trace`, plus a reproducible read envelope (`commit_id` / `snapshot_id` / `audit_id`, the last a deterministic hash of the call args). `role` is **trusted** here — it must be authenticated upstream; a self-asserted `role='governance'` would read every namespace. `as_of` threads point-in-time reads through the **structural** path only — graph-rung MATCH and fact-card validity checks; keyword/vector/chunk recall and node prose stay current-only in v1.

**`apply_edge`** — [`01-context/src/mutate.py:54`](../01-context/src/mutate.py). The **sole sanctioned entrypoint** for current-edge mutation (the "write gateway"; a CI grep-gate heuristically scans the Python source paths — allowlisting the engine plus adversarial test fixtures — for hand-written current `:RELATES_TO` writes that bypass it. It is a static backstop with known evasions (writes split across >3 lines, ad-hoc `cypher-shell`, schema fixture files), not an absolute guarantee — the runtime `invariant_check.py` / `cycle_check.py` sweeps are the authoritative net). Applies the relation's full 5-axis rule: evict-supersede for functional edges, reject-on-collision for `arity:1 + reject`, additive MERGE for unbounded arity, a cycle guard for `graph_invariant` relations, and a subject-node write-lock to serialize concurrent `arity:1` writers. Because Neo4j Community cannot express a "exactly one current edge" constraint, the guarantee is *single writer at the app boundary + continuous detection* (`invariant_check.py`, `cycle_check.py`), not DB-enforced.

**The abstain gate** — [`01-context/src/abstain.py`](../01-context/src/abstain.py). `abstain_gate()` computes the selective score from `sufficiency × self_confidence` through a logistic. `stage_a_decision()` composes it with the faithfulness `gate()` ([`gate.py:28`](../01-context/src/gate.py) → `pass | partial | abstain | escalate`, faithfulness *before* confidence). `execute()` is the real guardrail: an action auto-runs *only* when `mode=='autonomous'` (i.e. the role is `CALIBRATED`) **and** `final=='pass'`; while suggest-only, even a `pass` is blocked and routed to a human. `auto_revert()` is **revoke-only** — it can flip a role from `True` back to `False` on bad evidence, but no production code path ever sets `True`.

**The retrieval ladder** — [`01-context/src/ladder.py`](../01-context/src/ladder.py). Four rungs, all namespace-scoped: `keyword_rung` (exact IDs/names), `graph_rung` (structural MATCH, honors `as_of`), `vector_rung` (local EmbeddingGemma recall), `chunk_rung` ("which passage" chunk-level recall). `ladder.retrieve()` is an eval-gated first-hit *escalation* ladder that steps `graph_rung → vector_rung → PageIndex` (keyword and chunk rungs are **not** part of it); `serve()` instead scores keyword+graph+vector+chunk *sequentially and RRF-fuses* them (not in parallel). Vector and chunk hits are recall-only and never become gate claims — the epist authority order (`keyword > graph > vector > chunk`) keeps a fuzzy recall hit from outranking an exact-ID reference at fusion.

---

## 6. Current state — shipped vs roadmap (honest)

Per [`docs/ROADMAP.md`](ROADMAP.md):

- **G1 — Agentic RAG: CLOSED.** A planner (`02-agents/src/planner.py`) self-chooses ≥2 distinct retrievals and terminates on a bounded confidence/abstain signal; agent-callable via a stage-scoped MCP tool. Output stays **suggest-only** — orthogonal to the autonomy lease.
- **G2 — Multimodal RAG: OCR path CLOSED (OCR-first by design, not vision).** `etl.ingest_ocr_doc` embeds OCR text at ingest (`→ embed.embed_node`) and it is retrieved through the live `serve()` vector rung. Vision/ColPali is deliberately out of scope (OCR beat ColPali in all evaluated settings in the cited study). Multimodal here means OCR, not general vision — check [`ROADMAP.md`](ROADMAP.md) for remaining scope.
- **G3 — Calibration / autonomy: OPEN and FOUNDER-GATED.** `abstain.CALIBRATED` is a per-role dict defaulting **every role to `False`**. Autonomy is **not leased** — no production code path grants a lease (only the G3 test seeds `True` transiently to exercise revoke). Two calibration runs, both landing on autonomy OFF for *different* reasons: the public case study ([`03-evals/CASE_STUDY_calibration.md`](../03-evals/CASE_STUDY_calibration.md)) fit the sufficiency proxy with a **negative** weight (more retrieved facts predicted *less* correctness); the last measured run ([`docs/ROADMAP.md`](ROADMAP.md) lines 18-22) **refit that weight positive** but **failed its selective-gain gate** (−3.0pp). Either way the gate **correctly refused to certify autonomy**. `_support_coverage()` is implemented and test-pinned, but G3 Item 2 acceptance stays **OPEN**. **"Suggest-only" is the true, enforced current state.** Granting a lease is human-only, off the auto-grant path.

That refusal is not a bug — measure, refuse, fix, re-measure is the product.

---

## Source of truth (files this doc documents)

- [`README.md`](../README.md) · [`CONTRIBUTING.md`](../CONTRIBUTING.md) · [`DUAL_LICENSE.md`](../DUAL_LICENSE.md)
- [`01-context/ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) · [`01-context/schema/relations.yaml`](../01-context/schema/relations.yaml) · [`01-context/schema/*.cypher`](../01-context/schema/)
- [`01-context/src/serve.py`](../01-context/src/serve.py) · [`mutate.py`](../01-context/src/mutate.py) · [`abstain.py`](../01-context/src/abstain.py) · [`scope.py`](../01-context/src/scope.py) · [`ladder.py`](../01-context/src/ladder.py) · [`gate.py`](../01-context/src/gate.py) · [`fuse.py`](../01-context/src/fuse.py)

## See also (deep-dive design docs)

- [`01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md`](../01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md) — full write/read/freshness/conflict design
- [`01-context/RETRIEVAL.md`](../01-context/RETRIEVAL.md) · [`01-context/PAGEINDEX_PILOT.md`](../01-context/PAGEINDEX_PILOT.md) — retrieval evidence base, long-doc pilot
- [`02-agents/AGENT_ARCHITECTURE.md`](../02-agents/AGENT_ARCHITECTURE.md) — agents on governed context: roles, trust boundary, leased autonomy
- [`03-evals/CONTEXT_EVALS.md`](../03-evals/CONTEXT_EVALS.md) — the eval research synthesis
- [`03-evals/CASE_STUDY_calibration.md`](../03-evals/CASE_STUDY_calibration.md) — the first real calibration run, numbers + verdict
- [`docs/ROADMAP.md`](ROADMAP.md) — what's next, in capability terms
