"""Serve-side context management.

F1: a node-card is assembled at READ = long_context (stable) + a LIVE bi-temporal
edge query, role-scoped by namespace and validity+freshness stamped. Nothing fact-inclusive is
cached — the card is built per request, so it is always current (PART 3-B).
"""
import os
import re
import yaml
from pathlib import Path
from neo4j import GraphDatabase
URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))
# arity:1 relations — a functional relation with >1 current edge is an exactly-one-current breach
# that reconcile must quarantine (ambiguous_functional). Sourced from the rule contract, not hardcoded.
FUNCTIONAL_RELS = {r for r, spec in
                   yaml.safe_load((Path(__file__).parent.parent / "schema" / "relations.yaml").read_text())["relations"].items()
                   if spec.get("arity") == 1}

# Role-scoped node-card. SENTINEL contract: current = invalid_at > t. as_of=None => now.
# Default returns the CURRENT view; as_of=<ISO> returns the point-in-time view (valid_at <= t < invalid_at).
NODE_CARD = """
MATCH (i:Entity {key:$key}) WHERE i.namespace IN $allowed
OPTIONAL MATCH (i)-[r:RELATES_TO]->(o:Entity)
  WHERE r.namespace IN $allowed AND o.namespace IN $allowed
    AND r.valid_at <= coalesce(datetime($as_of), datetime())
    AND r.invalid_at > coalesce(datetime($as_of), datetime())
WITH i, r, o ORDER BY r.name, o.key
RETURN i.key AS node, i.long_context AS long_context, coalesce(i.dirty,false) AS fresh_dirty,
  [x IN collect(CASE WHEN r IS NULL THEN NULL ELSE {
     fact: r.name + ' -> ' + o.key,
     validity: 'current',
     valid_at: toString(r.valid_at)
   } END) WHERE x IS NOT NULL] AS facts
"""

def node_card(key, allowed, as_of=None):
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        rec = s.run(NODE_CARD, key=key, allowed=allowed, as_of=as_of).single()
        return rec.data() if rec else None


# GraphRAG communities (o46): flag-gated, read-only enrichment for the top fused hits.
# MATCH-only (zero writes); c.namespace IN $allowed scopes which communities are visible, and the
# SEED match (fused hit -> :IN_COMMUNITY -> :Community) ALSO scopes the edge itself via
# sr.namespace IN $allowed — a malformed seed edge whose own namespace is out-of-scope must not be
# able to select a community that doesn't validly overlap the fused hit. The member-expansion match
# below scopes m.namespace + r.namespace IN $allowed the same way (defense-in-depth, mirrors
# NODE_CARD's o.namespace/r.namespace convention above): build-time isolation (communities.py) keeps
# a clean community single-namespace, but a stale/malformed :IN_COMMUNITY edge — on either the seed
# or the expansion side — must not leak an out-of-scope entity's key into member_keys on READ.
# Presentation-layer only — never folds into merged_items/gate claims (epist.py carries the
# "community" authority weight, below graph).
COMMUNITY_Q = """
MATCH (e:Entity)-[sr:IN_COMMUNITY]->(c:Community)
WHERE e.key IN $keys AND c.namespace IN $allowed AND sr.namespace IN $allowed
WITH DISTINCT c
MATCH (m:Entity)-[r:IN_COMMUNITY]->(c)
WHERE m.namespace IN $allowed AND r.namespace IN $allowed
RETURN c.key AS id, c.summary AS summary, collect(m.key) AS member_keys
ORDER BY c.key
"""


def _support_coverage(query_text, primary, presentable_facts):
    """G3 Item 2 — DETERMINISTIC support-fact coverage signal (replaces the anti-correlated
    fact-count proxy that fit W_SUFFICIENCY≈−4.089). Pure (no Neo4j, no globals) so test_g3 can
    drive THIS function rather than a mirror that can drift from prod.

    coverage = |asked-entities found in SUPPORT| / max(1, |asked-entities|)
      Q = entity ids named in the question (ACME/SPI id patterns + agent:/issue: tokens)
      R = entities the SUPPORT actually covers — the `-> target` of each presentable fact, PLUS
          the primary IFF it carries >=1 presentable fact. A node with NO presentable facts is
          UNSUPPORTED (the faithfulness gate already abstains on it), so it contributes NOTHING to
          support coverage — counting its bare key would let a dead-end retrieval (a node named in
          the question but with no edges) score high sufficiency and trip the planner's
          confident-abstain early-stop BEFORE the multi-hop that finds the answer.
    Capped at 1.0; over-retrieval earns nothing (minimal-sufficient-subgraph principle).

    CANONICALIZATION: the question names BARE ids ("ACME-1"); retrieved keys are PREFIXED
    ("issue:ACME-1", "agent:cto"). Intersecting them raw never matches -> coverage collapses to 0.0
    even when the asked entity IS in the support, RE-CREATING the very anti-correlation this signal
    removes. Normalize BOTH sides to the id token after the last ":" before intersecting.

    NO COUNT FALLBACK (codex HIGH-1): when the question yields no extractable ids (|Q|=0) we CANNOT
    measure support coverage without identifiable asked-entities, so return a conservative 0.0 —
    NEVER score by raw fact count (that is the exact anti-correlated proxy this change removes,
    and it would silently reappear on NL questions the regex misses).

    HONEST NOTE: a positive sufficiency refit is NOT demonstrable on the public 10-item example
    set (its pass items have near-zero variance -> unstable weight). This signal is deterministic
    and NO LONGER anti-correlated BY CONSTRUCTION — the +gain claim requires the private 6-role
    golden + real sweep (founder gate). Do not claim gain here.
    """
    def _canon(k):
        return k.rsplit(":", 1)[-1]
    q = {_canon(k) for k in re.findall(
        r"\b(?:issue|agent):[A-Za-z0-9_-]+|[A-Z]+-\d+", query_text or "")}
    if not q:
        return 0.0
    r = set()
    for f in presentable_facts:
        m = re.search(r"->\s*(\S+)", f)
        if m:
            r.add(_canon(m.group(1)))
    if presentable_facts:                 # primary counts only when it actually carries support
        r.add(_canon(primary))
    return round(min(1.0, len(q & r) / max(1, len(q))), 2)


