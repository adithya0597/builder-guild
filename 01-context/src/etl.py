"""D1 ETL spine (the Context-Engineering epic): issue-tracker-shaped structured state -> Neo4j via deterministic
MERGE / MATCH-SET, per the relations.yaml rules. ZERO LLM (pure neo4j driver, no model calls).

SOURCE = FIXTURE stand-in (live tracker API is down). To go live, replace fetch_source()
with the neo4j-graphrag/tracker client GET; everything downstream is unchanged.
"""
from neo4j import GraphDatabase
from datetime import datetime, timezone

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")


def fetch_source(status_acme1="open"):
    """issue-tracker-shaped state. status_acme1 param lets us simulate a later status change."""
    return {
        "agents":  [{"id": "cto", "role": "CTO"}, {"id": "eng1", "role": "engineer"}],
        "projects":[{"id": "acme"}],
        "repos":   [{"id": "acme/api", "project": "acme"}],
        "issues":  [
            {"id": "ACME-1", "title": "Bolt client timeout", "status": status_acme1,
             "assignee": "eng1", "project": "acme", "blocks": []},
            {"id": "ACME-2", "title": "Add vector index", "status": "in_progress",
             "assignee": "cto", "project": "acme", "blocks": ["ACME-1"]},
        ],
    }

NS = "engineering"   # in live ETL, derived per source's owning CXO domain


def upsert_entity(tx, label, key, short, long_, ep, ns=NS):
    tx.run(
        f"MERGE (n:Entity:{label} {{key:$key}}) "
        "SET n.namespace=$ns, n.short_context=$short, n.long_context=$long, "
        "    n.content_rev=coalesce(n.content_rev,0)+1, n.dirty=false "
        "WITH n MERGE (e:Episodic {uuid:$ep}) "
        "  ON CREATE SET e.created_at=datetime(), e.valid_at=datetime(), e.namespace=$ns "
        "MERGE (e)-[:MENTIONS]->(n)",
        key=key, ns=ns, short=short, long=long_, ep=ep)


def functional_edge(tx, s_key, rel, o_key, ep, ns=NS):
    # supersede: invalidate the current (s)-[rel]-> edge if it points elsewhere
    tx.run("MATCH (s:Entity {key:$s})-[old:RELATES_TO {name:$rel}]->(prev:Entity) "
           "WHERE old.invalid_at IS NULL AND prev.key <> $o "
           "SET old.invalid_at=datetime(), old.expired_at=datetime()",
           s=s_key, rel=rel, o=o_key)
    tx.run("MATCH (s:Entity {key:$s}),(o:Entity {key:$o}) "
           "MERGE (s)-[r:RELATES_TO {name:$rel, namespace:$ns}]->(o) "
           "  ON CREATE SET r.valid_at=datetime(), r.created_at=datetime(), r.episodes=[$ep]",
           s=s_key, o=o_key, rel=rel, ns=ns, ep=ep)


def additive_edge(tx, s_key, rel, o_key, ep, ns=NS):
    tx.run("MATCH (s:Entity {key:$s}),(o:Entity {key:$o}) "
           "MERGE (s)-[r:RELATES_TO {name:$rel, namespace:$ns}]->(o) "
           "  ON CREATE SET r.valid_at=datetime(), r.created_at=datetime(), r.episodes=[$ep]",
           s=s_key, o=o_key, rel=rel, ns=ns, ep=ep)


def ingest(tx, data, ep):
    for a in data["agents"]:
        upsert_entity(tx, "Agent", f"agent:{a['id']}", f"{a['role']} {a['id']}", f"Agent {a['id']} ({a['role']}).", ep)
    for p in data["projects"]:
        upsert_entity(tx, "Project", f"project:{p['id']}", f"Project {p['id']}", f"Project {p['id']}.", ep)
    for r in data["repos"]:
        upsert_entity(tx, "Repo", f"repo:{r['id']}", f"Repo {r['id']}", f"Repository {r['id']}.", ep)
        functional_edge(tx, f"repo:{r['id']}", "PART_OF", f"project:{r['project']}", ep)
    for st in {i["status"] for i in data["issues"]}:
        upsert_entity(tx, "StatusValue", f"status:{st}", f"Status {st}", f"Status value {st}.", ep, ns="shared")
    for i in data["issues"]:
        k = f"issue:{i['id']}"
        upsert_entity(tx, "Issue", k, f"Issue {i['id']}: {i['title']}", f"Issue {i['id']} — {i['title']}.", ep)
        functional_edge(tx, k, "PART_OF", f"project:{i['project']}", ep)
        functional_edge(tx, k, "ASSIGNED_TO", f"agent:{i['assignee']}", ep)
        functional_edge(tx, k, "HAS_STATUS", f"status:{i['status']}", ep)
        for b in i["blocks"]:
            additive_edge(tx, k, "BLOCKS", f"issue:{b}", ep)


