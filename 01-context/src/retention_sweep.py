"""9or: bounded historical-edge retention sweep over RELATES_TO.

Invalidate-don't-delete (mutate.apply_edge) keeps every superseded edge forever; deadedge_metrics.py
MEASURES that growth. This sweep is the MECHANISM for a retention POLICY: report the cold
(historical, invalid_at <= now) edge volume, and OPTIONALLY prune edges whose invalid_at predates a
cutoff.

  DEFAULT                  dry-run — measure only, delete NOTHING.
  --apply --before <ISO>   DELETE historical edges with invalid_at < <ISO>.
  --selftest               seed + prove the prune keeps current + in-window history.

POLICY NOTE: pruning trades bi-temporal replay BEYOND the window for bounded storage — the window is
a FOUNDER decision (audit/compliance vs cost), so prune is opt-in and never the default. Current
edges (invalid_at = SENTINEL 9999-12-31, i.e. invalid_at > now) are NEVER deleted.
"""
import os
import sys
from neo4j import GraphDatabase

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))
SENTINEL = "9999-12-31T00:00:00Z"


def measure(s, ns=None):
    """(current, historical) RELATES_TO counts. current = invalid_at > now (SENTINEL-stamped);
    historical = invalid_at <= now. ns=None => whole graph."""
    cur = s.run("MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at > datetime() "
                "AND ($ns IS NULL OR r.namespace=$ns) RETURN count(r) AS c", ns=ns).single()["c"]
    hist = s.run("MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at <= datetime() "
                 "AND ($ns IS NULL OR r.namespace=$ns) RETURN count(r) AS c", ns=ns).single()["c"]
    return cur, hist


def prune(s, before_iso, ns=None):
    """DELETE historical edges (invalid_at <= now) with invalid_at < before_iso. Current edges are
    NEVER touched — their invalid_at = SENTINEL > now is excluded by the `<= now` predicate."""
    return s.run("MATCH ()-[r:RELATES_TO]->() "
                 "WHERE r.invalid_at <= datetime() AND r.invalid_at < datetime($b) "
                 "AND ($ns IS NULL OR r.namespace=$ns) "
                 "DELETE r RETURN count(r) AS c", b=before_iso, ns=ns).single()["c"]


def _selftest():
    """Seed (in a throwaway namespace) 1 current + 2 historical edges (one pre-cutoff, one post),
    prune with a cutoff BETWEEN them, and prove only the pre-cutoff historical edge is deleted —
    current and in-window history survive. No embeddings; runs on live Neo4j."""
    NS = "retention_test"
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        s.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS)
        try:
            s.run("CREATE (a:Entity {key:'ret:a', namespace:$ns}) "
                  "CREATE (b:Entity {key:'ret:b', namespace:$ns}) "
                  "CREATE (a)-[:RELATES_TO {name:'X', namespace:$ns, valid_at:datetime('2019-01-01'), invalid_at:datetime($sent)}]->(b) "
                  "CREATE (a)-[:RELATES_TO {name:'X', namespace:$ns, valid_at:datetime('2019-01-01'), invalid_at:datetime('2020-01-01')}]->(b) "
                  "CREATE (a)-[:RELATES_TO {name:'X', namespace:$ns, valid_at:datetime('2025-01-01'), invalid_at:datetime('2026-06-01')}]->(b)",
                  ns=NS, sent=SENTINEL)
            cur, hist = measure(s, ns=NS)
            pruned = prune(s, "2023-01-01", ns=NS)        # cutoff between the 2020 and 2026 historical edges
            cur2, hist2 = measure(s, ns=NS)
        finally:                                          # RT-3: crash-safe cleanup (shared local DB)
            s.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS)
    print(f"[retention] seed current={cur} historical={hist} -> prune(<2023)={pruned} "
          f"-> after current={cur2} historical={hist2}")
    ok = (cur == 1 and hist == 2 and pruned == 1 and cur2 == 1 and hist2 == 1)
    if not ok:
        print("RETENTION_SELFTEST_FAIL", (cur, hist, pruned, cur2, hist2)); sys.exit(1)
    print("RETENTION_SELFTEST_OK")


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        _selftest(); return
    before = None
    if "--before" in argv:
        i = argv.index("--before")
        before = argv[i + 1] if i + 1 < len(argv) else None
    apply_prune = "--apply" in argv
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        cur, hist = measure(s)
        print(f"[retention] current={cur} historical={hist} "
              f"(historical = invalid_at <= now; never pruned by default)")
        if apply_prune:
            if not before:
                print("RETENTION_SWEEP_FAIL: --apply requires --before <ISO>"); sys.exit(1)
            n = prune(s, before)
            print(f"[retention] APPLIED: deleted {n} historical edges with invalid_at < {before}")
        else:
            print("[retention] DRY-RUN — deleted nothing. "
                  "Pass --apply --before <ISO> to prune (founder policy decision).")
    print("RETENTION_SWEEP_OK")


if __name__ == "__main__":
    main()