# serve-join (SERVE_JOIN_DESIGN §2-§3): the PageIndex host node's live freshness, read at serve
# time. A dirty host node makes its drilled sections non-actionable (freshness propagation): the
# section EvidenceItems inherit node_fresh="stale" -> freshness_state="dirty" -> the gate refuses
# to ACT on stale prose. Module-level (not inline) so the $0 demo can monkeypatch it without
# mutating the live graph.
#   FAIL-CLOSED: if the host node cannot be CONFIRMED present + in-scope, return ("stale", None).
#   An unconfirmable host must never yield an actionable section — a None record (absent /
#   out-of-scope / parse uncertainty) collapses to "stale" so freshness_state="dirty",
#   is_actionable()=False, and the section's gate claim carries stale=True. Only an explicitly
#   present, NON-dirty node returns "fresh". Node-level supersession is NOT modeled in v1 (only
#   edges are bi-temporal), so this propagates the host DIRTY axis only; host validity stays
#   "current" by design.
def _host_freshness(s, key, allowed):
    rec = s.run("MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed "
                "RETURN coalesce(n.dirty,false) AS dirty, n.namespace AS ns", k=key, allowed=allowed).single()
    if rec is None:
        return "stale", None          # FAIL-CLOSED: unconfirmable host -> non-actionable
    return ("stale" if rec["dirty"] else "fresh"), rec["ns"]


