"""Serve-side context management (beads cb-ax8.*).

F1 (cb-ax8.1): a node-card is assembled at READ = long_context (stable) + a LIVE bi-temporal
edge query, role-scoped by namespace and validity+freshness stamped. Nothing fact-inclusive is
cached — the card is built per request, so it is always current (PART 3-B).
"""
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

if __name__ == "__main__":
    import json, sys
    key = sys.argv[1] if len(sys.argv) > 1 else "issue:ACME-1"
    print(json.dumps(node_card(key, ["engineering", "shared"]), indent=2, default=str))
