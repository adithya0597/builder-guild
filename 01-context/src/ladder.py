"""F2: the eval-gated retrieval ladder over the ONE graph store.
Rung 1 GRAPH INDEX (default, instant, no LLM) -> Rung 2 VECTOR recall -> Rung 3 PageIndex.
Escalate only when the lower rung is insufficient (eval-gated). The graph SCOPES the PageIndex drill.

Per M1 DoD the graph rung is the spine; vector (needs embeddings -> D3) and PageIndex
(pilot -> H1) are the design's deferred eval-gated escalation rungs.
"""
import os
import re
from neo4j import GraphDatabase
URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))


def keyword_rung(s, allowed, text):
    """Keyword/exact-ID rung (memo §18.2 'keyword retrieval: exact phrases, IDs, issue
    references'). A query token that literally matches an in-scope node key (or its tail after
    the type prefix) is a deterministic hit — exact-ID reference is fact-authority, not fuzz.
    Fixes the lexical-semantic trap (e.g. 'what does ACME-2 block' embeds near 'status=blocked'
    cards instead of ACME-2 itself). Linear scan is fine at this graph size; swap to the FTS
    index when the node count grows."""
    rows = s.run("MATCH (n:Entity) WHERE n.namespace IN $allowed RETURN n.key AS k",
                 allowed=allowed).data()
    toks = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", text.lower()))
    return sorted(r["k"] for r in rows
                  if r["k"].lower() in toks or r["k"].split(":", 1)[-1].lower() in toks)


def graph_rung(s, allowed, pattern):  # instant structural MATCH, role-scoped, current only
    # namespace-scope ALL three: subject, edge AND object (object filter was the codex leak #3).
    q = ("MATCH (i:Entity)-[r:RELATES_TO]->(o:Entity) "
         "WHERE i.namespace IN $allowed AND r.namespace IN $allowed AND o.namespace IN $allowed "
         "  AND r.name=$rel AND o.key=$obj AND r.invalid_at > datetime() "
         "RETURN i.key AS hit ORDER BY hit")
    return [rec["hit"] for rec in s.run(q, allowed=allowed, rel=pattern["rel"], obj=pattern["obj"])]


def vector_available(s):
    return s.run("MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN count(n) AS c").single()["c"] > 0


def _vector_query(s, allowed, qv, k):
    """Escalating post-filtered ANN over node_embedding (10o recall-cliff fix).
    db.index.vector.queryNodes returns top-N by cosine BLIND to namespace; we post-filter to the
    role's slice. A FIXED over-fetch (the old k*5) can return <k in-scope under HIGH namespace
    selectivity — in-scope hits ranked beyond the window are silently lost (the recall cliff).
    Fix: ESCALATE the over-fetch (k*5, then *5 each round) capped at the embedded-node count, until
    >=k in-scope hits OR the whole embedded set has been scanned (worst case = exact scan, no cliff).
    Cheap in the common low-selectivity case (k*5 returns immediately)."""
    total = s.run("MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN count(n) AS c").single()["c"]
    Q = ("CALL db.index.vector.queryNodes('node_embedding', $over, $q) YIELD node, score "
         "WHERE node.namespace IN $allowed "
         "RETURN node.key AS key, node.namespace AS ns, score ORDER BY score DESC LIMIT $k")
    over = k * 5
    while True:
        hits = s.run(Q, q=qv, allowed=allowed, k=k, over=min(over, max(total, 1))).data()
        if len(hits) >= k or over >= total:
            return hits
        over *= 5


def vector_rung(s, allowed, text, k=3):
    """Rung 2 (INT-2): real vector recall. Embed the query (local EmbeddingGemma), queryNodes the
    HNSW index, NAMESPACE-FILTER to the role's slice, cap at k. The over-fetch ESCALATES to defeat
    the recall cliff under high namespace selectivity (see _vector_query, 10o).
    OPTIONAL-DEP RESILIENCE: vector is an escalation rung — if the OPTIONAL embedder
    (sentence-transformers) is absent, return [] so the graph/keyword rungs still serve (the
    $0/local core runs without it). NARROW catch (red-team RT-1): sentence_transformers is
    lazy-imported INSIDE embed(), so the catch must wrap embed(text) — but only a missing
    sentence_transformers degrades; ANY OTHER ModuleNotFoundError (torch / a broken ST backend /
    embed / neo4j) PROPAGATES, so a genuinely broken embedder can't masquerade as 'no vector hits'."""
    try:
        from embed import embed
        qv = embed(text)
    except ModuleNotFoundError as e:
        if e.name == "sentence_transformers":     # optional embedder absent -> graceful degrade
            return []
        raise                                     # real failure (torch/embed/neo4j/...) -> surface it
    return _vector_query(s, allowed, qv, k)


def chunk_vector_available(s):
    return s.run("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c) AS c").single()["c"] > 0


