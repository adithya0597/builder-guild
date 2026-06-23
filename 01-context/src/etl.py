"""D1 ETL spine (the Context-Engineering epic): issue-tracker-shaped structured state -> Neo4j via deterministic
MERGE / MATCH-SET, per the relations.yaml rules. ZERO LLM (pure neo4j driver, no model calls).

SOURCE = FIXTURE stand-in (live tracker API is down). To go live, replace fetch_source()
with the neo4j-graphrag/tracker client GET; everything downstream is unchanged.
"""
from neo4j import GraphDatabase
from datetime import datetime, timezone
import mutate   # R3: the SINGLE write engine — all edge writes route through mutate.apply_edge

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
    # namespace is set ON CREATE only; a re-ingest under a DIFFERENT namespace is an ownership
    # violation and RAISES (FIX-NS at the entity layer — ownership never silently moves, matching
    # mutate.resolve_entity). content_rev still bumps each ingest (the dirty/re-embed trigger).
    # :Episodic/:MENTIONS below is DEFERRED, write-only provenance scaffolding (evidence.py:9-11
    # "named for later, not v1"; decision rqb 2026-06-22 = keep deferred). Its ambient datetime() is
    # INTENTIONALLY left un-threaded to $now: nothing reads the Episodic clock, so a standalone fix
    # would polish unread code. Clock + namespace + a read surface ship together IF provenance is
    # promoted — never as a piecemeal cleanup here.
    rec = tx.run(
        f"MERGE (n:Entity:{label} {{key:$key}}) "
        "ON CREATE SET n.namespace=$ns "
        "SET n.short_context=$short, n.long_context=$long, "
        "    n.content_rev=coalesce(n.content_rev,0)+1, n.dirty=false "
        "WITH n MERGE (e:Episodic {uuid:$ep}) "
        "  ON CREATE SET e.created_at=datetime(), e.valid_at=datetime(), e.namespace=$ns "
        "MERGE (e)-[:MENTIONS]->(n) "
        "RETURN n.namespace AS ns",
        key=key, ns=ns, short=short, long=long_, ep=ep).single()
    if rec["ns"] != ns:
        raise ValueError(f"namespace isolation: {key} is owned by '{rec['ns']}', "
                         f"refusing re-ingest under '{ns}'")


def edge_specs(data, ns=NS):
    """Every edge the source asserts, as (label, subject, rel, object, namespace). Pure data — no
    writes — so ingest can apply each in its OWN transaction (per-fact isolation). All entities are
    upserted before any edge, so endpoint order is irrelevant (fixes the old BLOCKS-before-target gap)."""
    specs = [(f"repo:{r['id']} PART_OF project:{r['project']}",
              f"repo:{r['id']}", "PART_OF", f"project:{r['project']}", ns) for r in data["repos"]]
    for i in data["issues"]:
        k = f"issue:{i['id']}"
        specs.append((f"{k} PART_OF project:{i['project']}", k, "PART_OF", f"project:{i['project']}", ns))
        specs.append((f"{k} ASSIGNED_TO agent:{i['assignee']}", k, "ASSIGNED_TO", f"agent:{i['assignee']}", ns))
        specs.append((f"{k} HAS_STATUS status:{i['status']}", k, "HAS_STATUS", f"status:{i['status']}", ns))
        specs += [(f"{k} BLOCKS issue:{b}", k, "BLOCKS", f"issue:{b}", ns) for b in i["blocks"]]
    return specs


def upsert_entities(tx, data, ep, ns=NS):
    """Phase 1: all entities in one tx (upserts never reject). StatusValues live in 'shared'."""
    for a in data["agents"]:
        upsert_entity(tx, "Agent", f"agent:{a['id']}", f"{a['role']} {a['id']}", f"Agent {a['id']} ({a['role']}).", ep, ns)
    for p in data["projects"]:
        upsert_entity(tx, "Project", f"project:{p['id']}", f"Project {p['id']}", f"Project {p['id']}.", ep, ns)
    for r in data["repos"]:
        upsert_entity(tx, "Repo", f"repo:{r['id']}", f"Repo {r['id']}", f"Repository {r['id']}.", ep, ns)
    for st in {i["status"] for i in data["issues"]}:
        upsert_entity(tx, "StatusValue", f"status:{st}", f"Status {st}", f"Status value {st}.", ep, ns="shared")
    for i in data["issues"]:
        upsert_entity(tx, "Issue", f"issue:{i['id']}", f"Issue {i['id']}: {i['title']}", f"Issue {i['id']} — {i['title']}.", ep, ns)


