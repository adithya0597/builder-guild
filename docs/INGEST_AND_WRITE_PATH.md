# The deterministic write path — how facts get into the graph

**Purpose:** every way a fact enters the Neo4j graph funnels through one function — `mutate.apply_edge`. This doc is the navigable map of that funnel: the two ingest sources that feed it, the truth-gate that sits in front of the low-trust one, the vector/community passes that run after facts land, and the guards that keep the "single writer" invariant honest in CI.

## What you'll find here

- [The invariant](#the-invariant-one-writer-ci-enforced) — why `apply_edge` is the only writer, and how that's enforced
- [`etl.py`](#etlpy--the-structured-acme-spine) — the deterministic structured-source ingest (MERGE/MATCH-SET, idempotent, zero LLM)
- [`etl_history.py`](#etl_historypy--session-history-ingest) — session-history ingest from engram / claude-mem / run-ledger
- [`mutate.py`](#mutatepy--the-sole-write-engine)  — the 5-axis mutation engine every writer calls
- [`staging.py`](#stagingpy--the-truth-gate-for-low-trust-sources)  — the candidate-stage + human-approval gate LLM-origin facts must pass through
- [`embed.py` + `demo_seed.py`](#embedpy--demo_seedpy--the-vector-rung) — populating the vector rungs
- [`communities.py`](#communitiespy--graphrag-communities) — Leiden/networkx community detection
- [The guards](#the-guards) — `invariant_check.py`, `cycle_check.py`, `tools/check_write_gateway.py`, `tools/run_guard.py`
- [Maintenance](#maintenance) — `sweep.py`, `retention_sweep.py`, `rollback.py`
- [`stamp.py`](#stamppy--reading-what-mutate-wrote) — the read-side consumer of the bi-temporal state the write path produces

---

## The invariant: one writer, CI-enforced

`mutate.apply_edge` (`01-context/src/mutate.py:54`) is the **sole sanctioned entrypoint** for writing a current `RELATES_TO` edge. Every current edge-write path in this repo — the structured spine, the session-history corpus, the reviewer-approved staging promote step — ends at a call to `apply_edge`. Nothing else is allowed to hand-write a current edge. (Node/content/chunk/community/embedding writes don't go through `apply_edge` at all — it's an edge-only gateway; OCR ingest, for instance, only calls `upsert_entity`/`embed.embed_node` and never touches it.)

This is **application-enforced, not database-enforced**: Neo4j Community can't express a constraint like "exactly one current edge per (subject, relation, namespace)" — that's a predicate over a query result, not a key. So the guarantee is really "single writer at the app boundary + continuous detection," not "the database physically prevents a second current edge" (`mutate.py:75-83`). Three things back that guarantee up:

1. **`tools/check_write_gateway.py`** — a CI-gated static scan that fails the build if any file outside an allowlist hand-writes a `RELATES_TO` pattern near a `CREATE`/`MERGE` verb, or imports/calls `mutate.apply_edge`/`mutate.resolve_entity` outside a second allowlist of known legitimate callers.
2. **`invariant_check.py`** — a read-only graph-wide sweep that fails loudly if any arity:1 relation ever ends up with >1 current edge.
3. **`cycle_check.py`** — the same idea for the acyclic (`graph_invariant`) relations: fails if a current cycle exists.

Two are CI gates on the write *code*; the other two are runtime sweeps over the write *result*. Together they're the whole enforcement story — see [The guards](#the-guards) below.

---

## `etl.py` — the structured ACME spine

`01-context/src/etl.py` is the zero-LLM ingest for issue-tracker-shaped structured state (agents, projects, repos, issues) — labelled **D1_SPINE** in its own selftest output. `fetch_source()` (`etl.py:15`) is currently a fixture standing in for a live tracker API; swapping it for a real client is meant to be the only thing that changes.

**Two-phase ingest** (`etl.py:93` `ingest()`):
- **Phase 1 — entities, one transaction.** `upsert_entities` (`etl.py:79`) calls `upsert_entity` (`etl.py:32`) for every agent/project/repo/status/issue. This is a `MERGE ... ON CREATE` that sets `namespace` once and never again — a re-ingest of an existing key under a *different* namespace raises `ValueError` (`etl.py:59-61`) rather than silently moving ownership. `content_rev` only bumps and `dirty` only flips when the content actually changed (a `WITH n, (... <> $short OR ... <> $long) AS changed` pre-SET snapshot at `etl.py:50`), so an identical re-ingest is a true no-op — idempotency by construction, proven in `etl.py:main()`'s `rev1 == rev2` assertion.
- **Phase 2 — edges, one transaction *per edge*.** `edge_specs()` (`etl.py:64`) is a pure function producing every `(label, subject, rel, object, namespace)` tuple the source asserts — no writes, just data, so `ingest()` can apply each fact in its own isolated transaction. Each edge goes through `mutate.apply_edge` (`etl.py:116`). A structural reject (arity violation, cycle, etc. — anything `ValueError`) is collected into a **dead-letter list** and skipped, so one bad fact never rolls back the batch; a genuine infra error (`neo4j.exceptions.*`) is deliberately *not* caught and halts the run (`etl.py:99-120`).

This makes phase 2 non-atomic by design: a mid-phase halt leaves earlier edges committed. That's fine because every write is idempotent — a re-run converges to the same state.

### G2: OCR ingest (additive, embedded at ingest)

`ingest_ocr_doc()` (`etl.py:154`) is a separate, additive path: OCR a rasterized page (`ocr_adapter.extract()`), `upsert_entity()` the text as a `:Document`, then immediately call `embed.embed_node()` so the node lands with `n.embedding` set — no dirty-then-sweep round trip. It creates one entity node and zero `RELATES_TO` edges, so it never touches the structured ETL flow. `_g2_ocr_serve_selftest()` (`etl.py:190`, run via `--g2-selftest`) proves the node is retrievable through the *real* `serve()` vector rung, not a manual bypass query — this is the "OCR now embedded at ingest, retrievable via `serve()`" capability the roadmap calls **G2, CLOSED** (`docs/ROADMAP.md`, "G2 — Multimodal RAG").

---

## `etl_history.py` — session-history ingest

`01-context/src/etl_history.py` ingests three configured local sqlite/jsonl history sources — two sqlite observation stores and two JSONL ledger files, each path env-overridable with a local-dev default — into one dedicated `history` namespace. Same convention as `etl.py`: zero LLM, pure `sqlite3`/`json`/`re` reads plus `mutate.py` writes.

Everything groups under a `:Entity:Project` node (`project:<canon_project(name)>`) via one relation, `PART_OF` (arity:1, `overflow_policy: reject` — a project reclassified between runs dead-letters rather than silently re-anchoring; `etl_history.py:10-12`). `canon_project()` (`etl_history.py:50`) collapses casing/spacing variants of a project name to one key.

**Read-then-write shape**: `_real_engram_rows()` / `_real_claude_mem_rows()` (`etl_history.py:57`, `:80`) open the *live*, other-process-owned sqlite DBs read-only (`?mode=ro`, `timeout=5.0` busy-wait, one bounded retry on "locked"). `_parse_ledger_lines()` (`etl_history.py:108`) dead-letters one corrupt JSONL line instead of aborting the whole read.

**`ingest()`** (`etl_history.py:224`) resolves every `Observation`/`Source`/`Project` entity via `mutate.resolve_entity` in one transaction (upsert has no reject axis, so it can't roll back on a rejected fact), then applies each `PART_OF` edge via `mutate.apply_edge` — one transaction per edge, same dead-letter idiom as `etl.py`. `_resolve_embeddable()` (`etl_history.py:209`) adds content-change detection on top of `resolve_entity`: it reads the prior `long_context` first and only calls `mutate.mark_dirty` if the text actually changed, so the embed-resume filter (below) doesn't miss a real edit but also doesn't false-positive on an identical re-ingest.

Positional keys (`ledger:<i>` / `runledger:<i>`) are derived from the **post-dead-letter-filter** index (`_filter_ledger_records()`, `etl_history.py:192`), shared between `ingest()` and the `--real` retrieval proofs, so the two can never desync on which index names which record.

`_embed_history_nodes()` (`etl_history.py:284`) is the embed-the-corpus pass for this namespace: by default it only embeds nodes with `n.embedding IS NULL OR n.dirty=true` (the resume filter); `--reembed-all` bypasses it for an embedding-model swap or chunking change.

---

## `mutate.py` — the sole write engine

`01-context/src/mutate.py` reads `01-context/schema/relations.yaml` (the ONTOLOGY_SCHEMA §10 5-axis contract) and picks parameterized Cypher per relation instead of hand-coding each call site. Three functions:

- **`resolve_entity`** (`mutate.py:32`) — idempotent `MERGE` of a keyed entity. `content_rev` starts at 0, `dirty` is cleared **ON CREATE only** (a resolve never clobbers a concurrent `mark_dirty`), and `namespace` is likewise set on create only — same ownership-never-moves-silently rule as `etl.py`'s `upsert_entity`.
- **`apply_edge`** (`mutate.py:54`) — add/remove a fact edge per a relation's rule from `relations.yaml`. `relations.yaml` *declares* the full 5-axis contract (**arity**: 1/inf, **overflow_policy**: evict/reject/coexist/aggregate, **verbs**: add vs add+remove, **temporal**: static/bi-temporal/windowed, **contradiction**: structural/`graph_invariant`/numeric/semantic), but `apply_edge` only *implements* a subset today: arity 1/inf, overflow `evict`/`reject` (coexist/aggregate aren't coded), verbs add/add+remove, temporal static/bi-temporal (windowed isn't coded), and the `graph_invariant` cycle guard (numeric/semantic contradiction resolution isn't coded). See `01-context/ONTOLOGY_SCHEMA.md` §10 for the full axis design and §6 for the per-relation table; `relations.yaml` is the machine-readable version this engine partially reads.
- **`mark_dirty`** (`mutate.py:165`) — content edit → bump `content_rev`, set `dirty=true` (the sweep trigger; see [Maintenance](#maintenance)).

### Arity, overflow, and the collision rule

For an **arity:1** relation (e.g. `ASSIGNED_TO`, `HAS_STATUS`, `PART_OF`):
- `overflow_policy: evict` — a new edge **supersedes** the current incumbent (functional re-anchor): the old edge's `invalid_at` is set to `now`, tagged `supersede_kind` (`correction` on a `static` relation, `validity` on bi-temporal) (`mutate.py:120-125`).
- `overflow_policy: reject` — a *different* current object is a **collision**, and the engine raises `ValueError` rather than guess which incumbent to replace (`mutate.py:126-132`, "the engine must never guess"). This is what makes `etl_history.py`'s reclassify-between-runs case dead-letter instead of silently re-anchoring.

For **arity:inf** (additive) relations like `BLOCKS`, there's no overflow axis to apply — the edge just accumulates via `MERGE`.

### FIX-RACE: the write-lock

Any arity:1 add takes an exclusive write-lock on the subject node first (`SET s._wlock=$now`, `mutate.py:117-119`) — pure write, no read-upgrade deadlock — so concurrent writers *through this engine* serialize into exactly one current edge. This only covers arity:1 writes on one subject; it does **not** cover multi-subject cycles (that's what `cycle_check.py` backstops).

### Bi-temporal supersession and resurrection

A current edge always carries `invalid_at = SENTINEL` ("9999-12-31T00:00:00Z") — never absent. Supersede/remove sets `invalid_at = now`. Re-adding a previously-removed (or evicted-away) edge **resurrects** it rather than duplicating: the final `MERGE` in `apply_edge` (`mutate.py:138-146`) matches the dead edge by key and clears its end-fields. `current_targets` / `edge_state` read `invalid_at > datetime()` to determine currency.

**Cycle guard** (`resolution: graph_invariant`, e.g. `DEPENDS_ON`, `SUPERSEDES`): before adding, `apply_edge` checks whether the new edge would close a directed cycle over *current, same-namespace* edges of that relation, and raises if so (`mutate.py:108-115`). This is a read-then-write check inside one transaction — it can't catch a TOCTOU race between two concurrent transactions each adding one leg of a would-be cycle; `cycle_check.py` is the periodic whole-graph backstop for exactly that gap.

**Namespace scoping**: edge *relationship* matches in `apply_edge` are scoped by `namespace` — a write in namespace A structurally cannot touch the same relation in namespace B. Endpoint matching is a separate story: the final resurrection `MERGE` (`mutate.py:138`) matches both endpoint nodes by `key` only — it does **not** enforce which namespace owns them. `apply_edge` will happily splice an edge onto an endpoint owned by a different namespace if a caller hands it one; enforcing endpoint ownership is the caller's job (see `staging.promote()`'s precondition check, below). `mutate.demo()` (`mutate.py:211`) exercises all of this (resolve idempotency, functional supersede, additive coexist, remove+resurrect, verbs-forbid-remove, dirty-flag, arity:1 reject, cycle guard, `set_snapshot` reconciliation, and cross-namespace isolation) against a throwaway namespace.

`apply_set_snapshot` (`mutate.py:149`) is the set-valued reconciliation mechanism (e.g. `OWNS`): diff current vs desired object set, `apply_edge(..., op="add")` the missing ones, `op="remove"` the extra ones.

---

## `staging.py` — the truth-gate for low-trust sources

`mutate.apply_edge` validates **structure** (relation exists, arity respected, no cycle) — it says nothing about **truth**. If an LLM extractor called `apply_edge` directly, a well-shaped hallucination would land in the graph exactly like a real fact. `01-context/src/staging.py` is the gate that sits in front of any low-trust source.

**The core invariant**: candidates are `:Candidate` **nodes** — never `:Entity`, never a `RELATES_TO` edge. Every existing reader (`serve`, the retrieval ladder, `node_card`, `invariant_check`, `cycle_check`) matches on `:Entity` + `RELATES_TO`, so a pending candidate is *structurally invisible* to every read path. No promote, no edge, nothing to see (`staging.py:10-12`).

- **`stage()`** (`staging.py:48`) — `MERGE`s one `:Candidate` node keyed by a deterministic `cand_id = sha1(json.dumps([ns, s_key, rel, o_key, origin]))` (JSON, not a bare `'|'`-join, so a field containing `|` can't shift a boundary and collide with a neighboring tuple — `staging.py:20-22`). `status`/`staged_at` are set `ON CREATE` only, so a re-stage is idempotent and never resets an already-reviewed candidate.
- **`stage_llm()`** (`staging.py:66`) — the `origin='llm'` entrypoint. It is **write-incapable by construction**: it holds no reference to `mutate.apply_edge`, so an ingest entrypoint that only calls `stage_llm` cannot create an edge, full stop.
- **`approve()` / `reject()`** (`staging.py:88`, `:112`) — reviewer-intended status transitions (`pending → approved`, `pending/approved → rejected`). The functions themselves have no auth/human check baked in — they only validate candidate state and CAS-lock the node; enforcing that a human (not a script) is the caller is a policy layered on top by whatever invokes them (e.g. `staging.py`'s CLI, below). Both lock the candidate first (`c._plock`) so concurrent approve/reject/promote calls on the same `cand_id` serialize, and both raise `ValueError` — never a silent no-op — if the candidate is missing or in the wrong state.
- **`promote()`** (`staging.py:137`) — the **only** function that writes an edge, and it does so by delegating to `mutate.apply_edge` (`staging.py:184`). Before calling it, `promote` rejects any candidate whose endpoints are missing or owned by a namespace other than its own or `'shared'` (an `OPTIONAL MATCH` + ownership check that raises `ValueError`, `staging.py:174-178`) — otherwise a candidate staged in namespace A could splice an edge onto entities owned by an unrelated namespace B, turning the gate into a namespace-isolation bypass. Only after that precondition passes does it call `apply_edge`, then re-verify the edge actually materialized via `mutate.edge_state` as a defensive postcondition before flipping the candidate to `promoted` — this second check exists because `apply_edge`'s resurrection `MATCH` still needs both endpoints to have been *resolved at all*; if either wasn't, the `MATCH` silently finds nothing, `apply_edge` writes nothing, and `promote` raises so the whole transaction rolls back and the candidate stays `approved`, never falsely `promoted`.

`tools/check_write_gateway.py` stays green against this file specifically because it hand-writes zero `RELATES_TO` edges — its own `_edge_count`/`_total_rel` selftest helpers are plain `MATCH` reads.

### Batch operations

`batch_approve` / `batch_reject` / `batch_promote` (`staging.py:222-258`) are thin loops over the existing per-candidate CAS-locked `approve`/`reject`/`promote` — no new locking primitive, no new edge-write path. Each requires a non-empty `batch_id` (an empty one would operate graph-wide, and is refused). A per-candidate `ValueError` (wrong state, lost race) is collected as an error entry rather than aborting the rest of the batch — the same dead-letter idiom `etl.py`/`etl_history.py` use.

`staging.py`'s CLI (`staging.py:606`) exposes `list` / `approve <id>` / `reject <id> <reason>` / `promote <id>` for a human reviewer.

---

## `embed.py` + `demo_seed.py` — the vector rung

`01-context/src/embed.py` embeds intrinsic node content locally with **EmbeddingGemma-300M** (768-dim, `$0`, no external API — `MODEL = "google/embeddinggemma-300m"`, `embed.py:23`). `embed_node()` (`embed.py:77`) is used by OCR ingest (`etl.ingest_ocr_doc`), demo seeding (`demo_seed.embed_all`), the freshness sweep (`sweep.py`), and `etl_history.py`'s dedicated history-embedding pass — **not** by structured `etl.ingest()`, which applies edges and returns without embedding inline (see [`etl_history.py`](#etl_historypy--session-history-ingest) above for its separate embed pass). Once a node reaches `embed_node()`:

- Content is chunked by kind — `chunk_prose()` (overlapping sentence windows) or `chunk_code()` (one chunk per top-level `def`/`class`, via `ast.parse`) — and `detect_kind()` (`embed.py:56`) auto-classifies which chunker to use.
- The whole-node vector, chunk text array, `chunk_count`, and freshness stamps (`embedded_at`, **`embedding_model`**, `embedded_content_rev`, `dirty=false`) are written onto the `:Entity` node.
- When a node splits into >1 chunk, each chunk is *also* embedded and materialized as its own `:Chunk` node, linked `(:Entity)-[:HAS_CHUNK]->(:Chunk)`, searchable via a separate `chunk_embedding` HNSW index (rung 2b, "which passage" vs rung 2's "which node"). A single-chunk node gets no `:Chunk` child.
- `assert_chunk_namespace_isolation()` (`embed.py:116`) is the structural proof that every `:Chunk` and its `HAS_CHUNK` edge carry the same namespace as the parent — never a cross-namespace leak.

`01-context/src/demo_seed.py` is the bridge between the structured `etl.ingest()` spine (which never embeds) and the embedding-path demos: `seed_extras()` (`demo_seed.py:62`) idempotently adds a handful of bare entities the ladder/serve demos structurally need (a finance-namespace isolation node, a long-doc node carrying a real `pageindex_doc_sha`, two multi-sentence "runbook" docs in different namespaces for chunk-recall proofs) — no hand-written `RELATES_TO`, so the write-gateway gate is untouched. `embed_all()` (`demo_seed.py:117`) then embeds every content-bearing `:Entity` in the graph, detecting kind per-node via `embed.detect_kind`.

---

## `communities.py` — GraphRAG communities

`01-context/src/communities.py` runs Leiden (via `leidenalg`/`python-igraph`, `_leiden_partition`, `communities.py:20`) or a `networkx` `greedy_modularity_communities` fallback (`_nx_partition`, `communities.py:45`) **per namespace**, over the intra-namespace subgraph only. `build_communities()` (`communities.py:158`) pulls the subgraph with a query that requires `a.namespace = b.namespace = r.namespace = $ns` — cross-namespace edges are structurally excluded before the algorithm ever runs, not filtered after. `now` is a required-explicit argument (raises if omitted) — no wall-clock-ambient writes.

Each `:Community` node and `:IN_COMMUNITY` membership edge carries `namespace`; `assert_no_cross_namespace_community()` (`communities.py:293`) is the structural proof that no community ever mixes members from two namespaces, checking both the node's own namespace field *and* every membership edge's namespace (a hollow check that only looked at node namespace missed a wrong-namespace edge — see the T10 selftest cases at `communities.py:535-577` that plant and catch exactly that). Summarization (`_summarize_community`, `communities.py:124`) is optional and off by default (`SUMMARY_CMD` unset ⇒ detection-only, `$0`).

---

## The guards

Three mechanisms enforce the "`apply_edge` is the only writer" invariant. One is a CI-gated static scan over source; two are runtime sweeps over the graph.

| Guard | Type | Catches |
|---|---|---|
| `tools/check_write_gateway.py` | static, CI-gated | any top-level `*.py` file in its fixed `SCAN_DIRS` list (outside an allowlist) that hand-writes a `RELATES_TO` pattern near `CREATE`/`MERGE`, or imports/calls `mutate.apply_edge`/`resolve_entity` outside a known-caller allowlist |
| `01-context/src/invariant_check.py` | runtime sweep, CI-gated + periodic ops | any arity:1 relation with >1 current edge per (subject, relation, namespace) — i.e. a writer bypassed `apply_edge`'s serialization |
| `01-context/src/cycle_check.py` | runtime sweep, CI-gated + periodic ops | a current directed cycle, up to `MAX_CYCLE_LEN=12` hops, over `graph_invariant` relations (`DEPENDS_ON`, `SUPERSEDES`) — the TOCTOU gap the per-add cycle guard in `apply_edge` can't close alone (that online guard is unbounded; this sweep trades tail-coverage past 12 hops for cost) |

`check_write_gateway.py` is a heuristic regex scan, explicitly **not** a parser (`check_write_gateway.py:9-14`), and it only walks top-level `*.py` files in a fixed `SCAN_DIRS` list — nested files, non-Python source, and Cypher/Markdown are out of scope. A write split across more than 3 source lines, or an ad-hoc cypher-shell session, could still evade it. That's why it's paired with the two runtime sweeps — the static scan is the cheap first line, the sweeps are the authoritative backstop. Both `invariant_check.py --self-test` and `cycle_check.py --self-test` prove the guard actually fires by planting a real violation in an isolated namespace, asserting it's caught, then cleaning up — so the CI gate isn't tautologically green against an always-clean seed.

`tools/run_guard.py` is adjacent guard infrastructure, not itself one of the three write-gateway mechanisms above: it's a generic `.cypher` runner that fails the process if a guard file "returns rows only on violation" (rows-on-violation) query returns rows — it doesn't know anything about `apply_edge` or the write-gateway invariant specifically, it just gives any rows-on-violation `.cypher` guard (like the sentinel-migration guard) teeth to actually fail CI instead of printing rows nobody checks.

`tools/apply_cypher.py` is the adjacent schema-DDL applier (`CREATE CONSTRAINT`/`CREATE INDEX IF NOT EXISTS` from `01-context/schema/*.cypher`) — not part of the write-gateway story, but `run_guard.py` reuses its statement splitter.

---

## Maintenance

- **`sweep.py`** — the freshness sweep. A content edit sets `n.dirty=true` (`mutate.mark_dirty`); `sweep_once()` (`sweep.py:30`) re-embeds up to `batch` dirty nodes and clears the flag. It's deliberately **0-hop**: only the edited node is re-embedded, never its neighbors, because embeddings here are intrinsic-content-only (no GraphSAGE-style neighbor aggregation), so an edge change can't change a neighbor's vector (ONTOLOGY_SCHEMA §11). `sweep_queue_depth()` (`sweep.py:21`) is a liveness metric — dirty-node backlog count + an alarm flag above `QUEUE_ALARM_THRESHOLD=1000`, so a cold dirty node can't silently rot unnoticed.
- **`retention_sweep.py`** — a bounded historical-edge retention sweep. Because `apply_edge` invalidates rather than deletes, every superseded edge lives forever by default. `measure()` (`retention_sweep.py:24`) reports current vs historical `RELATES_TO` volume; `prune()` (`retention_sweep.py:34`) deletes historical edges older than a cutoff — **current edges are never touched** (their `invalid_at = SENTINEL` excludes them from the `<= now` predicate). Dry-run is the default; `--apply --before <ISO>` is required to actually delete anything. The retention window itself is explicitly a **founder policy decision** (audit/compliance tradeoff vs storage cost), never a default (`retention_sweep.py:12-14`).
- **`rollback.py`** — namespace-scoped wipe + orphaned-`:Candidate` sweep, for cleanly re-ingesting a namespace during dev. `_require_ns()` (`rollback.py:48`) refuses an empty, `'shared'`, wildcard, or non-identifier namespace — every destructive op needs an explicit namespace, no default. `rollback_namespace()` (`rollback.py:94`) is dry-run by default; `--apply` is required, and preview and apply share one delete-set definition (`_DELSET`, `rollback.py:72`) so the dry-run count can never understate what `--apply` actually removes. `sweep_candidates()` (`rollback.py:136`) finds `:Candidate` nodes whose endpoints are missing or not owned by the target namespace/`shared` (reusing `staging.promote()`'s own ownership-check definition, rather than inventing a second one — so an endpoint owned by a different non-shared namespace counts as an orphan too, not only a never-resolved one) and removes them.

---

## `stamp.py` — reading what `mutate` wrote

`01-context/src/stamp.py`'s production read helpers (`stamp_card`, `freshness_judge`, `action_gate`, `card`) are **read-side only** — they write nothing — and are the direct consumers of the bi-temporal state `apply_edge` produces, so they belong in this map. The module also carries `plant_supersession()` and a `demo()` fixture, which write through `mutate`/entity-resolution to set up test scenarios — those are test/demo scaffolding, not part of the production read path. It extends a node card with two independent axes per fact: **validity** (`current`/`historical`, derived from `invalid_at`) and **fresh** (`fresh`/`stale`, derived from the source node's `dirty` flag). `freshness_judge()` (`stamp.py:41`) drops historical facts; `action_gate()` (`stamp.py:46`) refuses to act on anything not both current *and* fresh. The two axes are deliberately never collapsed into one confidence scalar — a fact can be current-but-stale (node edited, edge still valid) or historical-but-clean, and those are different failure modes.

---

## Source of truth

This doc summarizes and cross-links; the code is the ground truth:

- `01-context/src/etl.py`
- `01-context/src/etl_history.py`
- `01-context/src/mutate.py`
- `01-context/src/staging.py`
- `01-context/src/embed.py`
- `01-context/src/demo_seed.py`
- `01-context/src/communities.py`
- `01-context/src/invariant_check.py`
- `01-context/src/cycle_check.py`
- `01-context/src/sweep.py`
- `01-context/src/retention_sweep.py`
- `01-context/src/rollback.py`
- `01-context/src/stamp.py`
- `01-context/src/scope.py` (documents the role → namespace slice design; `staging.py` and `rollback.py` don't import it — they currently duplicate/enforce their own namespace rules inline, `staging.py` hardcoding "candidate namespace or `'shared'`" and `rollback.py`'s `_require_ns()` using its own regex + explicit refusals)
- `tools/check_write_gateway.py`
- `tools/run_guard.py`
- `tools/apply_cypher.py`
- `01-context/schema/relations.yaml`

## See also

- [`01-context/ONTOLOGY_SCHEMA.md`](../01-context/ONTOLOGY_SCHEMA.md) — the canonical ontology + the full 5-axis relation design (§10), the per-relation rule table (§6), namespace/ACL design (§7), and the embedding-staleness resolution (§11) that `sweep.py` implements.
- [`01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md`](../01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md) — the retrieval-side design (the ladder, `serve()`) that reads what this write path produces.
- [`01-context/RETRIEVAL.md`](../01-context/RETRIEVAL.md) — retrieval mechanics in more depth.
- [`01-context/SERVE_JOIN_DESIGN.md`](../01-context/SERVE_JOIN_DESIGN.md) — the serve-join design referenced from the retrieval side.
- [`01-context/PAGEINDEX_PILOT.md`](../01-context/PAGEINDEX_PILOT.md) — the long-doc / PageIndex pilot that `demo_seed.py`'s `extsrc:context-evals` node feeds.
- [`docs/ROADMAP.md`](ROADMAP.md) — current status: **G1 (agentic RAG) CLOSED**; **G2 (multimodal/OCR) CLOSED** — OCR is embedded at ingest (`etl.ingest_ocr_doc` → `embed.embed_node`) and retrieved through the live `serve()` vector rung, default stays OCR-first (not vision/ColPali); **G3 (calibration/autonomy) OPEN and founder-gated** — `01-context/src/abstain.py`'s `CALIBRATED` defaults `False` and no production code grants a lease, so autonomy stays off on two independent counts: the public case-study run fit the sufficiency proxy with a **negative** weight (see `03-evals/CASE_STUDY_calibration.md`), and the latest measured run fit a **positive** refit weight but still failed the selective-gain check (−3.0pp) (`docs/ROADMAP.md`). The write path this doc describes is unaffected by G3: every fact that lands in the graph, whether via `etl.py`, `etl_history.py`, or a promoted `staging.py` candidate, goes through the same deterministic, non-autonomous `apply_edge`.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — the project-wide ground rules this doc's invariant restates in miniature: "never let an LLM write a fact," "namespace on node *and* edge," "bi-temporal by default."
