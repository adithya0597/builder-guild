"""Single-current invariant sweep (builder-guild-llp): a READ-ONLY, graph-wide check that
fails LOUDLY if any arity:1 (functional) relation has more than ONE current edge per
(subject, rel, namespace).

WHY: R3 "single writer" is a CONVENTION, not a DB constraint. mutate.apply_edge serializes
arity:1 writes with a subject-node write-lock (mutate.py), but ANY writer that bypasses
apply_edge (a manual cypher session, a future second writer) can create a 2nd current edge
with no error — silently violating exactly-one-current. Neo4j has no uniqueness constraint
that can express "one CURRENT edge" (it's a predicate, not a key), so this sweep is the
enforceable backstop: run it in CI and as a periodic ops check; a nonzero exit = the
invariant is broken and a write path escaped the engine.

Modes:
  (default)     READ-ONLY graph-wide sweep -> SINGLE_CURRENT_OK or nonzero exit. Prod-safe.
  --self-test   inject a >1-current violation in an isolated namespace, assert the guard
                CATCHES it, clean up -> INVARIANT_SELFTEST_OK. Proves the guard actually
                fires (so the CI gate is not tautological on an always-clean seed). WRITES
                to an isolated namespace only, self-cleans.

Complements reconcile.py's per-read n_current>1 guard (which protects a single serve read)
with a whole-graph periodic assertion.
"""
from neo4j import GraphDatabase
from pathlib import Path
import sys
import yaml

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")  # local/CI dev cred (not a secret)

# arity:1 relations from the same source serve/reconcile use — the ones that MUST be single-current
FUNCTIONAL_RELS = sorted(
    rel for rel, spec in yaml.safe_load(
        (Path(__file__).parent.parent / "schema" / "relations.yaml").read_text()
    )["relations"].items() if spec.get("arity") == 1)

VIOLATION_Q = (
    # any endpoint label, not just :Entity — also catches a bypass writer using other labels;
    # the r.name IN $rels filter keeps it to the functional relations regardless of endpoints.
    "MATCH (s)-[r:RELATES_TO]->(o) "
    "WHERE r.name IN $rels AND r.invalid_at > datetime() "
    "WITH s.key AS subject, r.name AS rel, r.namespace AS ns, count(*) AS n, collect(o.key) AS objects "
    "WHERE n > 1 "
    "RETURN subject, rel, ns, n, objects ORDER BY n DESC")


def check(session):
    """Return the list of (subject, rel, namespace) groups holding >1 current edge."""
    return [dict(rec) for rec in session.run(VIOLATION_Q, rels=FUNCTIONAL_RELS)]


def self_test():
    """Prove the guard FIRES: inject a >1-current violation in an isolated namespace, assert
    it is caught, then clean up. WRITES to namespace '_invariant_selftest' only, self-cleans
    (even on failure, via finally). Keeps the CI invariant gate from being a no-op tautology."""
    ns, sent = "_invariant_selftest", "9999-12-31T00:00:00Z"
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            try:
                s.run("CREATE (x:Entity {key:'_st:x', namespace:$ns}) "
                      "CREATE (a:Entity {key:'_st:a', namespace:$ns}) "
                      "CREATE (b:Entity {key:'_st:b', namespace:$ns}) "
                      "CREATE (x)-[:RELATES_TO {name:'ASSIGNED_TO', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(a) "
                      "CREATE (x)-[:RELATES_TO {name:'ASSIGNED_TO', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(b)",
                      ns=ns, s=sent)
                caught = [v for v in s.execute_read(check) if v["ns"] == ns]
            finally:
                s.run("MATCH (n {namespace:$ns}) DETACH DELETE n", ns=ns)
            after = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    assert caught, "SELF-TEST FAILED: guard did not catch an injected >1-current violation"
    assert before == after, f"SELF-TEST cleanup leak: node count {before} -> {after}"
    print("INVARIANT_SELFTEST_OK")


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            violations = s.execute_read(check)
    print(f"functional (arity:1) relations checked: {FUNCTIONAL_RELS}")
    if violations:
        print(f"INVARIANT VIOLATED — {len(violations)} (subject,rel,namespace) with >1 current edge "
              f"(a writer bypassed mutate.apply_edge):")
        for v in violations:
            print(f"  {v['subject']} -[{v['rel']} @ {v['ns']}]-> {v['objects']}  (current count = {v['n']})")
        sys.exit(1)
    print("SINGLE_CURRENT_OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