def serve(query_text, role, pattern=None, action=None, deep_serve=False, rerank=False,
          include_communities=False):
    """INT-3: the end-to-end serve chain on the real graph. WIRES the modules:
    scope -> graph_rung + vector_rung -> fuse(RRF) -> epist(authority) -> stamp -> reconcile ->
    serve-join (deep PageIndex escalation, OPT-IN) -> gate+abstain -> execute.

    deep_serve (serve-join, SERVE_JOIN_DESIGN §2 + §7): DEFAULT OFF. The §2 trigger SIGNAL
    (coverage_initial < tau AND a long-doc node in scope) is ALWAYS computed and traced, but the
    PageIndex drill executes only when deep_serve=True. This keeps every existing caller at $0
    with behavior byte-identical to before (no augmentation without opt-in).

    In the public mirror the PageIndex drill is ALWAYS STUBBED via pageindex_adapter (returns
    resolved_at="gated" by default; tests inject a fake for the positive path). Zero external
    or LLM calls either way.

    Honest scope (per codex review 2026-06-05):
      - runs the graph + vector rungs IN PARALLEL for fusion — it does NOT use ladder.retrieve()'s
        first-hit eval-gated ESCALATION (fusion needs both sources; escalation short-circuits). These
        are two different retrieval modes; serve() deliberately uses the fusion mode.
      - fuse.cross_encoder_rerank is OPT-IN via rerank=True (9jq); default rerank=False keeps the
        $0 RRF-only path. With a single non-empty source, RRF degrades to identity ranking.
      - sufficiency/confidence are PROXIES (not validated evidence quality) — calibrated in H2b.
    SECURITY: `role` is TRUSTED here. It must be AUTHENTICATED upstream — a self-asserted
    role='governance' would read all namespaces. Do not expose `role` to an unauthenticated caller.
    """
    import scope as _scope, ladder, fuse, stamp, reconcile, abstain, evidence, epist
    import pageindex_adapter
    # env can only turn communities ON (never off): param passed True always wins; param
    # omitted/False lets SERVE_INCLUDE_COMMUNITIES=1 flip it (o46).
    include_communities = include_communities or os.environ.get("SERVE_INCLUDE_COMMUNITIES") == "1"
    sc = _scope.scope(role)
    allowed, k = sc["allowed"], sc["t_cap"]
    action = action or {"category": "routine", "reversible": True}
    trace = {"role": role, "allowed": allowed}

    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        # 1. RETRIEVE — keyword (exact-ID) + graph (structural) + vector (recall), all namespace-scoped
        kw_hits = ladder.keyword_rung(s, allowed, query_text) if query_text else []
        graph_hits = ladder.graph_rung(s, allowed, pattern) if pattern else []
        vec_hits = ladder.vector_rung(s, allowed, query_text, k) if query_text else []
        vec_keys = [h["key"] for h in vec_hits]
        # cf7 rung 2b — chunk-level vector recall ("which passage"). Returns parent keys (for fusion) +
        # the SELECTED passage per parent (for bzr surfacing). Gated on chunk vectors existing, so a
        # graph with only single-chunk nodes (no :Chunk materialized) behaves exactly as before.
        chunk_hits = (ladder.chunk_rung(s, allowed, query_text, k)
                      if query_text and ladder.chunk_vector_available(s) else [])
        chunk_keys = [h["key"] for h in chunk_hits]
        chunk_passages = {h["key"]: h["chunk"] for h in chunk_hits}    # bzr: parent key -> selected passage
        # CORRELATED-SOURCE DEDUP (post-impl red-team B1): node-vector (2a) and chunk-vector (2b) are
        # NOT independent retrievers — same EmbeddingGemma model over two granularities of the SAME
        # content — so a parent found by BOTH is one correlated signal, not consensus. RRF sums a
        # contribution PER source, which would double-score that parent (2/(k+1)) and let a purely-recall
        # node leap the fact-authority tier (keyword/graph), violating the epist contract. So chunk only
        # EXTENDS recall in fusion: it votes for parents node-vector MISSED. (trace + chunk_passages keep
        # the FULL chunk hits — the rung still reports/surfaces db-runbook even when vector also found it.)
        chunk_fusion = [c for c in chunk_keys if c not in vec_keys]
        trace["retrieve"] = {"keyword": kw_hits, "graph": graph_hits, "vector": vec_keys,
                             "chunk": chunk_keys, "chunk_fused": chunk_fusion}

        # 2. FUSE — RRF across whichever sources fired. fuse.rrf breaks RRF score-ties by SOURCE
        # AUTHORITY (keyword > graph > vector > chunk), so an exact-ID reference beats an equally-ranked
        # fuzzy hit (RC2 fix — previously a doc_id alphabetical tie-break dropped that authority;
        # full weighted RRF is the R7 upgrade).
        rankings = {**({"keyword": kw_hits} if kw_hits else {}),
                    **({"graph": graph_hits} if graph_hits else {}),
                    **({"vector": vec_keys} if vec_keys else {}),
                    **({"chunk": chunk_fusion} if chunk_fusion else {})}
        if not rankings:                                  # no retrieval (incl. vector degraded/absent)
            # UNIFORM RETURN CONTRACT: same keys as the normal return below, so a caller never
            # KeyErrors on the abstain path (surfaced when vector_rung degrades to [] without the
            # optional embedder and keyword/graph also miss). primary=None signals nothing retrieved.
            no_retrieval = {"query": query_text, "role": role, "primary": None, "presentable_facts": [],
                            "composed_evidence": [], "decision": "abstain", "mode": "suggest",
                            "reason": "no in-scope retrieval", "executed": False, "provenance": {}, "trace": trace}
            # o46: flag-ON must still carry "communities" on a miss query (uniform envelope, never a
            # missing key); flag-OFF stays BYTE-IDENTICAL to pre-o46 (no key added at all).
            if include_communities:
                trace["communities"] = []
                no_retrieval["communities"] = []
            return no_retrieval
        fused = fuse.rrf(rankings)
        # 2b. RERANK (9jq) — OPT-IN cross-encoder rerank of the fused set. Default OFF: serve stays
        # $0/RRF-only (the shipping path). When rerank=True AND sentence-transformers is installed,
        # re-score the fused docs by true (query, long_context) relevance; on ImportError fall back to
        # the RRF order (optional dev dep, never a hard requirement). Reorders what is PRESENTED; the
        # gate's claims are still built downstream from the (possibly reranked) order.
        if rerank and fused:
            try:
                from sentence_transformers import CrossEncoder
                _keys = [kk for kk, _ in fused]
                _rows = {r["k"]: r["ctx"] for r in s.run(
                    "MATCH (n:Entity) WHERE n.key IN $keys AND n.namespace IN $allowed "
                    "RETURN n.key AS k, n.long_context AS ctx", keys=_keys, allowed=allowed)}
                _texts = {kk: (_rows.get(kk) or kk) for kk in _keys}   # every fused key has text
                # Supply-chain pin (security-audit LOW): pin the model REVISION so a future HF-side
                # change to the tag can't alter what loads. SHA = the revision the 9jq on-path test ran.
                fused = fuse.cross_encoder_rerank(query_text, fused, _texts,
                                                  CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2",
                                                               revision="c5ee24cb16019beea0893ab7796b1df96625c6b8"))
                trace["rerank"] = {"applied": True, "order": [kk for kk, _ in fused]}
            except ImportError:
                trace["rerank"] = {"applied": False, "reason": "sentence-transformers absent; RRF order kept"}
        else:
            trace["rerank"] = {"applied": False, "reason": "rerank=False (default; $0 RRF-only)"}
        fused_keys = [kk for kk, _ in fused]
        primary = fused_keys[0]
        trace["fuse"] = {"fused_top": fused[:k]}

        # COMMUNITIES (o46) — flag-gated, read-only enrichment: communities overlapping the top
        # fused hits, role-scoped. Presentation-only (see COMMUNITY_Q docstring); computed here so
        # `comm_block` is a local var the session can populate before it closes (used below, after
        # the `with` block, only when the flag is on).
        comm_block = None
        if include_communities:
            comm_rows = s.run(COMMUNITY_Q, keys=fused_keys[:k], allowed=allowed).data()
            comm_block = [{"id": r["id"], "summary": r["summary"], "member_keys": r["member_keys"],
                           "provenance": "community"} for r in comm_rows]
            trace["communities"] = comm_block

        # 3. EPIST — source authority (keyword/graph = fact-authority > vector = recall)
        sources = {kk: ("keyword" if kk in kw_hits else "graph" if kk in graph_hits
                        else "vector" if kk in vec_keys else "chunk")
                   for kk in fused_keys}
        trace["epist"] = {"primary_source": sources[primary], "authority": "keyword=graph>vector>chunk"}

        # 4. STAMP + 5. RECONCILE — the primary node's card (o.namespace-isolated)
        rec = s.run(stamp.CARD_Q, key=primary, allowed=allowed).single()
        facts = stamp.stamp_card(rec)
        node_fresh = "stale" if rec["node_dirty"] else "fresh"
        card = reconcile.reconcile(node_fresh, facts, FUNCTIONAL_RELS)
        trace["stamp_reconcile"] = {"node_fresh": node_fresh, "n_current": card["n_current"],
                                    "n_superseded": card["n_superseded"], "actionable": card["actionable"]}

        # 4b. COMPOSE (R1+R2): the ANSWER surface = content + current facts of the top-K
        # fused cards (K = role T-cap), all role-scoped. Fixes the edge-only-card gaps: status and
        # prose live in long_context; set + multi-hop answers span multiple cards.
        # DELIBERATE SPLIT: claims/sufficiency for the GATE stay primary-card-based below —
        # composition widens what is PRESENTED, never what is ACTED on (the sufficiency proxy is
        # uncalibrated; do not feed it a bigger number for free).
        composed = []
        expand = []                                  # 1-hop: in-scope targets of presented facts
        def _add_card(kk):
            crec = s.run(stamp.CARD_Q, key=kk, allowed=allowed).single()
            if crec is None:
                return
            # 3zy: tag BOTH presentation surfaces with the PARENT's live freshness ([fresh]/[stale])
            # so a reader (and any downstream consumer) sees whether the surfaced prose/chunk text is
            # current. Presentation-only + gate-SAFE: actionability still derives from the stamped facts
            # below + the faithfulness gate (a dirty parent -> stale graph claims -> the gate refuses to
            # ACT); this marker NEVER becomes a gate claim, it only annotates what is shown. Mirrors the
            # node-vector lazy-refresh staleness window — a pre-existing pattern, not a cf7 regression.
            # The [..] marker sits AFTER the (kk) token so existing content(kk)/content_chunk(kk) prefix
            # matches (and the isolation issue:/agent: regex) are unaffected.
            pmark = "stale" if crec["node_dirty"] else "fresh"
            ctx = s.run("MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed "
                        "RETURN n.long_context AS ctx", k=kk, allowed=allowed).single()
            if ctx and ctx["ctx"]:
                composed.append(f"content({kk}) [{pmark}]: {ctx['ctx'][:200]}")
            # bzr: a node retrieved via chunk-vector (rung 2b) surfaces its SELECTED passage — the chunk
            # the query actually matched — not just the long_context abstract (whose [:200] truncation may
            # cut before the relevant span). Only the ONE selected chunk is surfaced (chunk_passages is
            # already deduped to the best passage per parent), so this never bloats the answer with all
            # chunks (the bzr concern). This is the read that makes embed.py's n.chunks no longer dead.
            if kk in chunk_passages:
                composed.append(f"content_chunk({kk}) [{pmark}]: {chunk_passages[kk][:200]}")
            for f in stamp.freshness_judge(stamp.stamp_card(crec)):
                composed.append(f"{kk}: {f['fact']}")
                m = re.search(r"->\s*(\S+)", f["fact"])
                if m:
                    expand.append(m.group(1))
        shown = list(fused_keys[:k])
        for kk in shown:
            _add_card(kk)
        # 1-HOP EXPANSION (R2b): multi-hop answers need the TARGET card too (e.g. "ACME-2 blocks
        # ACME-1, who owns ACME-1?" — ACME-1's card carries the second hop). One hop only, in-scope
        # only (CARD_Q re-checks namespace), capped at k extra cards.
        for tgt in expand:
            if len(shown) >= 2 * k:
                break
            if tgt not in shown:
                shown.append(tgt)
                _add_card(tgt)
        trace["compose"] = {"cards": shown, "n_evidence": len(composed)}

        # ISOLATION SELF-CHECK (measured, not assumed): every node this answer touches —
        # fused candidates, primary, composed cards, and the TARGETS of presented/composed facts —
        # must be in-scope.
        touched = set(fused_keys) | {primary}
        for f in card["presentable"]:
            m = re.search(r"->\s*(\S+)", f["fact"])
            if m:
                touched.add(m.group(1))
        for line in composed:
            touched.update(re.findall(r"\b(?:issue|agent):[A-Za-z0-9_-]+", line))
        leaked = [r["k"] for r in s.run(
            "MATCH (n:Entity) WHERE n.key IN $k AND NOT n.namespace IN $allowed RETURN n.key AS k",
            k=list(touched), allowed=allowed)]
        trace["isolation"] = {"clean": not leaked, "leaked": leaked}

        # ── SERVE-JOIN (SERVE_JOIN_DESIGN §2-§3): deep-PageIndex escalation + evidence normalization
        # feeding the SINGLE existing gate. Sequence is FROZEN: normalize -> epist AUTHORITY ORDER ->
        # freshness propagation -> build claims -> gate (the gate below stays last + single).
        # epist ORDERS evidence by authority; it does NOT decide actionability (that is the gate).
        # Vector hits are recall-only and never become gate claims.
        #
        # (a) DEEP-RUNG TRIGGER — frozen SIGNAL: warranted iff NOT isolation-leaked, non-empty
        # query_text, coverage_initial below the shared tau, AND the long-doc node in scope has a
        # non-empty doc-sha. The signal is ALWAYS computed + traced; the REAL drill executes only
        # under deep_serve (opt-in, $0-safe).
        # COVERAGE-GATED DB READS: the PageIndex ref/sha lookups run ONLY when query_text is
        # non-empty AND coverage_initial < tau. Empty/graph-only serve() (e.g. corrective.py
        # calls serve(query_text='') for graph-only retrieval) skips ALL PageIndex reads entirely
        # — _support_coverage returns 0.0 on |Q|=0, so a bare coverage check would fall through
        # to the else-branch and do unnecessary Neo4j round-trips.
        # ALIGN WITH LADDER: when it DOES evaluate, ladder drills sorted(in-scope nodes with
        # pageindex_ref)[0]; serve picks that SAME candidate, then warrants deep only if that
        # candidate ALSO has pageindex_doc_sha (non-empty — an empty-string sha is treated as absent).
        coverage_initial = _support_coverage(query_text, primary, [f["fact"] for f in card["presentable"]])
        deep = None
        deep_augmented = False                         # drill RAN vs sections ADDED are distinct
        pageindex_items = []
        if not query_text:
            # graph-only serve() (empty query_text): skip ALL PageIndex reads — no query to navigate.
            # _support_coverage returns 0.0 on |Q|=0; without this guard the coverage check would
            # fall through to the else-branch and trigger unnecessary PageIndex Neo4j round-trips.
            deep_warranted = False
            trace["serve_join"] = {"coverage_initial": coverage_initial, "deep_warranted": False,
                                   "reason": "no query text - PageIndex reads skipped"}
        elif coverage_initial >= evidence.DEEP_COVERAGE_TAU:
            # coverage sufficient: skip BOTH PageIndex reads entirely — drill not evaluated.
            deep_warranted = False
            trace["serve_join"] = {"coverage_initial": coverage_initial, "deep_warranted": False,
                                   "reason": "coverage sufficient - drill not evaluated"}
        else:
            ref_nodes = [r["k"] for r in s.run(                   # ladder's longdocs set (ref only)
                "MATCH (n:Entity) WHERE n.pageindex_ref IS NOT NULL "
                "AND n.namespace IN $allowed RETURN n.key AS k", allowed=allowed)]
            drill_candidate = sorted(ref_nodes)[0] if ref_nodes else None   # == ladder's sorted(...)[0]
            # NON-EMPTY sha: IS NOT NULL alone passes an empty-string sha (""), which may match a
            # ""-recorded tree. Require a real sha to align with ladder's binding semantics.
            candidate_has_sha = bool(drill_candidate) and bool(s.run(
                "MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed "
                "AND n.pageindex_doc_sha IS NOT NULL AND n.pageindex_doc_sha <> '' "
                "RETURN n.key AS k", k=drill_candidate, allowed=allowed).single())
            # F1: bool(query_text) guard also lives in deep_warranted for clarity — belt+suspenders.
            deep_warranted = (not leaked) and bool(query_text) and candidate_has_sha
            deep_fired = deep_warranted and deep_serve   # real drill is OPT-IN (default off)
            pageindex_host_note = None
            if deep_fired:
                deep = pageindex_adapter.drill(allowed, query_text, k)
                # fail-safe: non-"pageindex" / zero sections -> NO augmentation, gate on original.
                if deep.get("resolved_at") == "pageindex" and deep.get("sections"):
                    host = deep["doc"]
                    host_fresh, host_ns = _host_freshness(s, host, allowed)   # freshness propagation
                    if host_ns is None:
                        # FAIL-CLOSED: host UNCONFIRMABLE (rec is None) -> DROP the section.
                        # No EvidenceItem with a fabricated namespace may reach the answer or the
                        # gate. (A confirmed-DIRTY host has host_ns present + "stale" and DOES
                        # build a non-actionable section below — that is the freshness-safety path.)
                        pageindex_host_note = "unconfirmable - section dropped"
                    else:
                        ref = s.run("MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed "
                                    "RETURN n.pageindex_ref AS ref", k=host, allowed=allowed).single()
                        src_path = ref["ref"] if ref else None
                        # F2: ONE EvidenceItem per drill — the drill returns a single synthesized
                        # answer over N selected section IDs (not per-section text). Build one item
                        # carrying text=answer, section_id=comma-joined IDs for provenance.
                        pageindex_items.append(evidence.from_pageindex(
                            host_node_id=host, namespace=host_ns, text=deep["answer"],
                            source_path=src_path,
                            section_id=",".join(deep["sections"]),
                            node_fresh=host_fresh))
                        composed.append(f"pageindex({host}): {deep['answer']}")   # augment answer surface
                        deep_augmented = True
            trace["serve_join"] = {"coverage_initial": coverage_initial,
                                   "drill_candidate": drill_candidate, "candidate_has_sha": candidate_has_sha,
                                   "deep_warranted": deep_warranted, "deep_serve": deep_serve,
                                   "deep_fired": deep_fired, "deep_augmented": deep_augmented,
                                   "pageindex_host": pageindex_host_note,
                                   "resolved_at": deep.get("resolved_at") if deep else None,
                                   "mechanism": deep.get("mechanism") if deep else None,
                                   "n_pageindex_sections": len(pageindex_items)}

        # (b)+(c) NORMALIZE -> EPIST AUTHORITY ORDER -> the ordered set builds the gate claims.
        # epist stays LOAD-BEARING for ORDERING: rank by epist.weights_for(role) over each item's
        # retrieval_method (graph/pageindex/vector); claims are built FROM that one ordered list.
        # graph facts always normalize (they feed the gate even with no drill); the PageIndex side
        # is present only when a drill augmented.
        # F3 — DESIGN INTENT: epist provides authority ORDERING (trace + claims-list); the gate is
        # intentionally order-insensitive (epist != gate). Answer-surface ordering + conflict are v2.
        primary_ns = next((r["ns"] for r in s.run(
            "MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed RETURN n.namespace AS ns",
            k=primary, allowed=allowed)), (allowed[0] if allowed else "shared"))
        graph_items = [evidence.from_graph(f["fact"], namespace=primary_ns, node_id=primary,
                                           validity=f["validity"], node_fresh=f["fresh"])
                       for f in card["presentable"]]
        _w = epist.weights_for(role)
        merged_items = sorted(graph_items + pageindex_items,
                              key=lambda it: -_w.get(it.retrieval_method, 0.0))
        trace["epist"] = {**trace.get("epist", {}),
                          "merged_authority_order": [it.authority_hint for it in merged_items],
                          "n_merged": len(merged_items)}

        # 6+7. GATE + ABSTAIN — claims BUILT FROM the authority-ordered merged set (one homogeneous
        # list, not two). graph fact -> SUPPORTED, stale from its freshness; PageIndex section ->
        # SUPPORTED, stale = NOT is_actionable (freshness propagation: a dirty host -> stale=True).
        # A stale claim is a HARD faithfulness violation in abstain.stage_a_decision -> the gate
        # refuses to ACT (routes to human).
        #   conflict = False FOR EVERY CLAIM — v1 SCOPE (founder 2026-06-17): conflict deferred to v2.
        #   Cross-source graph-vs-prose conflict needs semantic matching across different node
        #   identities; within-source same-relation multi-edges are co-valid additive facts already
        #   adjudicated upstream (bi-temporal supersession + mutate-layer cardinality), so serve must
        #   NOT re-flag them — the prior resolve_slot path false-positived on additive edges (e.g.
        #   BLOCKS->A, BLOCKS->B) -> false abstains. epist AUTHORITY ORDERING stays load-bearing above.
        claims = [{"id": it.text if it.retrieval_method != "pageindex" else (it.section_id or it.text),
                   "support_status": "SUPPORTED",
                   "stale": not evidence.is_actionable(it.freshness_state),
                   "conflict": False}   # v1 SCOPE: conflict deferred to v2 (cross-source needs
                                        # semantic matching across node identities; within-source
                                        # same-relation multi-edges are co-valid additive facts
                                        # adjudicated upstream by bi-temporal + cardinality).
                                        # DO NOT wire resolve_slot — it false-positives on additive
                                        # edges -> false abstains.
                  for it in merged_items]
        if not claims:
            claims = [{"id": primary, "support_status": "UNSUPPORTED", "stale": False, "conflict": False}]
        # confidence basis is EXPLICIT (codex: no fabricated 0.9). A vector hit uses its cosine
        # score; a chunk-vector hit uses its chunk cosine; a graph-only hit is an exact structural MATCH
        # = high-certainty by construction (fact-authority), labelled as such — not a pretend score.
        # post-impl red-team B2: a chunk-ONLY primary (in chunk_hits, not vec_hits) must NOT be mislabeled
        # "graph_structural_exact" 0.95 — it is fuzzy recall. Use its real chunk cosine + an honest basis.
        vec_score = next((h["score"] for h in vec_hits if h["key"] == primary), None)
        chunk_score = next((h["score"] for h in chunk_hits if h["key"] == primary), None)
        if vec_score is not None:
            self_conf, conf_basis = round(min(0.99, vec_score), 2), "vector_score"
        elif chunk_score is not None:
            self_conf, conf_basis = round(min(0.99, chunk_score), 2), "chunk_vector_score"
        else:
            self_conf, conf_basis = 0.95, "graph_structural_exact"

        # G3 Item 2 — DETERMINISTIC support-fact coverage signal. Computed by the pure
        # module-level helper _support_coverage() (see its docstring): canonicalized
        # bare-vs-prefixed intersection, support-gated R, and |Q|=0 -> 0.0 (NO count fallback).
        sufficiency = _support_coverage(query_text, primary, [f["fact"] for f in card["presentable"]])

        decision = abstain.stage_a_decision(claims, action, sufficiency, self_conf, role=role)
        executed = abstain.execute(decision, lambda: f"acted on {primary}")
        trace["gate_abstain"] = {"sufficiency": sufficiency, "self_confidence": self_conf,
                                 "confidence_basis": conf_basis, **decision,
                                 "executed": executed["executed"]}

    result = {"query": query_text, "role": role, "primary": primary,
              "presentable_facts": [f["fact"] for f in card["presentable"]],
              "composed_evidence": composed,
              "decision": decision["final"], "mode": decision["mode"],
              "executed": executed["executed"], "provenance": sources, "trace": trace}
    if include_communities:
        result["communities"] = comm_block
    return result