def ingest(session, data, ep, now, ns=NS):
    """R3: structured ingest via the SINGLE write engine. Entities go through upsert_entity (namespace
    set ON CREATE; a re-ingest under a different namespace RAISES — ownership never silently moves) and
    edges through mutate.apply_edge (arity:1 write-lock FIX-RACE, namespace-scoped supersede FIX-NS,
    explicit clock — no ambient datetime, ONTOLOGY §10).

    TWO-TIER failure handling:
      - Phase 1 (entities, ONE tx): an entity namespace-ownership violation propagates and HALTS the
        ingest — a fatal invariant breach is never skipped.
      - Phase 2 (edges, one tx PER edge): an edge DOMAIN reject (PART_OF arity:1 reject / cycle /
        verbs — all ValueError) is collected to a dead-letter list and SKIPPED so it never rolls back
        the rest of the batch. Infra errors (neo4j.exceptions.*) are deliberately NOT caught — they halt.

    Per-fact isolation makes phase 2 NON-ATOMIC: a halt mid-phase leaves earlier edges committed. That
    is acceptable because every write is idempotent — re-running converges. A clean run RETURNS the
    dead-letter list (empty = all applied); a halt RAISES instead of returning (so the two are
    distinguishable). Takes a `session` (not a tx) because per-fact isolation needs one tx per edge;
    `now` is an explicit ISO clock string for reproducibility."""
    session.execute_write(lambda tx: upsert_entities(tx, data, ep, ns))
    deadletter = []
    for label, s_key, rel, o_key, ens in edge_specs(data, ns):
        try:
            session.execute_write(
                lambda tx, sk=s_key, rl=rel, ok=o_key, en=ens: mutate.apply_edge(tx, sk, rl, ok, now, en, ep))
        except ValueError as e:        # engine domain reject (arity:1 reject / cycle / verbs) -> dead-letter
            deadletter.append({"fact": label, "error": f"{type(e).__name__}: {e}"})
            # infra errors (neo4j.exceptions.*) deliberately NOT caught — they propagate and halt the
            # batch rather than masking an outage as a per-fact skip.
    return deadletter


def counts(tx):
    e = tx.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
    f = tx.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c").single()["c"]
    cur = tx.run("MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at > datetime() RETURN count(r) AS c").single()["c"]
    return e, f, cur


def node_card(tx, key, allowed):
    rec = tx.run(
        "MATCH (i:Entity {key:$key}) WHERE i.namespace IN $allowed "
        "OPTIONAL MATCH (i)-[r:RELATES_TO]->(o:Entity) "
        "  WHERE r.namespace IN $allowed AND o.namespace IN $allowed "
        "    AND r.valid_at <= datetime() AND r.invalid_at > datetime() "
        "RETURN i.long_context AS card, collect(r.name+' -> '+o.key) AS facts",
        key=key, allowed=allowed).single()
    if rec is None or rec["card"] is None:        # key absent or out-of-scope for this role
        return None, []
    return rec["card"], sorted(f for f in rec["facts"] if f)


def status_history(tx, key):
    return [(r["o"], r["cur"]) for r in tx.run(
        "MATCH (i:Entity {key:$key})-[r:RELATES_TO {name:'HAS_STATUS'}]->(o) "
        "RETURN o.key AS o, r.invalid_at > datetime() AS cur ORDER BY cur DESC", key=key)]


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


NOW1, NOW2 = "2026-06-14T00:00:00Z", "2026-06-14T01:00:00Z"   # explicit ETL-run clocks (no ambient datetime)


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))  # clean slate
            dl1 = ingest(s, fetch_source("open"), "etl-run-1", NOW1)
            print("after run 1 (entities, edges, current):", s.execute_read(counts), "| dead-letter:", dl1)
            dl2 = ingest(s, fetch_source("open"), "etl-run-1", NOW1)  # idempotency (same clock)
            print("after re-run  (must be identical):     ", s.execute_read(counts), "| dead-letter:", dl2)
            card, facts = s.execute_read(node_card, "issue:ACME-1", ["engineering", "shared"])
            print("CTO node-card ACME-1:", card, "| current facts:", facts)
            dl3 = ingest(s, fetch_source("closed"), "etl-run-2", NOW2)  # status open->closed (later clock)
            card2, facts2 = s.execute_read(node_card, "issue:ACME-1", ["engineering", "shared"])
            print("after status change: current facts:", facts2, "| dead-letter:", dl3)
            print("HAS_STATUS history (value, current):", s.execute_read(status_history, "issue:ACME-1"))
            print("LLM calls in path: 0 (pure Cypher via the single mutate.apply_edge engine)")
            assert not (dl1 or dl2 or dl3), ("unexpected dead-letter on the clean ACME fixture", dl1, dl2, dl3)
            print("D1_SPINE_OK")


if __name__ == "__main__":
    main()
