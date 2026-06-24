"""Serve-side context management.

F1: a node-card is assembled at READ = long_context (stable) + a LIVE bi-temporal
edge query, role-scoped by namespace and validity+freshness stamped. Nothing fact-inclusive is
cached — the card is built per request, so it is always current (PART 3-B).
"""
import re
import yaml
from pathlib import Path
from neo4j import GraphDatabase
URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
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


def serve(query_text, role, pattern=None, action=None, deep_serve=False, rerank=False):
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
            return {"query": query_text, "role": role, "primary": None, "presentable_facts": [],
                    "composed_evidence": [], "decision": "abstain", "mode": "suggest",
                    "reason": "no in-scope retrieval", "executed": False, "provenance": {}, "trace": trace}
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
            ctx = s.run("MATCH (n:Entity {key:$k}) WHERE n.namespace IN $allowed "
                        "RETURN n.long_context AS ctx", k=kk, allowed=allowed).single()
            if ctx and ctx["ctx"]:
                composed.append(f"content({kk}): {ctx['ctx'][:200]}")
            # bzr: a node retrieved via chunk-vector (rung 2b) surfaces its SELECTED passage — the chunk
            # the query actually matched — not just the long_context abstract (whose [:200] truncation may
            # cut before the relevant span). Only the ONE selected chunk is surfaced (chunk_passages is
            # already deduped to the best passage per parent), so this never bloats the answer with all
            # chunks (the bzr concern). This is the read that makes embed.py's n.chunks no longer dead.
            if kk in chunk_passages:
                composed.append(f"content_chunk({kk}): {chunk_passages[kk][:200]}")
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

    return {"query": query_text, "role": role, "primary": primary,
            "presentable_facts": [f["fact"] for f in card["presentable"]],
            "composed_evidence": composed,
            "decision": decision["final"], "mode": decision["mode"],
            "executed": executed["executed"], "provenance": sources, "trace": trace}


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
                                  text=_DRILL["answer"], source_path="/docs/context-evals.md",
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


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        _demo()
    elif len(sys.argv) > 1 and sys.argv[1] == "chunk":
        _chunk_demo()
    else:
        import json
        key = sys.argv[1] if len(sys.argv) > 1 else "issue:ACME-1"
        print(json.dumps(node_card(key, ["engineering", "shared"]), indent=2, default=str))