def _demo():
    """INT-3 + serve-join: one real query runs the FULL chain end-to-end on the live graph;
    then the serve-join is exercised with a STUBBED adapter (zero LLM/external calls, $0).

    $0 LAW: the REAL PageIndex drill is intentional-run only. Here pageindex_adapter._inject()
    installs a canned pageindex payload so the join WIRING is tested without any external call.
    serve() only ever calls pageindex_adapter.drill() for the deep drill (the retrieval/fusion
    rungs use keyword_rung/graph_rung/vector_rung directly), so the injection is surgical.
    """
    import sys, json
    import pageindex_adapter, evidence, epist

    r = serve("add a vector index for embedding similarity search", "engineering")
    print(json.dumps(r["trace"], indent=2, default=str))
    print(f"\n[serve] primary={r['primary']} decision={r['decision']} mode={r['mode']} "
          f"executed={r['executed']}")
    print(f"[serve] presentable_facts={r['presentable_facts']}")
    stages = {"retrieve", "fuse", "epist", "stamp_reconcile", "gate_abstain"}
    ok = stages <= set(r["trace"]) and r["decision"] in ("pass", "partial", "abstain", "escalate")
    print("INT3_OK" if ok else f"INT3_FAIL stages={set(r['trace'])} decision={r['decision']}")
    if not ok:
        sys.exit(1)

    # ── SERVE-JOIN (stubbed adapter, $0) ────────────────────────────────────────────────────────
    fail = []
    _DRILL = {"resolved_at": "pageindex",
              "answer": "the sufficient-context paper finds abstention beats answering on low coverage",
              "doc": "extsrc:context-evals",          # the real in-scope long-doc node (shared ns)
              "sections": ["0001", "0007"]}
    q_low = "what does the sufficient context paper conclude about abstention"

    # ($0 DEFAULT GUARD) — a default serve() (deep_serve omitted) must NOT execute the drill even
    # when the signal is WARRANTED. A tripwire raises if pageindex_adapter.drill() is touched;
    # the call must still succeed with deep_warranted=True (signal computed) but deep_fired=False.
    def _tripwire(allowed, q, t):
        raise AssertionError("pageindex_adapter.drill() called under deep_serve=False — $0 LAW breach")
    pageindex_adapter._inject(_tripwire)
    try:
        r0 = serve(q_low, "engineering")                        # deep_serve defaults to False
    finally:
        pageindex_adapter._inject(None)
    sj0 = r0["trace"]["serve_join"]
    print(f"[$0-def]  low-cov default serve() -> deep_warranted={sj0['deep_warranted']} "
          f"deep_fired={sj0['deep_fired']} (signal computed, NO real drill)")
    fail += [] if (sj0["deep_warranted"] is True and sj0["deep_fired"] is False
                   and sj0["n_pageindex_sections"] == 0) \
        else ["($0) low-cov default serve fired the drill or skipped the warranted signal"]

    # ($0 + COVERAGE-GATE) — a HIGH-coverage default serve() must do ZERO PageIndex reads.
    # The tripwire stays armed (must not fire), and serve_join trace must show deep_warranted=False
    # with the "coverage sufficient" reason and NO drill_candidate field.
    # Use a query that names in-scope entity IDs so _support_coverage() meets tau.
    # "issue:ACME-2 blocks issue:ACME-1" -> keyword_rung matches BOTH ids; sorted -> primary=issue:ACME-1.
    # ACME-1 carries presentable facts so it counts toward support -> 1 of the 2 asked ids covered ->
    # coverage_initial=0.5 == tau -> coverage gate fires. The assertion checks deep_warranted is False
    # (coverage >= tau), NOT == 0.5 exactly, so it holds whether RRF resolves primary to ACME-1 (->0.5)
    # or ACME-2 (whose BLOCKS->ACME-1 fact gives ->1.0); either way >= tau -> zero PageIndex reads.
    q_hi = "issue:ACME-2 blocks issue:ACME-1"
    pageindex_adapter._inject(_tripwire)
    try:
        rh = serve(q_hi, "engineering")
    finally:
        pageindex_adapter._inject(None)
    sjh = rh["trace"]["serve_join"]
    print(f"[$0-cov]  high-cov default serve() -> coverage_initial={sjh['coverage_initial']} "
          f"deep_warranted={sjh.get('deep_warranted')} reason={sjh.get('reason')!r}")
    fail += [] if (sjh.get("deep_warranted") is False
                   and sjh.get("reason") == "coverage sufficient - drill not evaluated"
                   and "drill_candidate" not in sjh and "n_pageindex_sections" not in sjh) \
        else [f"($0-cov) high-coverage serve evaluated/ran the drill or did a PageIndex read: {sjh}"]

    # A low-coverage query WITH a long-doc in scope -> signal is warranted; with deep_serve=True
    # the stub adapter returns the canned drill (zero LLM). Proves join WIRING, not the real drill.
    pageindex_adapter._inject(lambda allowed, q, t: dict(_DRILL))
    try:
        r1 = serve(q_low, "engineering", deep_serve=True)
    finally:
        pageindex_adapter._inject(None)
    sj = r1["trace"]["serve_join"]
    print(f"\n[join]   q_low -> deep_fired={sj['deep_fired']} deep_augmented={sj['deep_augmented']} "
          f"sections={sj['n_pageindex_sections']} candidate={sj['drill_candidate']}")
    print(f"[join]   composed_evidence (tail)={r1['composed_evidence'][-1:]}")
    # (i) the drill RAN and ACTUALLY augmented; the PageIndex answer reached the composed surface.
    answer_in_composed = any(_DRILL["answer"] in line for line in r1["composed_evidence"])
    fail += [] if (sj["deep_fired"] and sj["deep_augmented"] and sj["resolved_at"] == "pageindex"
                   and sj["n_pageindex_sections"] == 1 and answer_in_composed) \
        else ["(i) stubbed drill did not augment composed with the PageIndex answer"]

    # (i-transform) — assert the CODE transforms real inputs, not the stub echoing itself.
    # (a) the normalizer produces a prose-authority EvidenceItem with host key + section id +
    #     source path — fields the join CODE sets, not the drill dict:
    pit = evidence.from_pageindex(host_node_id=_DRILL["doc"], namespace="shared",
                                  text=_DRILL["answer"], source_path="01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md",
                                  section_id=_DRILL["sections"][0], node_fresh="fresh")
    fail += [] if (pit.retrieval_method == "pageindex" and pit.authority_hint == "prose"
                   and pit.node_id == _DRILL["doc"] and pit.section_id == _DRILL["sections"][0]
                   and pit.freshness_state == "current") \
        else ["(i-transform) from_pageindex did not produce the expected prose EvidenceItem"]
    # (b) epist.weights_for puts fact-authority before prose:
    _w = epist.weights_for("engineering")
    gi = evidence.from_graph("ASSIGNED_TO -> agent:cto", namespace="engineering", node_id="issue:ACME-2")
    mixed = sorted([pit, gi], key=lambda it: -_w.get(it.retrieval_method, 0.0))
    mixed_auth = [it.authority_hint for it in mixed]
    fail += [] if (mixed_auth == ["fact", "prose"]
                   and mixed[0].retrieval_method == "graph"
                   and mixed[1].node_id == _DRILL["doc"]) \
        else [f"(i-transform) epist authority ordering wrong: {mixed_auth}"]
    # live drilled set reached the gate as prose claims: n_merged >= pageindex sections
    # (may also include graph facts from primary card; prose authority must be present)
    eo = r1["trace"]["epist"]
    fail += [] if (eo["n_merged"] >= sj["n_pageindex_sections"]
                   and sj["n_pageindex_sections"] > 0
                   and "prose" in eo["merged_authority_order"]) \
        else [f"(i-transform) drilled sections did not reach the gate as claims: {eo}"]
    # (c) v1 conflict behavior: conflict is DEFERRED to v2 — conflict_slots absent from trace:
    fail += [] if "conflict_slots" not in eo else ["(i-transform) conflict_slots must be absent (v2 defer)"]
    print(f"[join]   epist order(live)={eo['merged_authority_order']} mixed-order={mixed_auth} "
          f"n_merged={eo['n_merged']} (conflict deferred to v2: every claim conflict=False)")

    # (ii) FRESHNESS FAIL-CLOSED: a DIRTY/superseded host node makes sections non-actionable.
    # Monkeypatch _host_freshness to "stale" (simulates a dirty host WITHOUT mutating the live
    # graph) -> PageIndex claim carries stale=True -> abstain.stage_a_decision treats it as a HARD
    # faithfulness violation (via=faithfulness) -> gate must NOT execute an act.
    real_host = _host_freshness
    pageindex_adapter._inject(lambda allowed, q, t: dict(_DRILL))
    try:
        globals()["_host_freshness"] = lambda s, key, allowed: ("stale", "shared")
        r2 = serve(q_low, "engineering", deep_serve=True)
    finally:
        pageindex_adapter._inject(None)
        globals()["_host_freshness"] = real_host
    has_pi = r2["trace"]["serve_join"]["n_pageindex_sections"] > 0
    d_via, d_final = r2["trace"]["gate_abstain"].get("via"), r2["decision"]
    print(f"[fresh]  dirty-host drill -> via={d_via} decision={d_final} executed={r2['executed']} "
          f"(stale section -> hard faithfulness violation, must NOT act)")
    fail += [] if (has_pi and d_via == "faithfulness" and r2["executed"] is False and d_final != "pass") \
        else [f"(ii) stale PageIndex section did not hard-fail: via={d_via} decision={d_final}"]

    # CONTROL — the SAME query+drill with a FRESH host does NOT trip the faithfulness hard-gate:
    pageindex_adapter._inject(lambda allowed, q, t: dict(_DRILL))
    try:
        r3 = serve(q_low, "engineering", deep_serve=True)
    finally:
        pageindex_adapter._inject(None)
    f_via = r3["trace"]["gate_abstain"].get("via")
    print(f"[fresh]  fresh-host control -> via={f_via} decision={r3['decision']} "
          f"(no stale claim: NOT the faithfulness hard-gate)")
    fail += [] if f_via == "sufficiency×confidence" \
        else [f"(ii) fresh-host control should route via sufficiency×confidence, got via={f_via}"]

    if fail:
        print("INT3_FAIL(serve-join):", fail); sys.exit(1)
    print("INT3_OK")