def _chunk_vector_query(s, allowed, qv, k):
    """Escalating post-filtered ANN over chunk_embedding (cf7 rung 2b; SAME 10o cliff fix as
    _vector_query). queryNodes returns :Chunk nodes BLIND to namespace; post-filter to the role's
    chunks, resolve each to its parent :Entity, and DEDUPE to the best-scoring chunk per parent (one
    parent = one fused hit, carrying its best-matching passage in `chunk`). Escalate the over-fetch
    until >=k DISTINCT in-scope parents OR the whole chunk set is scanned (worst case = exact scan, no
    cliff). Rows arrive score-desc, so the first chunk seen per parent is that parent's best passage.

    emh (scale): the escalating SCAN returns only lightweight identity+score per chunk
    (parent_key/ns/chunk_key/score) — NOT the full passage text. node.text is fetched in ONE
    namespace-scoped follow-up read for just the <=k deduped SURVIVORS (the passages serve actually
    surfaces), so a high-selectivity full scan no longer drags every chunk's text across the wire on
    every round. Return shape is unchanged: [{key, ns, chunk_key, chunk(text), score}]."""
    total = s.run("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c) AS c").single()["c"]
    Q = ("CALL db.index.vector.queryNodes('chunk_embedding', $over, $q) YIELD node, score "
         "WHERE node.namespace IN $allowed "
         "RETURN node.parent_key AS key, node.namespace AS ns, node.key AS chunk_key, "
         "       score ORDER BY score DESC")
    over = k * 5
    while True:
        rows = s.run(Q, q=qv, allowed=allowed, over=min(over, max(total, 1))).data()
        best = {}                                 # parent -> best (first-seen = highest score)
        for r in rows:
            best.setdefault(r["key"], r)
        if len(best) >= k or over >= total:
            survivors = list(best.values())[:k]
            # fetch the SELECTED passage text only for the survivors, by chunk_key, in one read;
            # namespace-scoped (belt + suspenders — survivors already passed the scan's ns filter).
            ckeys = [r["chunk_key"] for r in survivors]
            texts = {t["ck"]: t["txt"] for t in s.run(
                "MATCH (c:Chunk) WHERE c.key IN $ck AND c.namespace IN $allowed "
                "RETURN c.key AS ck, c.text AS txt", ck=ckeys, allowed=allowed)}
            for r in survivors:
                r["chunk"] = texts.get(r["chunk_key"])
            return survivors
        over *= 5


def chunk_rung(s, allowed, text, k=3):
    """Rung 2b (cf7): chunk-level vector recall — "which passage". Embed the query (local
    EmbeddingGemma), queryNodes the chunk_embedding HNSW index, NAMESPACE-FILTER, resolve each :Chunk
    to its parent :Entity, dedupe to the best passage per parent, cap at k distinct parents. The
    over-fetch ESCALATES to defeat the recall cliff (10o). SAME optional-dep resilience as vector_rung:
    a missing sentence_transformers degrades to [] (graph/keyword still serve); any other failure
    propagates. Returns [{key(=parent), ns, chunk_key, chunk(text), score}] — `key` feeds RRF fusion,
    `chunk` is the selected passage serve surfaces (bzr)."""
    try:
        from embed import embed
        qv = embed(text)
    except ModuleNotFoundError as e:
        if e.name == "sentence_transformers":     # optional embedder absent -> graceful degrade
            return []
        raise                                     # real failure -> surface it
    return _chunk_vector_query(s, allowed, qv, k)


def retrieve(query):
    allowed = query["allowed"]
    k = query.get("t_cap", 3)
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        trace = []
        if query.get("pattern"):                                   # Rung 1: graph index (default)
            hits = graph_rung(s, allowed, query["pattern"])
            trace.append({"rung": 1, "name": "graph_index", "instant": True, "llm": False, "hits": hits})
            if hits:
                return {"resolved_at": "graph_index", "llm_calls": 0, "hits": hits, "trace": trace}
        if query.get("text") and vector_available(s):              # Rung 2: vector recall (escalate)
            vhits = vector_rung(s, allowed, query["text"], k)
            trace.append({"rung": 2, "name": "vector", "llm": False, "hits": vhits})
            if vhits:
                return {"resolved_at": "vector", "llm_calls": 0, "hits": vhits, "trace": trace}
        else:
            trace.append({"rung": 2, "name": "vector",
                          "status": "ready" if vector_available(s) else "GATED: no embeddings",
                          "note": "no query text" if not query.get("text") else "no in-scope hits"})
        # NOTE: chunk-vector (rung 2b, chunk_rung) is NOT wired into this first-hit-escalation ladder.
        # retrieve() returns at the first rung that hits, and node-vector (rung 2) hits for almost any
        # query (cosine always ranks something in-scope), so a 2b branch here would be near-unreachable.
        # Chunk-vector recall lives in serve()'s PARALLEL-FUSION path (serve.py: chunk_rung joins RRF +
        # surfaces the selected passage), which is the read path that benefits from "which passage" recall.
        longdocs = [r["k"] for r in s.run(                          # Rung 3: PageIndex (graph-scoped)
            "MATCH (n:Entity) WHERE n.pageindex_ref IS NOT NULL AND n.namespace IN $allowed RETURN n.key AS k",
            allowed=allowed)]
        trace.append({"rung": 3, "name": "pageindex",
                      "status": "GATED: pilot H1",
                      "graph_scopes_drill_to": longdocs or "no long-doc node in scope"})
        return {"resolved_at": "escalated", "trace": trace}


