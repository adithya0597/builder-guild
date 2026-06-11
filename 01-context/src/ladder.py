"""F2 (beads cb-ax8.3): the eval-gated retrieval ladder over the ONE graph store.
Rung 1 GRAPH INDEX (default, instant, no LLM) -> Rung 2 VECTOR recall -> Rung 3 PageIndex.
Escalate only when the lower rung is insufficient (eval-gated). The graph SCOPES the PageIndex drill.

Per M1 DoD the graph rung is the spine; vector (needs embeddings -> D3 cb-dfv.3) and PageIndex
(pilot -> H1 cb-hjv.4) are the design's deferred eval-gated escalation rungs.
"""
import re
from neo4j import GraphDatabase
URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")


def keyword_rung(s, allowed, text):
    """Keyword/exact-ID rung (cb-s36; memo §18.2 'keyword retrieval: exact phrases, IDs, issue
    references'). A query token that literally matches an in-scope node key (or its tail after
    the type prefix) is a deterministic hit — exact-ID reference is fact-authority, not fuzz.
    Fixes the lexical-semantic trap (e.g. 'what does SPI-2 block' embeds near 'status=blocked'
    cards instead of SPI-2 itself). Linear scan is fine at this graph size; swap to the FTS
    index (cb-6a1.6) when the node count grows."""
    rows = s.run("MATCH (n:Entity) WHERE n.namespace IN $allowed RETURN n.key AS k",
                 allowed=allowed).data()
    toks = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", text.lower()))
    return sorted(r["k"] for r in rows
                  if r["k"].lower() in toks or r["k"].split(":", 1)[-1].lower() in toks)


def graph_rung(s, allowed, pattern):  # instant structural MATCH, role-scoped, current only
    # namespace-scope ALL three: subject, edge AND object (object filter was the codex leak #3).
    q = ("MATCH (i:Entity)-[r:RELATES_TO]->(o:Entity) "
         "WHERE i.namespace IN $allowed AND r.namespace IN $allowed AND o.namespace IN $allowed "
         "  AND r.name=$rel AND o.key=$obj AND r.invalid_at IS NULL "
         "RETURN i.key AS hit ORDER BY hit")
    return [rec["hit"] for rec in s.run(q, allowed=allowed, rel=pattern["rel"], obj=pattern["obj"])]


def vector_available(s):
    return s.run("MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN count(n) AS c").single()["c"] > 0


def vector_rung(s, allowed, text, k=3):
    """Rung 2 (INT-2 cb-djp.2): real vector recall. Embed the query (local EmbeddingGemma),
    queryNodes the HNSW index, then NAMESPACE-FILTER to the role's slice and cap at k.
    Over-fetch (k*5) so namespace filtering still yields up to k in-scope hits."""
    from embed import embed
    qv = embed(text)
    return s.run(
        "CALL db.index.vector.queryNodes('node_embedding', $over, $q) YIELD node, score "
        "WHERE node.namespace IN $allowed "
        "RETURN node.key AS key, node.namespace AS ns, score ORDER BY score DESC LIMIT $k",
        q=qv, allowed=allowed, k=k, over=k * 5).data()


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
        longdocs = [r["k"] for r in s.run(                          # Rung 3: PageIndex (graph-scoped)
            "MATCH (n:Entity) WHERE n.pageindex_ref IS NOT NULL AND n.namespace IN $allowed RETURN n.key AS k",
            allowed=allowed)]
        trace.append({"rung": 3, "name": "pageindex",
                      "status": "GATED: pilot H1 (cb-hjv.4)",
                      "graph_scopes_drill_to": longdocs or "no long-doc node in scope"})
        return {"resolved_at": "escalated", "trace": trace}


def demo():
    """INT-2 (cb-djp.2): real vector recall on the LIVE graph, namespace-scoped."""
    import sys
    from scope import scope
    fail = []
    q = "rate limit backoff for the inference client"          # best global match = issue:SPI-2 (engineering)

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
    # ISOLATION: the best global match (SPI-2, engineering) must NOT surface for a finance role;
    # every finance hit must be in finance/shared
    fin_keys = [k for k, _, _ in fin_hits]
    fail += [] if ("issue:SPI-2" not in fin_keys
                   and all(ns in ("finance", "shared") for _, ns, _ in fin_hits)) \
        else ["finance vector rung leaked an out-of-slice node"]
    print(f"[isolate] SPI-2 (engineering) in finance results? {'issue:SPI-2' in fin_keys} (must be False)")

    if fail:
        print("INT2_FAIL:", fail); sys.exit(1)
    print("INT2_OK")


if __name__ == "__main__":
    demo()
