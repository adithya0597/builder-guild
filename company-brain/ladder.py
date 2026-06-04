"""F2 (beads cb-ax8.3): the eval-gated retrieval ladder over the ONE graph store.
Rung 1 GRAPH INDEX (default, instant, no LLM) -> Rung 2 VECTOR recall -> Rung 3 PageIndex.
Escalate only when the lower rung is insufficient (eval-gated). The graph SCOPES the PageIndex drill.

Per M1 DoD the graph rung is the spine; vector (needs embeddings -> D3 cb-dfv.3) and PageIndex
(pilot -> H1 cb-hjv.4) are the design's deferred eval-gated escalation rungs.
"""
from neo4j import GraphDatabase
URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")


def graph_rung(s, allowed, pattern):  # instant structural MATCH, role-scoped, current only
    q = ("MATCH (i:Entity)-[r:RELATES_TO]->(o:Entity) "
         "WHERE i.namespace IN $allowed AND r.namespace IN $allowed "
         "  AND r.name=$rel AND o.key=$obj AND r.invalid_at IS NULL "
         "RETURN i.key AS hit ORDER BY hit")
    return [rec["hit"] for rec in s.run(q, allowed=allowed, rel=pattern["rel"], obj=pattern["obj"])]


def vector_available(s):
    return s.run("MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN count(n) AS c").single()["c"] > 0


def retrieve(query):
    allowed = query["allowed"]
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        trace = []
        if query.get("pattern"):                                   # Rung 1: graph index (default)
            hits = graph_rung(s, allowed, query["pattern"])
            trace.append({"rung": 1, "name": "graph_index", "instant": True, "llm": False, "hits": hits})
            if hits:
                return {"resolved_at": "graph_index", "llm_calls": 0, "hits": hits, "trace": trace}
        trace.append({"rung": 2, "name": "vector",                 # Rung 2: vector recall (escalate)
                      "status": "ready" if vector_available(s) else "GATED: embeddings pending D3 (cb-dfv.3)"})
        longdocs = [r["k"] for r in s.run(                          # Rung 3: PageIndex (graph-scoped)
            "MATCH (n:Entity) WHERE n.pageindex_ref IS NOT NULL AND n.namespace IN $allowed RETURN n.key AS k",
            allowed=allowed)]
        trace.append({"rung": 3, "name": "pageindex",
                      "status": "GATED: pilot H1 (cb-hjv.4)",
                      "graph_scopes_drill_to": longdocs or "no long-doc node in scope"})
        return {"resolved_at": "escalated", "trace": trace}


if __name__ == "__main__":
    import json
    print("== structural query (assigned_to eng1) — resolves at graph rung, instant, 0 LLM ==")
    print(json.dumps(retrieve({"allowed": ["engineering", "shared"],
                               "pattern": {"rel": "ASSIGNED_TO", "obj": "agent:eng1"}}), indent=2, default=str))
    print("== fuzzy query (no graph pattern) — escalates through gated rungs ==")
    print(json.dumps(retrieve({"allowed": ["engineering", "shared"]}), indent=2, default=str))
