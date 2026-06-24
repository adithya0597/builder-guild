"""44d: the embed-the-seed SETUP STEP for the embedding-path demos.

The structured ETL (etl.py) writes the ACME spine as PLAIN nodes — it does NOT embed (D1 is the
$0 graph spine; embeddings are the D3 increment). The embedding-path demos (ladder.py INT2,
serve.py INT3) need the persistent seed to carry n.embedding so the vector rung can fire, plus a
couple of nodes the structured ETL never creates. This module is the bridge.

  SEQUENCE (CI + local):   etl.py  ->  demo_seed.py  ->  ladder.py / serve.py demo

NON-HERMETIC (deliberate): unlike the self-seeding unit demos (embed/sweep/retention_sweep, which
seed a throwaway namespace + tear down in try/finally), this is a PIPELINE setup step — it MUTATES
the persistent engineering/finance/shared namespaces and has NO teardown, assuming etl.py ran its
clean-slate first. Re-running is idempotent (MERGE + deterministic re-embed); embed_all() MUST
follow seed_extras() in the same run so the freshness stamps stay consistent.

What it adds (idempotent MERGE; BARE entities, NO hand-written RELATES_TO — so the write-gateway
gate is untouched: the isolation / deep-rung tests need node PRESENCE + an embedding, not edges):
  - agent:cfo + issue:ACME-4   (finance)  -> ladder INT2 isolation: a present-but-FILTERED finance
                                             node, so the test proves the namespace filter rather
                                             than passing vacuously on an empty finance slice.
  - extsrc:context-evals       (shared)   -> serve INT3 deep-rung signal: a long-doc node carrying
                                             pageindex_ref + a NON-EMPTY pageindex_doc_sha, which is
                                             what serve()'s deep_warranted requires.

embed_all() is the general embed-the-seed pass: every :Entity with long_context gets a 768-d
EmbeddingGemma vector via embed.embed_node (kind=prose). $0 / local — the model runs on-box, no API.
"""
import sys
from neo4j import GraphDatabase
from mutate import resolve_entity
from embed import embed_node

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
NOW = "2026-06-14T02:00:00Z"   # explicit clock (no ambient datetime); after etl's NOW1/NOW2

# A fixed, NON-EMPTY stand-in tree-sha (a real PageIndex deploy stamps the true sha). Non-empty is
# the load-bearing property: serve()'s deep_warranted requires `pageindex_doc_sha <> ''`.
CTX_EVALS_SHA = "demo-sha-context-evals-0001"

# the demo-critical nodes the embedding-path demos structurally depend on (presence + embedding)
DEMO_CRITICAL = ["issue:ACME-2", "issue:ACME-4", "extsrc:context-evals"]


def seed_extras(session, now=NOW):
    """Idempotent MERGE of the extra nodes the embedding-path demos need beyond etl's ACME-1/ACME-2.
    BARE entities only (no RELATES_TO) — presence + an embedding is all the isolation / deep-rung
    tests require, so this never touches the current-edge write path (write-gateway gate untouched)."""
    # finance isolation node (+ its owner): a real finance-namespace vector hit so the ladder INT2
    # finance role returns something IN-SLICE while the engineering node stays filtered out.
    session.execute_write(lambda tx: resolve_entity(
        tx, "Agent", "agent:cfo", now, "finance", short="CFO cfo", long_="Agent cfo (CFO)."))
    session.execute_write(lambda tx: resolve_entity(
        tx, "Issue", "issue:ACME-4", now, "finance",
        short="Issue ACME-4: Q3 inference budget cap",
        long_="Issue ACME-4 — Q3 inference budget cap controlling embedding and GPU inference spend."))
    # serve-join long-doc node (shared): pageindex_ref + a NON-EMPTY doc-sha => deep_warranted signal.
    session.execute_write(lambda tx: resolve_entity(
        tx, "ExternalSource", "extsrc:context-evals", now, "shared",
        short="Sufficient Context paper",
        long_="The sufficient-context paper studies when a model should abstain versus answer under "
              "low retrieval coverage; it finds abstention beats answering on insufficient context."))
    session.execute_write(lambda tx: tx.run(
        "MATCH (n:Entity {key:'extsrc:context-evals'}) SET n.pageindex_ref=$ref, n.pageindex_doc_sha=$sha",
        ref="/docs/context-evals.md", sha=CTX_EVALS_SHA))


def embed_all(session, now=NOW):
    """The embed-the-seed pass: embed EVERY content-bearing :Entity (768-d, kind=prose). Returns the
    count embedded. Idempotent — re-running re-embeds (deterministic vectors, cheap on this size)."""
    keys = [r["k"] for r in session.run(
        "MATCH (n:Entity) WHERE n.long_context IS NOT NULL RETURN n.key AS k ORDER BY k")]
    for k in keys:
        content = session.run("MATCH (n:Entity {key:$k}) RETURN n.long_context AS c", k=k).single()["c"]
        session.execute_write(lambda tx, k=k, c=content: embed_node(tx, k, c, "prose", now))
    return len(keys)


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            seed_extras(s)
            n = embed_all(s)
            emb = s.run("MATCH (n:Entity) WHERE n.embedding IS NOT NULL RETURN count(n) AS c").single()["c"]
            present = {r["k"] for r in s.run(
                "MATCH (n:Entity) WHERE n.key IN $need AND n.embedding IS NOT NULL RETURN n.key AS k",
                need=DEMO_CRITICAL)}
            sha_ok = s.run("MATCH (n:Entity {key:'extsrc:context-evals'}) "
                           "RETURN n.pageindex_doc_sha AS s").single()["s"]
    print(f"[demo_seed] embedded {n} content nodes (graph now has {emb} embedded entities)")
    print(f"[demo_seed] demo-critical nodes embedded: {sorted(present)} | extsrc doc_sha={sha_ok!r}")
    fail = []
    fail += [] if emb > 0 else ["no embeddings written"]
    fail += [] if set(DEMO_CRITICAL) <= present else [f"missing demo-critical embedded nodes: {set(DEMO_CRITICAL) - present}"]
    fail += [] if sha_ok else ["extsrc:context-evals has no doc_sha (serve deep_warranted would be False)"]
    if fail:
        print("DEMO_SEED_FAIL:", fail); sys.exit(1)
    print("DEMO_SEED_OK")


if __name__ == "__main__":
    main()