def counts(tx):
    e = tx.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
    f = tx.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c").single()["c"]
    cur = tx.run("MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at IS NULL RETURN count(r) AS c").single()["c"]
    return e, f, cur


def node_card(tx, key, allowed):
    rec = tx.run(
        "MATCH (i:Entity {key:$key}) WHERE i.namespace IN $allowed "
        "OPTIONAL MATCH (i)-[r:RELATES_TO]->(o:Entity) "
        "  WHERE r.namespace IN $allowed AND o.namespace IN $allowed "
        "    AND r.valid_at <= datetime() AND (r.invalid_at IS NULL OR r.invalid_at > datetime()) "
        "RETURN i.long_context AS card, collect(r.name+' -> '+o.key) AS facts",
        key=key, allowed=allowed).single()
    return rec["card"], sorted(rec["facts"])


def status_history(tx, key):
    return [(r["o"], r["cur"]) for r in tx.run(
        "MATCH (i:Entity {key:$key})-[r:RELATES_TO {name:'HAS_STATUS'}]->(o) "
        "RETURN o.key AS o, r.invalid_at IS NULL AS cur ORDER BY cur DESC", key=key)]


# ---------------------------------------------------------------------------
# G2 OCR ingestion path (G2) — ADDITIVE, does not touch fetch_source / ingest
# ---------------------------------------------------------------------------

def ingest_ocr_doc(session, image_path, namespace, key, ep=None):
    """OCR a rasterized page image and ingest its text as a graph entity.

    Calls ocr_adapter.extract() -> extracted text -> upsert_entity() with
    long_context=<ocr text>, namespace=<namespace>, key=<key>.

    This function is intentionally isolated from the existing fetch_source / ingest
    path: it adds ONE entity node per image, does not create any RELATES_TO edges,
    and can be called from any session without affecting the structured ETL flow.

    Args:
        session:    open Neo4j driver session (execute_write will be called internally)
        image_path: absolute path to a rasterized page image
        namespace:  graph namespace for the new entity (e.g. "engineering")
        key:        graph key for the new entity (e.g. "doc:ocr-spi-42-scan")
        ep:         episodic uuid; defaults to f"ocr:{key}"
    """
    import ocr_adapter
    ep = ep or f"ocr:{key}"
    ocr_text = ocr_adapter.extract(image_path)
    short = f"OCR document {key}"
    session.execute_write(lambda tx: upsert_entity(tx, "Document", key, short, ocr_text, ep, ns=namespace))
    return ocr_text


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))  # clean slate
            s.execute_write(ingest, fetch_source("open"), "etl-run-1")
            print("after run 1 (entities, edges, current):", s.execute_read(counts))
            s.execute_write(ingest, fetch_source("open"), "etl-run-1")  # idempotency
            print("after re-run  (must be identical):     ", s.execute_read(counts))
            card, facts = s.execute_read(node_card, "issue:ACME-1", ["engineering", "shared"])
            print("CTO node-card ACME-1:", card, "| current facts:", facts)
            s.execute_write(ingest, fetch_source("closed"), "etl-run-2")  # status open->closed
            card2, facts2 = s.execute_read(node_card, "issue:ACME-1", ["engineering", "shared"])
            print("after status change: current facts:", facts2)
            print("HAS_STATUS history (value, current):", s.execute_read(status_history, "issue:ACME-1"))
            print("LLM calls in path: 0 (pure Cypher MERGE/MATCH-SET)")
            print("D1_SPINE_OK")


if __name__ == "__main__":
    main()
