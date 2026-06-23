"""Migration/invariant guard runner (builder-guild-sjd): run a .cypher guard file and EXIT NONZERO if
any statement returns rows. A guard query is written to return rows ONLY on violation (empty = pass),
so "returns a row" == "the invariant is broken".

WHY: a bare `RETURN count(r) AS must_be_zero` cannot fail a migration — it returns a number and the
process exits 0 regardless; and apply_cypher.py (the schema-DDL applier) deliberately discards results.
So the 07 sentinel guard shipped as a no-op. This runner makes guard queries actually enforce: rows ->
nonzero exit. Use for 07_sentinel_migration.cypher and any future rows-on-violation guard.

Usage:
    python tools/run_guard.py 01-context/schema/07_sentinel_migration.cypher
    python tools/run_guard.py --self-test     # prove the runner fails on an injected violation

Reuses apply_cypher.statements() for the comment-strip/`;`-split (same house splitter).
"""
import sys
from neo4j import GraphDatabase
from apply_cypher import statements

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")  # local/CI dev cred (not a secret)


def run_guard(session, path):
    """Run every statement in `path`; return [(stmt_index, statement, rows)] for statements that
    returned rows. Write statements (SET/CREATE with no RETURN) return nothing; only a VIOLATED guard
    (rows-on-violation) returns rows."""
    offending = []
    for i, st in enumerate(statements(open(path).read())):
        rows = list(session.run(st))
        if rows:
            offending.append((i, st, rows))
    return offending


def self_test():
    """Prove the runner FAILS on a violation: inject one NULL-invalid_at edge (the exact thing the 07
    guard forbids) in an isolated namespace, run the guard predicate, assert it returns rows, clean up
    (finally). WRITES to '_guard_selftest' only; the handwritten edge is an intentional adversarial
    fixture (tools/ is not on the write-gateway scan path)."""
    ns = "_guard_selftest"
    guard = ("MATCH (s {namespace:$ns})-[r:RELATES_TO]->(o) WHERE r.invalid_at IS NULL RETURN r LIMIT 5")
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            try:
                s.run("CREATE (a:Entity {key:'_g:a', namespace:$ns}) "
                      "CREATE (b:Entity {key:'_g:b', namespace:$ns}) "
                      # invalid_at deliberately ABSENT (NULL) — the violation the guard must catch
                      "CREATE (a)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime()}]->(b)",
                      ns=ns)
                caught = list(s.run(guard, ns=ns))
            finally:
                s.run("MATCH (n {namespace:$ns}) DETACH DELETE n", ns=ns)
            after = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    assert caught, "SELF-TEST FAILED: guard did not return rows for a NULL invalid_at edge"
    assert before == after, f"SELF-TEST cleanup leak: node count {before} -> {after}"
    print("GUARD_SELFTEST_OK")


def main(paths):
    if not paths:
        sys.exit("usage: run_guard.py <guard.cypher> [more.cypher ...]  (or --self-test)")
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            total = 0
            for p in paths:
                for idx, st, rows in run_guard(s, p):
                    total += len(rows)
                    print(f"GUARD FAILED [{p} stmt #{idx}]: {len(rows)} offending row(s)")
                    for r in rows[:5]:
                        print(f"    {dict(r)}")
            if total:
                sys.exit(1)
    print("GUARD_OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main([a for a in sys.argv[1:] if not a.startswith("--")])