def _chunk_demo():
    """INT-2b (cf7 + bzr): chunk-vector recall + selected-passage surfacing on the LIVE seeded graph.
    Assumes the pipeline ran (etl.py -> demo_seed.py), so the multi-chunk nodes extsrc:db-runbook
    (engineering) and extsrc:finance-policy (finance) exist WITH indexed :Chunk children. Proves:
      cf7  — a PASSAGE-specific query retrieves the right multi-chunk node via the chunk rung (2b),
             and that node joins RRF fusion (trace.retrieve.chunk).
      bzr  — serve surfaces the SELECTED chunk (content_chunk(...)) — the passage the query actually
             matched, not just the long_context abstract. THIS is the read that makes embed.py's
             n.chunks no longer dead-stored.
      iso  — the engineering runbook chunk NEVER surfaces for a finance role, while finance still
             returns its OWN chunk slice (non-vacuous isolation; mirrors ladder INT2)."""
    import sys
    q = "how does the service reclaim idle database connections with a reaper"
    eng = serve(q, "engineering")
    fin = serve(q, "finance")
    eng_chunk = eng["trace"]["retrieve"]["chunk"]
    fin_chunk = fin["trace"]["retrieve"]["chunk"]
    surfaced = [c for c in eng["composed_evidence"] if c.startswith("content_chunk(extsrc:db-runbook)")]
    print(f"[chunk]   engineering chunk-rung hits = {eng_chunk}")
    print(f"[chunk]   finance     chunk-rung hits = {fin_chunk}")
    print(f"[bzr]     surfaced selected passage   = {surfaced[:1]}")
    print(f"[isolate] db-runbook (engineering) in finance chunk hits? "
          f"{'extsrc:db-runbook' in fin_chunk} (must be False)")

    fail = []
    fail += [] if "extsrc:db-runbook" in eng_chunk else ["cf7: chunk rung did not retrieve extsrc:db-runbook"]
    fail += [] if surfaced and "reaper" in surfaced[0].lower() \
        else ["bzr: serve did not surface the selected reaper chunk on the answer surface"]
    fail += [] if "extsrc:db-runbook" not in fin_chunk \
        else ["isolation: finance role leaked the engineering runbook chunk"]
    fail += [] if fin_chunk else ["isolation vacuous: finance returned no chunk hits (finance :Chunk nodes seeded?)"]

    if fail:
        print("CHUNK_RECALL_FAIL:", fail); sys.exit(1)
    print("CHUNK_RECALL_OK")