def demo():
    """INT-2: real vector recall on the LIVE graph, namespace-scoped."""
    import sys
    from scope import scope
    fail = []
    # DRIFT NOTE (etl fixture vs validated golden; bead 11b reconciles): demos retrieve against the
    # LIVE etl seed, so they speak the etl vocabulary — etl ACME-2 = "Add vector index". The validated
    # golden (03-evals/example_golden.jsonl) instead has ACME-2 = "rate-limit backoff". Do NOT treat
    # the demo's ACME semantics as canonical; aligning the seed to the golden is founder-gated (11b).
    q = "add a vector index for embedding similarity search"   # best global match = issue:ACME-2 (engineering "Add vector index")

    eng = retrieve({**scope("engineering"), "text": q})
    fin = retrieve({**scope("finance"), "text": q})
    eng_hits = [(h["key"], h["ns"], round(h["score"], 3)) for h in eng.get("hits", [])]
    fin_hits = [(h["key"], h["ns"], round(h["score"], 3)) for h in fin.get("hits", [])]
    print(f"[vector] engineering query -> resolved_at={eng['resolved_at']} hits={eng_hits}")
    print(f"[vector] finance     query -> resolved_at={fin['resolved_at']} hits={fin_hits}")

    # engineering: vector rung fires, all hits in its slice
    fail += [] if (eng["resolved_at"] == "vector" and eng_hits
                   and all(ns in ("engineering", "shared") for _, ns, _ in eng_hits)) \
        else ["engineering vector rung failed or leaked"]
    # ISOLATION: the best global match (ACME-2, engineering) must NOT surface for a finance role;
    # every finance hit must be in finance/shared
    fin_keys = [k for k, _, _ in fin_hits]
    fail += [] if (fin_hits                                          # NON-VACUOUS: finance must return its OWN slice
                   and "issue:ACME-2" not in fin_keys                # ...but never the engineering best-match (ACME-2)
                   and all(ns in ("finance", "shared") for _, ns, _ in fin_hits)) \
        else ["finance vector rung leaked an out-of-slice node OR returned nothing (vacuous isolation)"]
    print(f"[isolate] ACME-2 (engineering) in finance results? {'issue:ACME-2' in fin_keys} (must be False)")

    if fail:
        print("INT2_FAIL:", fail); sys.exit(1)
    print("INT2_OK")


def _recall_selftest():
    """10o recall-cliff self-test — NO ML dep (synthetic vectors), runs on live Neo4j.
    Seeds 50 OUT-namespace nodes whose embedding == the query vector (cosine 1.0, so they occupy the
    top ANN ranks) and 1 IN-namespace node at cosine ~0.9 (ranked below the OUT block). A FIXED
    over-fetch of 5 returns only OUT nodes -> 0 in-scope (the cliff); the escalating _vector_query
    must still find the IN node. Proves the fix defeats the cliff without real embeddings."""
    import sys
    D = 768
    qv = [1.0] + [0.0] * (D - 1)
    out_vec = [1.0] + [0.0] * (D - 1)               # cosine 1.0 to qv -> top ranks
    in_vec = [0.9, 0.4358899] + [0.0] * (D - 2)     # cosine ~0.9 to qv -> ranked below the OUT block
    NS_IN, NS_OUT = "recall_test_in", "recall_test_out"
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        s.run("MATCH (n:Entity) WHERE n.namespace STARTS WITH 'recall_test' DETACH DELETE n")
        try:
            for i in range(50):
                s.run("CREATE (n:Entity {key:$k, namespace:$ns, embedding:$v})",
                      k=f"rt:out:{i}", ns=NS_OUT, v=out_vec)
            s.run("CREATE (n:Entity {key:'rt:in:1', namespace:$ns, embedding:$v})", ns=NS_IN, v=in_vec)
            s.run("CALL db.awaitIndexes()")
            # the OLD fixed k*5=5 over-fetch (simulated) misses the in-scope node = the cliff:
            fixed = s.run(
                "CALL db.index.vector.queryNodes('node_embedding', 5, $q) YIELD node "
                "WHERE node.namespace = $ns RETURN node.key AS k", q=qv, ns=NS_IN).data()
            # the ESCALATING query (the fix) finds it:
            got = _vector_query(s, [NS_IN], qv, k=1)
        finally:                                  # RT-3: crash-safe cleanup (shared local DB)
            s.run("MATCH (n:Entity) WHERE n.namespace STARTS WITH 'recall_test' DETACH DELETE n")
    fixed_found = any(r["k"] == "rt:in:1" for r in fixed)
    esc_found = any(r["key"] == "rt:in:1" for r in got)
    print(f"[recall] fixed k*5 found in-scope? {fixed_found} (expect False = the cliff) | "
          f"escalating found? {esc_found} (expect True = fixed)")
    if not esc_found or fixed_found:
        print("RECALL_SELFTEST_FAIL"); sys.exit(1)
    print("RECALL_SELFTEST_OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--recall-selftest":
        _recall_selftest()
    else:
        demo()
