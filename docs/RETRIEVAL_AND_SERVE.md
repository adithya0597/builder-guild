# Retrieval and Serve — the query→answer path

One sentence: `serve()` (`01-context/src/serve.py`) takes a question + a role, runs it through a
multi-rung retrieval ladder, fuses and epistemically orders the hits, reconciles them against
bi-temporal graph state, and hands the result to a faithfulness gate that decides `pass` /
`partial` / `abstain` / `escalate` — never executing an action unless a namespace has been
explicitly leased (it hasn't; see [Gate state](#gate-state-suggest-only-not-a-shipped-claim)).

## What you'll find here

A navigable map of the 11 modules that make up the retrieval/serve path — what each one owns,
how they wire together, and where the SHIPPED code ends and the ROADMAP begins. This doc
summarizes and cross-links the deeper design docs (`HYBRID_RETRIEVAL_ARCHITECTURE.md`,
`SERVE_JOIN_DESIGN.md`, `PAGEINDEX_PILOT.md`, `RETRIEVAL.md`) rather than repeating them — read
those for the "why we chose this" reasoning; read this for "what runs, in what order, calling
what."

## The pipeline, end to end

```
query_text, role, [pattern], [action], [as_of], [deep_serve], [rerank]
        │
        ▼
  scope.scope(role)              → allowed namespaces + role T-cap (serve.py:244)
        │
        ▼
  ┌─────────────────────────── LADDER (ladder.py) ───────────────────────────┐
  │  keyword_rung   — exact-ID / literal token match (deterministic)         │
  │  graph_rung     — structural MATCH on a caller-supplied {rel,obj} pattern│
  │  vector_rung    — node-level ANN recall (EmbeddingGemma + Neo4j HNSW)    │
  │  chunk_rung     — passage-level ANN recall ("which passage", cf7)        │
  └───────────────────────────────────────────────────────────────────────────┘
        │  (serve.py runs keyword+graph+vector+chunk SEQUENTIALLY, one after another,
        │   before fusion — NOT ladder.retrieve()'s first-hit escalation; see below)
        ▼
  A2 embed-model guard — drop any vector/chunk hit stamped with a stale embedding_model
        │
        ▼
  fuse.rrf()  — Reciprocal Rank Fusion, k=60, SOURCE_PRIORITY tie-break
        │
        ▼
  [optional] fuse.cross_encoder_rerank()  — rerank=True only, default OFF
        │
        ▼
  stamp.CARD_Q + reconcile.reconcile()  — primary node's bi-temporal card
        │
        ▼
  serve-join: coverage check → optional PageIndex deep drill (deep_serve=True only)
        │
        ▼
  evidence.from_graph() / evidence.from_pageindex()  → epist.weights_for(role) ordering
        │
        ▼
  claims[] built from the authority-ordered merged set
        │
        ▼
  abstain.stage_a_decision()  →  gate.gate()  →  pass | partial | abstain | escalate
        │
        ▼
  abstain.execute()  — suggest-only unless CALIBRATED[role] is True (it never is, today)
        │
        ▼
  result dict: {primary, presentable_facts, composed_evidence, decision, mode, executed,
                provenance, trace, commit_id, snapshot_id, audit_id}
```

---

## `serve.py` — the serve contract

`01-context/src/serve.py` (1069 lines) is the one function everything else routes through:
`serve(query_text, role, pattern=None, action=None, deep_serve=False, rerank=False,
include_communities=False, as_of=None)` (`serve.py:213`).

### The response envelope

Every call — including the no-retrieval early return — carries the same base envelope keys
(`serve.py:600-608`, `314-323`); the no-retrieval branch returns before fuse/epist/stamp/gate ever
run, so its `trace` only holds whatever stages ran before that early return (`retrieve`, plus
`communities` when `include_communities=True`) — not the full per-stage set below:

| Key | What it is |
|---|---|
| `primary` | the top-fused node key (or `None` on a miss) |
| `presentable_facts` | current, in-scope graph facts for the primary card |
| `composed_evidence` | the wider answer surface — content + facts across the top-K fused cards, 1-hop expansion, plus any PageIndex augmentation |
| `decision` / `mode` / `executed` | the gate's verdict, suggest-vs-autonomous mode, whether anything actually ran |
| `provenance` | `{key: source}` map (keyword/graph/vector/chunk) |
| `trace` | full per-stage diagnostics (retrieve/fuse/epist/stamp_reconcile/gate_abstain/serve_join/…) |
| `commit_id`, `snapshot_id`, `audit_id` | the **A1 reproducible read envelope** (see below) |

**A1 envelope** (`serve.py:19-39`, `249-258`): `commit_id` is resolved once at import — `git
rev-parse HEAD`, or the `BG_COMMIT_ID` env override for deployed artifacts without a `.git` dir,
degrading to `"unknown"` on failure rather than breaking CI. `snapshot_id` is the temporal cut —
`as_of` if given, else the literal string `"current"`. `audit_id` is a deterministic sha256 of
`commit_id | snapshot_id | query_text | role | pattern | as_of | deep_serve | rerank |
include_communities | action` (`serve.py:255-258`) — same call args reproduce the same audit_id;
a different `action` changes the decision downstream, so it's folded into the hash too. This is
**not** a per-call UUID or clock reading — it's built to be reproducible across identical calls
(exercised in `_demo()`'s A1 block, `serve.py:647-676`).

### `as_of` — temporal reads

`_validate_as_of()` (`serve.py:58-70`) is the single Python-boundary check every `as_of`-taking
entry point funnels through — an ISO-8601 parse via `datetime.fromisoformat`, raising a clean
`ValueError` instead of leaking a raw Cypher error. `NODE_CARD` (`serve.py:43-56`) and
`ladder.graph_rung` (`ladder.py:28-38`) both filter on `r.valid_at <= coalesce(datetime($as_of),
datetime()) AND r.invalid_at > ...` — `as_of=None` coalesces to "now," giving the same
current-only behavior as before temporal reads existed. `serve()`'s own `_demo()` plants a
supersession chain (`stamp.plant_supersession`) and asserts three time points return the right
fact (`serve.py:847-876`) — this is what backs the "who owned X on \<date\>" query.

### `role` is trusted input

`serve()`'s docstring is explicit: `role` must be authenticated upstream — a self-asserted
`role='governance'` would read every namespace (`serve.py:235-236`). It is never validated inside
`serve()` itself; namespace scoping comes entirely from `scope.scope(role)`.

### src-class provenance tags

`_src_class(kk)` (`serve.py:170-185`) maps a key's prefix to a provenance class for display:
`obs:`→`engram`, `cmobs:`→`claude-mem`, `ledger:`→`explore-ledger`, `runledger:`→`run-ledger`,
`extsrc:`/`doc:`→`doc`, and the structured-domain prefixes (`issue:`, `agent:`, `project:`,
`status:`, `community:`, `repo:`) → `graph`. **Unknown prefixes fail closed to `doc`**, never to
the highest-trust `graph` label. `_display_body()` (`serve.py:188-190`) escapes raw evidence text
(`\` and `[`/`]`) so only serve-owned brackets can render a `[fresh src:graph]`-style tag —
closing a forged-provenance-tag injection vector (`_demo()` asserts this at `serve.py:630`).

### A2 — embed-model-mismatch guard

An ANN hit stamped with an `embedding_model` other than the live embedder (`embed.MODEL`) sits in
an incomparable vector space — cosine scores across two models aren't commensurable. `serve.py`
filters these out of both `vec_hits` and `chunk_hits` (`serve.py:280-286`) via `_model_ok()`,
**drop-and-count, not raise** (a raise would break serve during a normal re-embed window). `NULL`
embedding_model is *not* treated as a mismatch — only ever one model has existed, so every legacy
node predates the stamp and is current-era by construction; only a **set-and-different** model is
dropped. `model_mismatch_dropped` is surfaced in `trace["retrieve"]` so the silent recall loss
stays observable. Proven live in `_demo()`'s A2 block (`serve.py:690-718`): a planted stale-model
node never leaks into `vec_hits`/`chunk_hits`, while a control node with the correct model does.

### abstain/decision integration

`serve()` builds `claims` from the epist-ordered merged evidence set (graph facts always
included; PageIndex sections only when a drill actually augmented) and calls
`abstain.stage_a_decision(claims, action, sufficiency, self_conf, role=role)` (`serve.py:592`),
then `abstain.execute(decision, ...)` (`serve.py:593`). See [`gate.py`](#gatepy--faithfulness--apc-decision) and
the [gate-state note](#gate-state-suggest-only-not-a-shipped-claim) below — this is where "suggest-only" is
actually enforced, not just labeled.

### Confidence basis — never fabricated

`self_conf` is explicit about its source (`serve.py:576-583`): if the primary is in `vec_hits`, use
its own cosine score (`conf_basis="vector_score"`); else if it's in `chunk_hits`, use its chunk
cosine (`"chunk_vector_score"` — not mislabeled as a graph-exact hit); otherwise — any primary with
neither a vector nor a chunk score, which includes a graph-only hit **and** a keyword-only hit —
falls back to `0.95` labeled `"graph_structural_exact"` (a structural MATCH is certain-by-
construction, not a pretend similarity score; the label is accurate for the graph case and a known
simplification for the keyword-only case).

### Sufficiency signal — `_support_coverage`

`_support_coverage()` (`serve.py:102-145`) is implemented and test-pinned as the deterministic
replacement for the old fact-count proxy (which fit with a **negative** weight — see
[Gate state](#gate-state-suggest-only-not-a-shipped-claim)). Coverage = the fraction of
question-named entity ids (`issue:`/`agent:` tokens or `ACME-1`-style patterns) that the
support facts actually cover, canonicalized (bare `ACME-1` vs prefixed `issue:ACME-1`) before
intersecting, support-gated (a node with zero presentable facts contributes nothing), capped at
1.0, and **0.0 with no count fallback** when the question yields no extractable ids. **G3 Item 2
acceptance stays OPEN**, though: a positive refit is not demonstrable on the public 10-item
example set, and the real refit + selective-gain check needs the larger validated V1 golden set
(founder-gated) plus a real judge sweep — until both land, the helper's existence doesn't close
the item.

---

## `ladder.py` — the retrieval rungs

`01-context/src/ladder.py` defines the four retrieval methods and one first-hit-escalation
entry point (`retrieve()`, used by `corrective.py` and standalone callers) that `serve()` does
**not** use directly — `serve()` runs the rungs sequentially, then fuses, instead (see
[Honest scope](#honest-scope-serve-vs-ladderretrieve) below).

| Rung | Function | What it does |
|---|---|---|
| **Keyword / exact-ID** | `keyword_rung(s, allowed, text)` (`ladder.py:14-25`) | Linear scan of in-scope node keys against query tokens (a key or its post-prefix tail literally appearing in the query). Fixes the lexical-semantic trap where "what does ACME-2 block" embeds near "status=blocked" cards instead of ACME-2 itself. Fact-authority, not fuzz. |
| **Graph / structural** | `graph_rung(s, allowed, pattern, as_of=None)` (`ladder.py:28-38`) | Instant Cypher `MATCH` on a caller-supplied `{rel, obj}` pattern, bi-temporally filtered (`valid_at`/`invalid_at`), all three sides (subject/edge/object) namespace-scoped. |
| **Vector (node-level)** | `vector_rung(s, allowed, text, k=3)` (`ladder.py:66-83`) | Embeds the query locally (EmbeddingGemma via `embed.embed`), queries the `node_embedding` HNSW index, post-filters to the role's namespace slice. Escalating over-fetch (`_vector_query`, `ladder.py:45-63`) defeats a recall cliff: a fixed `k*5` over-fetch can return `<k` in-scope hits under high namespace selectivity, so the fetch widens (`*5` each round) until enough in-scope hits surface or the whole embedded set has been scanned. Degrades to `[]` (not a crash) if `sentence_transformers` is absent — any *other* import failure propagates. |
| **Chunk (passage-level)** | `chunk_rung(s, allowed, text, k=3)` (`ladder.py:128-143`) | Same embed-and-ANN shape, but over `:Chunk` nodes (`chunk_embedding` index) — answers "which passage," not just "which node." Resolves each chunk hit to its parent entity, dedupes to the best-scoring chunk per parent (`_chunk_vector_query`, `ladder.py:90-125`), and fetches passage text only for the survivors (not the whole scan) — a scale fix so a high-selectivity scan doesn't drag every chunk's text across the wire. |

### A2 embed-model guard (ladder-side)

Both `vector_rung` and `chunk_rung` return each hit's `embedding_model`; the guard itself lives
in `serve.py` (see [above](#a2--embed-model-mismatch-guard)) — the ladder just carries the field
through so the caller can filter.

### Honest scope: serve vs `ladder.retrieve()`

`ladder.retrieve()` (`ladder.py:146-176`) is a **first-hit-escalation** ladder: graph rung fires
first (instant, no LLM); if it hits, return immediately; else try vector; else report the
PageIndex rung as gated (structural pointer only — the real drill lives in
`pageindex_adapter.py`). This mode is used by `corrective.py`'s rewrite probes and standalone
callers, not by `serve()`. `serve()` deliberately runs graph + vector + chunk **sequentially, all
before fusion** (never first-hit escalation) and lets `fuse.py` combine them — fusion needs
multiple sources, and first-hit escalation would short-circuit before a second source ever fires
(`serve.py:228-234` names this distinction explicitly). `chunk_rung` (2b) is not wired into
`retrieve()`'s escalation at all, because node-vector (rung 2) hits for almost any query — a 2b
branch there would be near-unreachable; chunk-vector recall only earns its keep in serve's
sequential-then-fuse path.

---

## `fuse.py` — RRF fusion + cross-encoder rerank

`01-context/src/fuse.py` — two stages, per `HYBRID_RETRIEVAL_ARCHITECTURE.md` §3.

**Stage 1 — `rrf(rankings, k=60)`** (`fuse.py:25-37`): Reciprocal Rank Fusion (Cormack & Clarke,
SIGIR 2009) — `score(d) = Σ_sources 1/(k + rank_source(d))`, rank-based and scale-free, so it
sidesteps normalizing BM25-style scores against cosine scores. Score ties are broken by
`SOURCE_PRIORITY` — `{"keyword": 0, "graph": 1, "vector": 2, "chunk": 3}` (`fuse.py:22`), an
explicit name-keyed map (not dict iteration order), then by `doc_id` for final determinism. This
replaced an earlier alphabetical-`doc_id` tie-break that silently discarded keyword authority
whenever a fuzzy vector hit's key happened to sort first (the RC2 regression, guarded by
`demo()`'s RC2 test block, `fuse.py:77-84`).

**Stage 2 — `cross_encoder_rerank(query, fused_docs, doc_text, model)`** (`fuse.py:40-46`):
re-scores the fused set by true `(query, passage)` relevance using a cross-encoder
(`ms-marco-MiniLM-L-6-v2` by default). **Available but opt-in** — `serve()` only invokes it when
called with `rerank=True` *and* `sentence-transformers` is importable (`serve.py:330-345`); the
model revision is pinned by SHA (`serve.py:341-342`) as a supply-chain guard. Default
`rerank=False` keeps `serve()` on the `$0` RRF-only path.

**`SOURCE_PRIORITY` and epist authority are related but cover different sets.** `fuse.py`'s
`SOURCE_PRIORITY` tie-break is `{"keyword": 0, "graph": 1, "vector": 2, "chunk": 3}` — the four
retrieval rungs. `epist.py`'s `DEFAULT_AUTHORITY` is `{"graph": 1.0, "pageindex": 0.7, "vector":
0.3, "community": 0.2}` — no `keyword`, no `chunk`; it adds `pageindex` and `community` instead,
because epist orders the *merged evidence* set (graph facts + PageIndex sections + community
summaries), not the raw per-rung rankings fusion works over. In the live gate path today, `serve()`
only ever builds `merged_items` from `graph_items + pageindex_items` (`serve.py:542-543`) — vector,
chunk, and community items don't feed epist ordering yet; `SOURCE_PRIORITY` is what breaks
vector/chunk ties earlier, within fusion's one ranked list.

---

## `evidence.py` — the canonical evidence shape

`01-context/src/evidence.py` defines `EvidenceItem` — one dataclass shape for graph facts, vector
hits, and PageIndex sections, so the serve-join path can normalize → epist-merge →
freshness-stamp → gate a single homogeneous set (`SERVE_JOIN_DESIGN.md` §1). v1 is deliberately
narrow: exactly 11 fields (`_V1_FIELDS`, `evidence.py:31-32`), every one populated by a real
producer — `evidence_id` is named for later, not a v1 field, so the runtime object never looks
more complete than it is (founder decision, 2026-06-17).

- **`from_graph(fact, namespace, node_id, validity, node_fresh)`** (`evidence.py:74-81`) — a
  stamped fact string → `EvidenceItem`. `retrieval_score=None` on purpose: a structural `MATCH` is
  certain-by-construction, not a similarity score.
- **`from_vector(node_id, namespace, score, text, node_fresh)`** (`evidence.py:84-87`) — carries
  the cosine score, `authority_hint="recall"`.
- **`from_pageindex(host_node_id, namespace, text, source_path, section_id, score=None,
  node_fresh="fresh", validity="current")`** (`evidence.py:90-98`) — a PageIndex section. **Freshness propagates from the host node**: a
  section drilled from a dirty or superseded long-doc node inherits `freshness_state="dirty"`/
  `"superseded"`, and `is_actionable()` (`evidence.py:51-56`) returns `False` — the gate then
  refuses to act on stale prose. This is the freshness-propagation safety case `evidence.py`'s
  `demo()` locks (`evidence.py:140-149`).
- **`DEEP_COVERAGE_TAU = 0.5`** (`evidence.py:23`) — the frozen trigger constant for the serve-join
  deep rung (below). **Labeled uncalibrated** — pending a coverage-vs-deep-benefit sweep. Both the
  private and public trees import this same constant so the escalation policy can't drift between
  them.

`authority_hint(method)` (`evidence.py:35-36`) is a fixed epistemic-role *hint* per method
(`keyword`/`graph`→`"fact"`, `pageindex`→`"prose"`, `vector`→`"recall"`, unknown→`"recall"`,
fail-safe) — a stable label, never a numeric weight; the actual per-role weighting is
`epist.weights_for(role)`.

---

## `epist.py` — multi-source epistemics

`01-context/src/epist.py` weights sources by epistemic role and resolves cross-source conflicts
structurally — authority first, then bi-temporal validity, zero LLM calls.

`DEFAULT_AUTHORITY = {"graph": 1.0, "pageindex": 0.7, "vector": 0.3, "community": 0.2}`
(`epist.py:21`), overridable per role via `ROLE_WEIGHTS` (`epist.py:22-26`) — e.g. `"comms"`
inverts the ordering so prose (`pageindex`) outranks structured facts, because a comms-facing
role cares more about narrative than raw graph state. `weights_for(role)` (`epist.py:29-30`)
looks this up, falling back to `_default`.

**`resolve_slot(claims, role)`** (`epist.py:33-51`) resolves conflicting claims for the *same*
slot: unanimous claims → `"agreement"`; otherwise rank by `(authority, validity-current-first)`
and take the top; a genuine tie (same authority, same validity) → `"SURFACE_conflict"` with
`value=None` — **never silently picked**. `epist.py`'s `demo()` walks four cases: structural
graph-wins, bi-temporal current-beats-historical, genuine-conflict surfaced, and per-role
re-weighting (`epist.py:59-101`).

**`resolve_slot` is NOT wired into `serve()`'s live path** (`serve.py:553-567` is explicit about
this): v1 scope defers cross-source conflict detection to v2, because a prior attempt
false-positived on additive same-relation multi-edges (e.g. `BLOCKS→A` and `BLOCKS→B` on the same
issue are co-valid, not conflicting) and produced false abstains. Every claim in `serve()`
currently carries `conflict: False`. What *does* run live is the **authority ordering** —
`merged_items = sorted(graph_items + pageindex_items, key=lambda it: -_w.get(it.retrieval_method,
0.0))` (`serve.py:542-543`) — which determines claim order into the gate, traced as
`merged_authority_order` (`serve.py:544-546`).

---

## `gate.py` — faithfulness + APC decision

`01-context/src/gate.py` ports the ai-product-council governance engine (VoteCalculator /
DecisionRouter / SycophancyDetector — "pure logic, zero model deps") into a single function:
`gate(claims, action, generator_self_confidence, requery=None)` (`gate.py:28-63`) → one of
`"pass"`, `"partial"`, `"abstain"`, `"escalate"`, with a reason string.

**Decision order — faithfulness before confidence, no citation, no claim:**

1. **One CRAG requery** on each `UNSUPPORTED` claim (`gate.py:35-36`) — if the caller supplies a
   `requery` function and it still can't support the claim, it's a hard violation.
2. **Hard faithfulness violation** (`unsupported | conflict | stale`) feeding the action
   (`gate.py:44-50`): if the action category is `security`/`irreversible`, or it isn't reversible
   → `escalate` (mandatory human); otherwise → `abstain`.
3. **Partial support, no hard violation** (`gate.py:52-56`): a reversible `routine` action →
   `partial` (answer partial, action withheld); anything riskier → `escalate`.
4. **All supported, clean** (`gate.py:58-63`): `security`/`irreversible` categories are a
   **categorical hard-stop** — `escalate` regardless of confidence (`CATEGORICAL_HUMAN`,
   `gate.py:25`); otherwise compare `confidence` against a per-category threshold
   (`THRESHOLD = {"routine": 0.50, "architectural": 0.67, "security": 0.80, "irreversible":
   0.90}`, `gate.py:24`) — `pass` if it clears the bar, else `escalate`.

All four output states (`pass`/`partial`/`abstain`/`escalate`) are exercised in `gate.py`'s
`demo()` test table (`gate.py:70-103`).

`serve()` invokes this indirectly through `abstain.stage_a_decision()`
(`abstain.py:71-89`), which runs the faithfulness hard-gate first (calling into `gate.gate()`
when a hard violation exists) and otherwise applies the sufficiency×confidence logistic
(`abstain.selective_score`, `abstain.py:52-54`) as the selective abstain mechanism validated
against the "Sufficient Context" paper (Google, ICLR'25) — never abstaining on low sufficiency
alone, since the paper found LLMs answer correctly 35-62% of the time even on insufficient
context.

---

## `reconcile.py` — per-card validity + freshness

`01-context/src/reconcile.py` keeps two axes orthogonal, never collapsed into one scalar
(`reconcile.py:1-24`):

- **edge validity** (`current`/`historical`) and **node freshness** (`fresh`/`stale`) are
  independent.
- a superseded fact never marks its node stale (freshness is node content, not any one edge).
- a dirty node never revalidates a superseded fact (validity is bi-temporal, not a vote).
- **presentable** = current facts only; superseded facts are **quarantined**, not silently
  dropped.
- **actionable** = current AND node-fresh AND no ambiguous functional relation — all three axes
  must pass.

`reconcile(node_fresh, facts, functional_rels)` (`reconcile.py:36-57`) returns the card stamp
`{node_fresh, presentable, superseded, n_current, n_superseded, ambiguous_functional,
actionable}`. `ambiguous_functional` is a read-side invariant guard: an arity-1 relation (e.g.
`ASSIGNED_TO`) showing more than one *current* edge is an upstream write-layer breach that should
be structurally impossible (sentinel + single-writer) — if one slips through, it's quarantined
rather than acted on (`reconcile.py:44-47`, `case4` in `demo()`).

`serve()` calls this once for the primary node's card (`stamp.CARD_Q` → `stamp.stamp_card` →
`reconcile.reconcile`, `serve.py:370-373`) — **sufficiency** is computed from this primary card's
facts only (`serve.py:588-589`); **claims** are built from `graph_items + pageindex_items`
(`serve.py:538-546`, `559-568`) — the primary card's facts always contribute, and a PageIndex
section becomes a gate claim too whenever a deep drill actually augmented. The wider
`composed_evidence` surface (multi-card, 1-hop expansion) stays presentation-only and never feeds
the gate (`serve.py:380-382`).

---

## `corrective.py` — bounded rewrite → re-retrieve loop

`01-context/src/corrective.py` wraps `serve.serve()`: `corrective_serve(query_text, role,
pattern=None, action=None, *, max_rewrites=2, web_fallback=False, _serve=None)`
(`corrective.py:182-332`) — `max_rewrites`/`web_fallback`/`_serve` are keyword-only; `_serve` is a
test-only injection point (defaults to `serve.serve`).
Recovery triggers **only** on `decision == "abstain"` — `pass`/`partial`/`escalate` terminate
immediately. Pure-Python deterministic rewrites, `$0`/local, no model calls.

Four rewrite tactics, tried in order, bounded by `max_rewrites` and a no-op guard (`tried` set of
`(query, pattern)` pairs):

1. **`id_extract`** (`corrective.py:122-126`) — pull ID-like tokens (`issue:`/`agent:` or
   `ACME-1`-style) and re-serve on just the ids.
2. **`pattern_synth`** (`corrective.py:128-143`) — map a verb (block/depend/own/assign) to an
   ontology relation, pick the object id positioned *after* the verb in the text (falling back to
   before-verb ids), and re-serve with `query_text=""` so only the graph rung fires — a clean
   structural match, sidestepping keyword noise from the original text.
3. **`neighbor_expand`** (`corrective.py:145-169`) — pull 1-hop neighbor keys from the prior
   result's `presentable_facts` (trusted graph edges, used ungated) plus any `issue:`/`agent:`
   tokens found in `composed_evidence` (untrusted prose) — **gated through the pdk forged-token
   guard** (below) before being used as a re-retrieval seed.
4. **`decompose`** (`corrective.py:171-179`) — strip stopwords, split on "and"/",", re-serve the
   stripped core.

Evidence is **unioned across all probes**, not first-hit-wins (`corrective.py:225-237`) — so an
answer that needs facts combined across decompose sub-queries can still surface even when no
single probe passes alone. Every probe re-asserts `trace.isolation.clean` (`corrective.py:212-214`,
`270-272`) — namespace isolation holds because every re-retrieve still routes through the same
role-scoped `serve()`.

### pdk — the forged-token guard

`composed_evidence` is untrusted prose (attacker-influenceable content cards / `long_context`) —
a forged `issue:`/`agent:` token embedded in it must never seed re-retrieval unless it names a
*real*, namespace-scoped entity. `_resolve_seed_tokens(keys, allowed)` (`corrective.py:100-115`)
enforces this: it re-checks each candidate token against `MATCH (n:Entity) WHERE n.key IN $keys
AND n.namespace IN $allowed`, keeping only survivors — mirroring `serve()`'s own isolation idiom.
`presentable_facts`-derived tokens (trusted graph edges) skip this check; only prose-derived
tokens are gated. Proven by `_pdk_selftest()` (`corrective.py:335-357`): a forged
`issue:FORGED-999` token never survives as a seed, while a real in-scope `agent:cto` token in the
same prose does.

### Web fallback (`web_fallback=True`)

Only runs when `resolved_at == "exhausted"` and the environment enables it
(`web_fallback_adapter.is_enabled()`). External web facts carry **no namespace**, so they are
never merged into the role-scoped answer — they're segregated into `web_advisory` (tagged
`external-unverified`) and re-graded through the *same* gate as `UNSUPPORTED` claims, so a
routine/reversible action still abstains and a risky one still escalates
(`corrective.py:294-322`). External evidence is advisory only; it never autonomously resolves an
in-scope query.

---

## `pageindex_adapter.py` — vectorless PageIndex drill

`01-context/src/pageindex_adapter.py` is the adapter contract for a fourth retrieval mode: LLM
tree-reasoning navigation over a document's table of contents, no embeddings involved
(`SERVE_JOIN_DESIGN.md` §2.3). `drill(allowed, query_text, t_cap) -> {resolved_at, answer, doc,
sections}` (`pageindex_adapter.py:144-174`).

**What's actually live in the public tree:**

- **The public stub** (default) — always returns `resolved_at="gated"`, zero external/LLM calls
  (`_GATED_RESPONSE`, `pageindex_adapter.py:42-51`). The real vendor PageIndex drill — an
  authenticated retrieval call against the vendor's hosted document trees — is excluded from this
  public tree; only the mechanism + interface contract ship here.
- **An opt-in *local* drill** (`PAGEINDEX_LOCAL_DRILL=1`, env read live per call, default OFF) —
  a real, un-stubbed mechanism: deterministic markdown-heading-tree parsing
  (`_build_tree`, `pageindex_adapter.py:76-111`) over an in-repo doc
  (`HYBRID_RETRIEVAL_ARCHITECTURE.md`), token-overlap section scoring, zero LLM/network calls.
  Honestly labeled `"mechanism": "local_toc_deterministic"` — **not** vendor PageIndex
  tree-reasoning and **not** the measured pilot in `PAGEINDEX_PILOT.md`. Honors the same
  namespace scope as `serve()` (the hardcoded host doc is namespace `shared`; out-of-scope
  callers get gated before any file I/O, `pageindex_adapter.py:166-172`).
- **Injection** (`_inject(fn)`) — the test/demo override that lets `serve()`'s own tests exercise
  the positive `resolved_at="pageindex"` path with zero external calls.

`serve()` only calls this adapter for the **deep rung** — the trigger signal (coverage below
`evidence.DEEP_COVERAGE_TAU`, a long-doc node in scope with a non-empty `pageindex_doc_sha`) is
*always computed and traced* (`serve.py:462-526`), but the real drill executes only when the
caller opts in with `deep_serve=True` — every existing caller stays `$0` and byte-identical to
before by default (the `$0` law, exercised by the tripwire assertions in `_demo()`,
`serve.py:728-766`). A drilled section's freshness **propagates from its host node** (see
[`evidence.py`](#evidencepy--the-canonical-evidence-shape)) — a confirmed-unconfirmable host drops
the section entirely (fail-closed, `serve.py:498-504`); a confirmed-dirty host still builds the
section but marks it non-actionable, tripping the faithfulness hard-gate.

---

## `ocr_adapter.py` + `summarize_adapter.py`

**`ocr_adapter.py`** (`01-context/src/ocr_adapter.py`) — `extract(image_path)` wraps the system
`tesseract` CLI via subprocess, zero Python OCR wrappers (no pytesseract/easyocr). Design choice
cited from Most et al. (arXiv:2505.05666, "Lost in OCR Translation?"): OCR-based retrieval
generalizes better to unseen/varying-quality documents than vision-native approaches, so OCR is
the default for general ingestion, not ColPali/vision. `$0`-by-default via a local binary path;
a backstop regex (`_AUTH_RE`, `ocr_adapter.py:32`) raises `RuntimeError` if the CLI output signals
auth/payment/quota — for the case an operator points `OCR_CMD` at a hosted service. Raises loud
(not silent-degrade) on: auth/payment signal, missing binary, timeout, non-zero exit, or empty
output — an empty `long_context` is never ingested.

**`summarize_adapter.py`** (`01-context/src/summarize_adapter.py`) — the pluggable summary CLI
for GraphRAG community summaries. `summarize(member_texts, fact_lines, *, key=None, ckpt=None)`
(`key`/`ckpt` keyword-only) builds a prompt from **in-namespace member text + intra-community fact names only** (build-time
isolation — the adapter never sees another namespace) and calls out via `SUMMARY_CMD` (unset =
detection-only mode, communities are still written, summaries just skipped). Same `$0`-or-STOP
regex backstop as the OCR adapter, plus a JSONL checkpoint (`load_checkpoint`/`_checkpoint`) so a
long summarization run can resume.

### Where OCR reaches `serve()`

Per `docs/ROADMAP.md` (line 13, line 80-88): `etl.ingest_ocr_doc` (`01-context/src/etl.py:154-176`)
wires OCR text straight into `embed.embed_node` at ingest time, so an OCR'd doc is embedded the
moment it lands and becomes retrievable through the **existing, namespace-scoped `serve()` vector
rung** — no manual vector-query bypass. ROADMAP marks **G2 (Multimodal RAG) as CLOSED** on this
basis, verified by `etl.py`'s `--g2-selftest` (`G2_OCR_SERVE_OK`). The scope is deliberately
OCR-first, not vision-native — ColPali/CLIP are explicitly out of scope per the cited paper's
finding that OCR beat ColPali in every evaluated setting.

---

## Gate state: suggest-only (not a shipped claim)

This is load-bearing enough to say plainly, in one place: **`abstain.CALIBRATED` is a per-role
dict, every value `False`** (`01-context/src/abstain.py:26-34`). No *production* code path sets
any of them `True` — granting an autonomy lease is human-only; `auto_revert()` is revoke-only
(`abstain.py:105-132`). `03-evals/src/test_g3.py` manually seeds a role to `True` (e.g.
`abstain.CALIBRATED["engineering"] = True`, `test_g3.py:199`, `329-360`) purely to exercise the
revoke path — that's a test fixture, not a lease grant. As long as a role's flag is `False`,
`abstain.execute()` blocks even a `"pass"` decision and routes it to a human (`abstain.py:92-100`)
— this is what makes "suggest-only" functional, not just a label on a dict.

Per `docs/ROADMAP.md` and `03-evals/CASE_STUDY_calibration.md`, two different runs both land on
the same answer — autonomy stays off: the **public case-study run** (the 10-item public example
set in `CASE_STUDY_calibration.md`) fit the sufficiency proxy with a **negative** weight, a broken
signal; the **most recent measured run** (`docs/ROADMAP.md:18-22`, run against a larger internal
graph) fit a **positive** sufficiency weight but **failed its selective-gain bar** (−3.0pp vs
confidence-only). `_support_coverage()` (see [`serve.py`](#sufficiency-signal--_support_coverage)
above) is implemented and test-pinned as the deterministic replacement for the old proxy, but G3
Item 2 acceptance stays open — a positive refit **and** a passing selective gain, together, on the
validated V1 golden set (founder-gated) plus a real judge sweep, are what's required — **not
demonstrated on the public example set**. Do not read anything in this codebase as "autonomy
works" or "the gate is calibrated" — the true current state is suggest-only, full stop.

---

## Source of truth

- `01-context/src/serve.py`
- `01-context/src/ladder.py`
- `01-context/src/fuse.py`
- `01-context/src/evidence.py`
- `01-context/src/epist.py`
- `01-context/src/gate.py`
- `01-context/src/reconcile.py`
- `01-context/src/corrective.py`
- `01-context/src/pageindex_adapter.py`
- `01-context/src/ocr_adapter.py`
- `01-context/src/summarize_adapter.py`
- `01-context/src/abstain.py` (gate state / `CALIBRATED`)
- `docs/ROADMAP.md` (shipped vs open status, G1/G2/G3 gaps)

## See also

- [`01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md`](../01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md) —
  the full architecture: tiered ontology, bi-temporal validity/freshness lifecycle, the
  decision/faithfulness layer, multi-source epistemics, OCR and GraphRAG-community design notes.
- [`01-context/SERVE_JOIN_DESIGN.md`](../01-context/SERVE_JOIN_DESIGN.md) — the serve-join
  design in full: the deep-rung trigger signal, the drill interface contract, the freshness
  hard boundary, and the `$0` opt-in law for `deep_serve`.
- [`01-context/PAGEINDEX_PILOT.md`](../01-context/PAGEINDEX_PILOT.md) — the PageIndex
  adopt-and-measure pilot spec: what PageIndex is, how to self-host it, the eval design, and the
  decision rule for adopting it.
- [`01-context/RETRIEVAL.md`](../01-context/RETRIEVAL.md) — the retrieval decision card: RAG vs
  long-context, failure modes to design against, embedders in the stack, and the OCR/Corrective-RAG
  summaries.
- [`docs/ROADMAP.md`](ROADMAP.md) — capability-level status (shipped/closed/open) and the G1/G2/G3
  gap write-ups this doc's "shipped vs roadmap" framing draws from.