def _communities_demo():
    """o46: GraphRAG communities wired into serve() — flag-gated, read-only enrichment.
    Own fixture setup (mirrors _chunk_demo()'s "assumes the pipeline ran" convention): builds
    communities for engineering+finance via communities.py's existing, already-approved write
    path (never through serve()). Assumes etl.py + demo_seed.py already ran.
    Proves the bead's 4 acceptance clauses (a)-(d)."""
    import sys, json, re
    import communities, epist

    fail = []

    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        communities.build_communities(s, namespaces=["engineering", "finance"], algo="auto",
                                      summarize=False, run_id="serve-comm-demo",
                                      now="2026-07-02T00:00:00")

    # (a) enrichment shape + authority
    q = "issue:ACME-2 blocks issue:ACME-1"
    r_on = serve(q, "engineering", include_communities=True)
    comms_on = r_on.get("communities")
    print(f"[comm-a]  engineering communities: {comms_on}")
    fail += [] if "communities" in r_on else ["(a) 'communities' key missing when flag ON"]
    fail += [] if comms_on else ["(a) communities empty (engineering has >=1 entity -> >=1 community)"]
    fail += [] if comms_on and all(set(c.keys()) == {"id", "summary", "member_keys", "provenance"}
                                   and c["provenance"] == "community" for c in comms_on) \
        else ["(a) community item shape/provenance wrong"]
    eng_w, def_w = epist.weights_for("engineering"), epist.weights_for("_default")
    fail += [] if eng_w["community"] < eng_w["graph"] else ["(a) engineering: community authority must be < graph"]
    fail += [] if def_w["community"] < def_w["graph"] else ["(a) _default: community authority must be < graph"]

    # (b) OFF byte-identity: omitted flag vs explicit False must match, and carry no 'communities' key
    r_off1 = serve(q, "engineering")
    r_off2 = serve(q, "engineering", include_communities=False)
    j1 = json.dumps(r_off1, sort_keys=True, default=str)
    j2 = json.dumps(r_off2, sort_keys=True, default=str)
    print(f"[comm-b]  OFF byte-identical: {j1 == j2}")
    fail += [] if j1 == j2 else ["(b) omitted-flag vs explicit-False responses differ"]
    fail += [] if "communities" not in r_off1 else ["(b) 'communities' key present when flag OFF"]
    fail += [] if "communities" not in r_off1["trace"] else ["(b) trace['communities'] present when flag OFF"]
    pre_change_keys = {"query", "role", "primary", "presentable_facts", "composed_evidence",
                       "decision", "mode", "executed", "provenance", "trace"}
    fail += [] if set(r_off1.keys()) == pre_change_keys else [f"(b) key set drifted: {set(r_off1.keys())}"]

    # (c) zero writes: the literal query string is MATCH-only
    fail += [] if not re.search(r"CREATE|MERGE|SET|DELETE|REMOVE", COMMUNITY_Q, re.I) \
        else ["(c) COMMUNITY_Q contains a write verb"]

    # (d) 2-namespace isolation
    r_fin = serve("issue:ACME-4", "finance", include_communities=True)
    comms_fin = r_fin.get("communities", [])
    print(f"[comm-d]  finance communities: {comms_fin}")
    fail += [] if all(c["id"].startswith("community:finance:") or c["id"].startswith("community:shared:")
                      for c in comms_fin) else ["(d) finance surfaced a non-finance/shared community id"]
    fail += [] if not any(mk in ("issue:ACME-1", "issue:ACME-2")
                          for c in comms_fin for mk in c["member_keys"]) \
        else ["(d) finance surfaced an engineering-only member key"]
    fail += [] if not any(c["id"].startswith("community:finance:") for c in comms_on) \
        else ["(d) engineering surfaced a finance community id"]
    fail += [] if not any(mk in ("agent:cfo", "issue:ACME-4")
                          for c in comms_on for mk in c["member_keys"]) \
        else ["(d) engineering surfaced a finance-only member key"]

    # (e) malicious fixture — read-path defense-in-depth. Build-time isolation (communities.py)
    # keeps every CLEAN community single-namespace, but COMMUNITY_Q must still filter a
    # stale/malformed :IN_COMMUNITY edge on READ. Inject one: finance's agent:cfo attached to an
    # engineering community, edge stamped with the COMMUNITY's own namespace (exactly how a buggy
    # write would look — see _write_community) so the test isolates the member-NODE check, not
    # just an edge check. Assert agent:cfo never reaches engineering's member_keys, then clean up.
    eng_comm_id = next((c["id"] for c in comms_on if c["id"].startswith("community:engineering:")), None)
    fail += [] if eng_comm_id else ["(e) no engineering community found to inject the malformed edge into"]
    if eng_comm_id:
        with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
            s.run("MATCH (m:Entity {key:'agent:cfo'}), (c:Community {key:$ck}) "
                  "MERGE (m)-[r:IN_COMMUNITY]->(c) SET r.namespace='engineering'", ck=eng_comm_id)
            try:
                r_leak = serve(q, "engineering", include_communities=True)
                leaked = any(mk == "agent:cfo"
                            for c in (r_leak.get("communities") or []) for mk in c["member_keys"])
                print(f"[comm-e]  malformed edge (agent:cfo -> {eng_comm_id}) leaked into "
                      f"engineering member_keys? {leaked} (must be False)")
                fail += [] if not leaked else \
                    ["(e) malformed :IN_COMMUNITY edge leaked agent:cfo (finance) into engineering member_keys"]
            finally:
                s.run("MATCH (:Entity {key:'agent:cfo'})-[r:IN_COMMUNITY]->(:Community {key:$ck}) DELETE r",
                      ck=eng_comm_id)

    # (g) malformed SEED edge — read-path defense-in-depth on the FIRST match (the seed match scopes
    # c.namespace but, pre-fix, left the seed edge's OWN namespace unchecked). A decoy community
    # (its own namespace IN $allowed, so c.namespace alone would not exclude it) gets ONE legitimate
    # member (agent:cto, a real in-scope entity, via a properly-scoped edge) so it CAN survive the
    # member-expansion match if wrongly selected as a candidate. Then a REAL fused hit (issue:ACME-1)
    # is linked to the decoy via a MALFORMED seed edge whose own namespace is out-of-scope (finance,
    # not in engineering's ["engineering","shared"]). If the seed match doesn't also check the edge's
    # namespace, the decoy leaks in purely off that malformed edge.
    decoy_id = "community:engineering:seed-test-g"
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        s.run("MERGE (c:Community {key:$ck}) SET c.namespace='engineering', c.summary='seed-test decoy'",
              ck=decoy_id)
        s.run("MATCH (m:Entity {key:'agent:cto'}), (c:Community {key:$ck}) "
              "MERGE (m)-[r:IN_COMMUNITY]->(c) SET r.namespace='engineering'", ck=decoy_id)
        s.run("MATCH (e:Entity {key:'issue:ACME-1'}), (c:Community {key:$ck}) "
              "MERGE (e)-[r:IN_COMMUNITY]->(c) SET r.namespace='finance'", ck=decoy_id)
        try:
            r_seed = serve(q, "engineering", include_communities=True)
            seed_leaked = any(c["id"] == decoy_id for c in (r_seed.get("communities") or []))
            print(f"[comm-g]  malformed seed edge (issue:ACME-1 -[ns=finance]-> {decoy_id}) leaked? "
                  f"{seed_leaked} (must be False)")
            fail += [] if not seed_leaked else \
                ["(g) malformed seed :IN_COMMUNITY edge (out-of-scope namespace) leaked a decoy community"]
        finally:
            s.run("MATCH (:Entity {key:'issue:ACME-1'})-[r:IN_COMMUNITY]->(:Community {key:$ck}) DELETE r",
                  ck=decoy_id)
            s.run("MATCH (:Entity {key:'agent:cto'})-[r:IN_COMMUNITY]->(:Community {key:$ck}) DELETE r",
                  ck=decoy_id)
            s.run("MATCH (c:Community {key:$ck}) DELETE c", ck=decoy_id)

    # (h) empty-retrieval envelope consistency: a miss query (no keyword/graph/vector/chunk hits)
    # returns from serve()'s early no-retrieval branch. Flag ON must still carry "communities": []
    # (uniform envelope, never a missing key); flag OFF must carry no such key at all (byte-identical
    # to pre-o46, same contract as (b) above). query_text="" (no pattern) is the guaranteed-empty
    # trigger in THIS env — an arbitrary nonsense string does NOT reach zero rankings here because
    # vector_rung has a real local embedder and returns nearest-neighbor hits for any non-empty text
    # (no similarity floor); "" short-circuits keyword/vector/chunk rungs at their `if query_text`
    # guards the same way corrective.py's graph-only serve(query_text='') calls already rely on.
    r_miss_on = serve("", "engineering", include_communities=True)
    r_miss_off = serve("", "engineering", include_communities=False)
    print(f"[comm-h]  miss query -> flag-on communities={r_miss_on.get('communities')!r} "
          f"flag-off has-key={'communities' in r_miss_off}")
    fail += [] if ("communities" in r_miss_on and r_miss_on["communities"] == []) \
        else ["(h) no-retrieval + flag ON must carry communities:[]"]
    fail += [] if "communities" not in r_miss_off \
        else ["(h) no-retrieval + flag OFF must not carry a communities key"]

    if fail:
        print("COMM_WIRED_FAIL:", fail); sys.exit(1)
    print("COMM_WIRED_OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        _demo()
    elif len(sys.argv) > 1 and sys.argv[1] == "chunk":
        _chunk_demo()
    elif len(sys.argv) > 1 and sys.argv[1] == "communities":
        _communities_demo()
    else:
        import json
        key = sys.argv[1] if len(sys.argv) > 1 else "issue:ACME-1"
        print(json.dumps(node_card(key, ["engineering", "shared"]), indent=2, default=str))
