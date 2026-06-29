"""Cycle invariant sweep (builder-guild-dzm): a READ-ONLY, graph-wide check that fails LOUDLY if any
graph_invariant relation has a CURRENT directed cycle (a cycle of same-name, same-namespace current edges).

WHY: apply_edge guards each ADD against closing a cycle (mutate.py), but that guard is a read-then-write
inside ONE transaction — two concurrent transactions can each add one leg of a would-be cycle, each pass
its guard against a snapshot that lacks the other's edge, and both commit, leaving a CURRENT cycle with no
error (a TOCTOU). The arity:1 subject write-lock does NOT cover these rels (DEPENDS_ON / SUPERSEDES are
arity:inf), and a cycle spans multiple subjects, so no single-node lock can serialize it. This sweep is the
whole-graph backstop: run it in CI and as a periodic ops check; a nonzero exit = a current cycle of length
<= MAX_CYCLE_LEN exists. The depth bound is a cost tradeoff — the online apply_edge guard is UNBOUNDED;
this bounded periodic sweep catches the realistic short cycles a concurrent-write TOCTOU produces.

Scope: CURRENT edges of the graph_invariant relations ONLY — derived from relations.yaml
(contradiction.resolution == 'graph_invariant'): DEPENDS_ON, SUPERSEDES. BLOCKS is resolution:structural
(NOT cycle-guarded) and is deliberately excluded.

Modes:
  (default)     READ-ONLY graph-wide sweep -> CYCLE_CHECK_OK or nonzero exit. Prod-safe.
  --self-test   inject a 2-cycle AND a 3-cycle in an isolated namespace, assert the sweep CATCHES both,
                clean up -> CYCLE_SELFTEST_OK. Proves the sweep fires (so the CI gate is not tautological).

Sibling of invariant_check.py (the >1-current backstop). Together they are the "continuous invariant
detection" half of the application-enforced write gateway (crk) — NOT DB-enforced.
"""
import os
from neo4j import GraphDatabase
from pathlib import Path
import sys
import yaml

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))  # local/CI dev cred (not a secret)

# graph_invariant (acyclic) relations from the same schema the engine reads — the ones whose CURRENT
# edge set must stay a DAG (DEPENDS_ON, SUPERSEDES). Derived, so adding a graph_invariant rel auto-covers it.
GRAPH_INVARIANT_RELS = sorted(
    rel for rel, spec in yaml.safe_load(
        (Path(__file__).parent.parent / "schema" / "relations.yaml").read_text()
    )["relations"].items()
    if spec.get("contradiction", {}).get("resolution") == "graph_invariant")

# A current directed cycle whose edges are all the SAME graph_invariant relation + SAME namespace
# (matching apply_edge's per-rel, per-namespace cycle guard). Bounded depth keeps the backstop cheap;
# the online apply_edge guard is unbounded, so this sweep trades tail-coverage (cycles > MAX_CYCLE_LEN) for cost.
MAX_CYCLE_LEN = 12
VIOLATION_Q = (
    f"MATCH p=(n)-[:RELATES_TO*1..{MAX_CYCLE_LEN}]->(n) "
    "WHERE relationships(p)[0].name IN $rels "
    "  AND all(r IN relationships(p) WHERE r.invalid_at > datetime() "
    "          AND r.name = relationships(p)[0].name "
    "          AND r.namespace = relationships(p)[0].namespace) "
    "RETURN DISTINCT relationships(p)[0].name AS rel, relationships(p)[0].namespace AS ns, "
    "       [x IN nodes(p) | x.key] AS cycle "
    "ORDER BY rel, ns LIMIT 25")


def check(session):
    """Return the list of current cycles over graph_invariant relations."""
    return [dict(rec) for rec in session.run(VIOLATION_Q, rels=GRAPH_INVARIANT_RELS)]


def self_test():
    """Prove the sweep FIRES: inject a 2-cycle and a 3-cycle of CURRENT DEPENDS_ON edges in an isolated
    namespace, assert BOTH are caught, then clean up (finally, even on failure). WRITES to namespace
    '_cycle_selftest' only. These handwritten current-edge writes are an INTENTIONAL adversarial bypass of
    apply_edge (this file is allowlisted in tools/check_write_gateway.py for exactly that reason)."""
    ns, sent = "_cycle_selftest", "9999-12-31T00:00:00Z"
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            try:
                s.run(
                    "CREATE (a:Entity {key:'_cy:a', namespace:$ns}) "
                    "CREATE (b:Entity {key:'_cy:b', namespace:$ns}) "
                    "CREATE (c:Entity {key:'_cy:c', namespace:$ns}) "
                    "CREATE (d:Entity {key:'_cy:d', namespace:$ns}) "
                    "CREATE (e:Entity {key:'_cy:e', namespace:$ns}) "
                    # 2-cycle: a -> b -> a
                    "CREATE (a)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(b) "
                    "CREATE (b)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(a) "
                    # 3-cycle: c -> d -> e -> c
                    "CREATE (c)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(d) "
                    "CREATE (d)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(e) "
                    "CREATE (e)-[:RELATES_TO {name:'DEPENDS_ON', namespace:$ns, valid_at:datetime(), invalid_at:datetime($s)}]->(c)",
                    ns=ns, s=sent)
                caught = [v for v in s.execute_read(check) if v["ns"] == ns]
                nodes_in_cycles = {k for v in caught for k in v["cycle"]}
            finally:
                s.run("MATCH (n {namespace:$ns}) DETACH DELETE n", ns=ns)
            after = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    assert caught, "SELF-TEST FAILED: sweep did not catch an injected current cycle"
    assert {"_cy:a", "_cy:b"} <= nodes_in_cycles, f"2-cycle not caught: {sorted(nodes_in_cycles)}"
    assert {"_cy:c", "_cy:d", "_cy:e"} <= nodes_in_cycles, f"3-cycle not caught: {sorted(nodes_in_cycles)}"
    assert before == after, f"SELF-TEST cleanup leak: node count {before} -> {after}"
    print("CYCLE_SELFTEST_OK")


def main():
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            violations = s.execute_read(check)
    print(f"graph_invariant (acyclic) relations checked: {GRAPH_INVARIANT_RELS}")
    if violations:
        print(f"CYCLE INVARIANT VIOLATED — {len(violations)} current cycle(s) "
              f"(a concurrent write closed a cycle past the per-add guard):")
        for v in violations:
            print(f"  [{v['rel']} @ {v['ns']}] cycle: {' -> '.join(v['cycle'])}")
        sys.exit(1)
    print("CYCLE_CHECK_OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
