"""Serve-side context management.

F1: a node-card is assembled at READ = long_context (stable) + a LIVE bi-temporal
edge query, role-scoped by namespace and validity+freshness stamped. Nothing fact-inclusive is
cached — the card is built per request, so it is always current (PART 3-B).
"""
import re
from neo4j import GraphDatabase
URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")

# Role-scoped, validity-stamped node-card. as_of=None => now.
NODE_CARD = """
MATCH (i:Entity {key:$key}) WHERE i.namespace IN $allowed
OPTIONAL MATCH (i)-[r:RELATES_TO]->(o:Entity)
  WHERE r.namespace IN $allowed AND o.namespace IN $allowed
WITH i, r, o ORDER BY r.name, o.key
RETURN i.key AS node, i.long_context AS long_context, coalesce(i.dirty,false) AS fresh_dirty,
  [x IN collect(CASE WHEN r IS NULL THEN NULL ELSE {
     fact: r.name + ' -> ' + o.key,
     validity: CASE WHEN r.invalid_at IS NULL THEN 'current' ELSE 'historical' END,
     valid_at: toString(r.valid_at)
   } END) WHERE x IS NOT NULL] AS facts
"""

def node_card(key, allowed):
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        rec = s.run(NODE_CARD, key=key, allowed=allowed).single()
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

    CANONICALIZATION: the question names BARE ids ("SPI-3"); retrieved keys are PREFIXED
    ("issue:SPI-3", "agent:cto"). Intersecting them raw never matches -> coverage collapses to 0.0
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


def serve(query_text, role, pattern=None, action=None):
    """INT-3: the end-to-end serve chain on the real graph. WIRES the modules:
    scope -> graph_rung + vector_rung -> fuse(RRF) -> epist(authority) -> stamp -> reconcile ->
    gate+abstain (sufficiency x confidence, suggest-only) -> execute.

    Honest scope (per codex review 2026-06-05):
      - runs the graph + vector rungs IN PARALLEL for fusion — it does NOT use ladder.retrieve()'s
        first-hit eval-gated ESCALATION (fusion needs both sources; escalation short-circuits). These
        are two different retrieval modes; serve() deliberately uses the fusion mode.
      - fuse.cross_encoder_rerank is available but NOT invoked here — serve() does RRF only.
        With a single non-empty source, RRF degrades to identity ranking (not true fusion).
      - sufficiency/confidence are PROXIES (not validated evidence quality) — calibrated in H2b.
    SECURITY: `role` is TRUSTED here. It must be AUTHENTICATED upstream — a self-asserted
    role='governance' would read all namespaces. Do not expose `role` to an unauthenticated caller.
    """
    import scope as _scope, ladder, fuse, stamp, reconcile, abstain
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
        trace["retrieve"] = {"keyword": kw_hits, "graph": graph_hits, "vector": vec_keys}

        # 2. FUSE — RRF across whichever sources fired. fuse.rrf breaks RRF score-ties by SOURCE
        # AUTHORITY (keyword > graph > vector), so an exact-ID reference beats an equally-ranked
        # fuzzy hit (RC2 fix — previously a doc_id alphabetical tie-break dropped that authority;
        # full weighted RRF is the R7 upgrade).
        rankings = {**({"keyword": kw_hits} if kw_hits else {}),
                    **({"graph": graph_hits} if graph_hits else {}),
                    **({"vector": vec_keys} if vec_keys else {})}
        if not rankings:
            return {"decision": "abstain", "mode": sc and "suggest", "reason": "no in-scope retrieval", "trace": trace}
        fused = fuse.rrf(rankings)
        fused_keys = [kk for kk, _ in fused]
        primary = fused_keys[0]
        trace["fuse"] = {"fused_top": fused[:k]}

        # 3. EPIST — source authority (keyword/graph = fact-authority > vector = recall)
        sources = {kk: ("keyword" if kk in kw_hits else "graph" if kk in graph_hits else "vector")
                   for kk in fused_keys}
        trace["epist"] = {"primary_source": sources[primary], "authority": "keyword=graph>vector"}

        # 4. STAMP + 5. RECONCILE — the primary node's card (o.namespace-isolated)
        rec = s.run(stamp.CARD_Q, key=primary, allowed=allowed).single()
        facts = stamp.stamp_card(rec)
        node_fresh = "stale" if rec["node_dirty"] else "fresh"
        card = reconcile.reconcile(node_fresh, facts)
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
            for f in stamp.freshness_judge(stamp.stamp_card(crec)):
                composed.append(f"{kk}: {f['fact']}")
                m = re.search(r"->\s*(\S+)", f["fact"])
                if m:
                    expand.append(m.group(1))
        shown = list(fused_keys[:k])
        for kk in shown:
            _add_card(kk)
        # 1-HOP EXPANSION (R2b): multi-hop answers need the TARGET card too (e.g. "SPI-2 blocks
        # SPI-3, who owns SPI-3?" — SPI-3's card carries the second hop). One hop only, in-scope
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

        # 6+7. GATE + ABSTAIN — claims from presentable facts; sufficiency x confidence, suggest-only
        claims = [{"id": f["fact"], "support_status": "SUPPORTED",
                   "stale": f["fresh"] == "stale", "conflict": False} for f in card["presentable"]]
        if not claims:
            claims = [{"id": primary, "support_status": "UNSUPPORTED", "stale": False, "conflict": False}]
        # confidence basis is EXPLICIT (codex: no fabricated 0.9). A vector hit uses its cosine
        # score; a graph-only hit is an exact structural MATCH = high-certainty by construction
        # (fact-authority), labelled as such — not a pretend score.
        vec_score = next((h["score"] for h in vec_hits if h["key"] == primary), None)
        if vec_score is not None:
            self_conf, conf_basis = round(min(0.99, vec_score), 2), "vector_score"
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
    """INT-3: one real query runs the FULL chain end-to-end on the live graph; trace each stage."""
    import sys, json
    r = serve("rate limit backoff for the inference client", "engineering")
    print(json.dumps(r["trace"], indent=2, default=str))
    print(f"\n[serve] primary={r['primary']} decision={r['decision']} mode={r['mode']} "
          f"executed={r['executed']}")
    print(f"[serve] presentable_facts={r['presentable_facts']}")
    stages = {"retrieve", "fuse", "epist", "stamp_reconcile", "gate_abstain"}
    ok = stages <= set(r["trace"]) and r["decision"] in ("pass", "partial", "abstain", "escalate")
    print("INT3_OK" if ok else f"INT3_FAIL stages={set(r['trace'])} decision={r['decision']}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        _demo()
    else:
        import json
        key = sys.argv[1] if len(sys.argv) > 1 else "issue:SPI-1"
        print(json.dumps(node_card(key, ["engineering", "shared"]), indent=2, default=str))
