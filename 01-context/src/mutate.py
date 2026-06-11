"""E1-mut (beads cb-dfv.4): parameterized MATCH mutation engine.

Reads schema/relations.yaml (the §10 5-axis S7 contract) and picks parameterized Cypher
per relation instead of hand-coding it per call site:
  resolve_entity — idempotent MERGE of a keyed entity (+ optional provenance episode)
  apply_edge     — add/remove a fact edge; arity:1+overflow:evict supersedes the incumbent,
                   additive (reject/coexist) just accumulates; verbs gate whether remove is legal
  mark_dirty     — content edit -> bump content_rev + set dirty=true (the G1-sweep trigger)

Generalizes etl.py's hand-written functional_edge/additive_edge into one rule-driven engine
that FIX-RACE (cb-dfv.5) and G1-sweep (cb-t0m.1) build on. ZERO LLM — pure neo4j driver.

Spec honored (ONTOLOGY_SCHEMA §10 / §7):
  - the evaluation clock `now` is an EXPLICIT argument, never ambient datetime(), so a temporal
    mutation is reproducible (same input + same now -> same graph). §10 calls ambient-clock a
    latent bug in the bi-temporal path; this engine fixes it at the source.
  - invalid_at/expired_at are ABSENT on a current edge (set only on supersede/remove), never
    placed as null inside a MERGE pattern (§7 Cypher gotcha).
"""
import sys
import yaml
from pathlib import Path
from neo4j import GraphDatabase

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
RULES = yaml.safe_load((Path(__file__).parent / "schema" / "relations.yaml").read_text())["relations"]


def resolve_entity(tx, label, key, now, ns, short="", long_="", ep=None):
    """resolve = idempotent MERGE of a keyed entity. content_rev starts at 0, dirty cleared.
    namespace is set ON CREATE only — a re-ingest under a DIFFERENT namespace is an isolation
    violation and raises (ownership never silently moves)."""
    rec = tx.run(
        f"MERGE (n:Entity:{label} {{key:$key}}) "
        "ON CREATE SET n.created_at=datetime($now), n.content_rev=0, n.namespace=$ns "
        "SET n.short_context=$short, n.long_context=$long, n.dirty=false "
        "RETURN n.namespace AS ns",
        key=key, now=now, ns=ns, short=short, long=long_).single()
    if rec["ns"] != ns:
        raise ValueError(f"namespace isolation: {key} is owned by '{rec['ns']}', "
                         f"refusing re-ingest under '{ns}'")
    if ep:
        tx.run("MATCH (n:Entity {key:$key}) "
               "MERGE (e:Episodic {uuid:$ep}) "
               "  ON CREATE SET e.created_at=datetime($now), e.valid_at=datetime($now), e.namespace=$ns "
               "MERGE (e)-[:MENTIONS]->(n)",
               key=key, ep=ep, now=now, ns=ns)


def apply_edge(tx, s_key, rel, o_key, now, ns, ep=None, op="add", lock=True):
    """Apply an edge per the relation's FULL 5-axis rule (arity / overflow_policy / verbs /
    temporal / contradiction). op in {add, remove}. ALL edge matches are namespace-scoped — a
    write in namespace A can never touch the same relation in namespace B (FIX-NS).

    Axis handling:
      verbs         — remove is rejected unless 'remove' in verbs.
      overflow:evict (arity:1)  — supersede the current incumbent (functional re-anchor).
      overflow:reject + arity:1 — a DIFFERENT current object is a collision -> RAISE (never
                                  silently add a 2nd current edge; "engine must not guess").
      overflow:reject/coexist/aggregate + arity:inf — additive (no overflow on unbounded arity).
      temporal      — recorded on the edge (r.temporal); supersede on a 'static' relation is a
                      transaction-time CORRECTION (r.supersede_kind), on bi-temporal it is a
                      validity-time change. Both clear 'current' via invalid_at so reads are right.
      contradiction:graph_invariant (collision_key:path) — cycle guard: refuse an add that would
                      close a directed cycle over current edges of this relation (DEPENDS_ON, SUPERSEDES).

    FIX-RACE (cb-dfv.5): any arity:1 path takes an exclusive subject-node write-lock first
    (pure write, no read-upgrade deadlock) so concurrent writers serialize -> exactly one current.
    """
    rule = RULES[rel]
    arity = rule["arity"]
    overflow = rule["overflow_policy"]
    temporal = rule["temporal"]
    resolution = rule.get("contradiction", {}).get("resolution")
    functional = arity == 1

    if op == "remove":
        if "remove" not in rule["verbs"]:
            raise ValueError(f"{rel}: verbs='{rule['verbs']}' forbids remove")
        tx.run("MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel, namespace:$ns}]->(o:Entity {key:$o}) "
               "WHERE r.invalid_at IS NULL "
               "SET r.invalid_at=datetime($now), r.expired_at=datetime($now)",
               s=s_key, rel=rel, o=o_key, now=now, ns=ns)
        return

    # op == add ----------------------------------------------------------------
    # cycle guard for graph_invariant relations (over CURRENT, same-namespace edges of this rel)
    if resolution == "graph_invariant":
        cyc = tx.run(
            "MATCH (o:Entity {key:$o}) "
            "OPTIONAL MATCH p=(o)-[:RELATES_TO*1..]->(s:Entity {key:$s}) "
            "WHERE all(r IN relationships(p) WHERE r.name=$rel AND r.namespace=$ns AND r.invalid_at IS NULL) "
            "RETURN count(p) > 0 AS cycle", o=o_key, s=s_key, rel=rel, ns=ns).single()
        if cyc and cyc["cycle"]:
            raise ValueError(f"{rel}: adding {s_key}->{o_key} would close a cycle (graph_invariant)")

    if functional and lock:                       # serialize arity:1 writers (FIX-RACE)
        tx.run("MATCH (s:Entity {key:$s}) SET s._wlock=$now", s=s_key, now=now)

    if overflow == "evict":                       # functional re-anchor: supersede incumbent (ns-scoped)
        tx.run("MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel, namespace:$ns}]->(prev:Entity) "
               "WHERE r.invalid_at IS NULL AND prev.key <> $o "
               "SET r.invalid_at=datetime($now), r.expired_at=datetime($now), "
               "    r.supersede_kind=CASE WHEN $temporal='static' THEN 'correction' ELSE 'validity' END",
               s=s_key, rel=rel, o=o_key, now=now, ns=ns, temporal=temporal)
    elif overflow == "reject" and functional:     # arity:1 + reject: collision -> REJECT
        clash = tx.run("MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel, namespace:$ns}]->(prev:Entity) "
                       "WHERE r.invalid_at IS NULL AND prev.key <> $o RETURN prev.key AS k LIMIT 1",
                       s=s_key, rel=rel, o=o_key, ns=ns).single()
        if clash:
            raise ValueError(f"{rel}: arity:1 overflow_policy:reject — refusing {o_key}; "
                             f"current is {clash['k']} (no silent supersede)")
    # else additive (reject/coexist/aggregate + arity:inf): just MERGE the edge below

    # On re-add of a HISTORICAL edge (retract-then-readd, or evict-away-then-readd the same object)
    # the MERGE matches the dead edge — RESURRECT it (clear end-fields, refresh valid_at). A still
    # -current edge is left untouched. Without this, a removed fact could never be reasserted.
    tx.run("MATCH (s:Entity {key:$s}),(o:Entity {key:$o}) "
           "MERGE (s)-[r:RELATES_TO {name:$rel, namespace:$ns}]->(o) "
           "ON CREATE SET r.valid_at=datetime($now), r.created_at=datetime($now), "
           "              r.episodes=$eps, r.temporal=$temporal "
           "ON MATCH  SET r.episodes=CASE WHEN $ep IS NULL OR $ep IN r.episodes "
           "                              THEN r.episodes ELSE r.episodes+$ep END, "
           "              r.valid_at=CASE WHEN r.invalid_at IS NULL THEN r.valid_at ELSE datetime($now) END, "
           "              r.invalid_at=null, r.expired_at=null",
           s=s_key, o=o_key, rel=rel, ns=ns, now=now, eps=[ep] if ep else [], ep=ep, temporal=temporal)


def apply_set_snapshot(tx, s_key, rel, desired, now, ns, ep=None):
    """set_snapshot reconciliation (e.g. OWNS): diff current vs desired set -> add missing,
    remove extra. The §10 set-valued mechanism (toAdd/toRemove)."""
    if not RULES[rel].get("set_snapshot"):
        raise ValueError(f"{rel}: not a set_snapshot relation")
    current = {r["k"] for r in tx.run(
        "MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel, namespace:$ns}]->(o) "
        "WHERE r.invalid_at IS NULL RETURN o.key AS k", s=s_key, rel=rel, ns=ns)}
    desired = set(desired)
    for o in sorted(desired - current):
        apply_edge(tx, s_key, rel, o, now, ns, ep, op="add")
    for o in sorted(current - desired):
        apply_edge(tx, s_key, rel, o, now, ns, op="remove")
    return {"added": sorted(desired - current), "removed": sorted(current - desired)}


def mark_dirty(tx, key, now):
    """dirty-flag = content changed -> bump content_rev + set dirty (the lazy re-embed trigger)."""
    tx.run("MATCH (n:Entity {key:$key}) "
           "SET n.content_rev=coalesce(n.content_rev,0)+1, n.dirty=true, "
           "    n.content_changed_at=datetime($now)",
           key=key, now=now)


# ── read helpers (assertions) ────────────────────────────────────────────────
def current_targets(tx, s_key, rel, ns=None):
    """ns=None -> any namespace (current behaviour); ns set -> scoped to that namespace."""
    return sorted(r["k"] for r in tx.run(
        "MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel}]->(o) "
        "WHERE r.invalid_at IS NULL AND ($ns IS NULL OR r.namespace=$ns) "
        "RETURN o.key AS k", s=s_key, rel=rel, ns=ns))


def edge_state(tx, s_key, rel, o_key, ns=None):
    rec = tx.run(
        "MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel}]->(o:Entity {key:$o}) "
        "WHERE ($ns IS NULL OR r.namespace=$ns) "
        "RETURN r.invalid_at IS NULL AS current", s=s_key, rel=rel, o=o_key, ns=ns).single()
    return None if rec is None else rec["current"]


def dirty_state(tx, key):
    rec = tx.run("MATCH (n:Entity {key:$key}) RETURN n.dirty AS d, n.content_rev AS rev",
                 key=key).single()
    return rec["d"], rec["rev"]


# ── demo / acceptance test (isolated namespace, self-cleaning) ───────────────
TNS = "mut_test"          # throwaway namespace; live data (16 nodes) untouched
T0, T1, T2 = "2026-06-04T00:00:00Z", "2026-06-04T01:00:00Z", "2026-06-04T02:00:00Z"


def _seed(tx):
    for k, lbl in [("test:iss:1", "Issue"), ("test:iss:2", "Issue"), ("test:iss:3", "Issue"),
                   ("test:ag:alice", "Agent"), ("test:ag:bob", "Agent")]:
        resolve_entity(tx, lbl, k, T0, TNS, short=k, long_=k, ep="test-ep-1")


def _cleanup(tx):
    tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=TNS)


def demo():
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(_cleanup)                       # idempotent start

            # 1) RESOLVE (MERGE) is idempotent — re-seeding must not duplicate
            count_ns = lambda tx: tx.run(
                "MATCH (n) WHERE n.namespace=$ns RETURN count(n) AS c", ns=TNS).single()["c"]
            s.execute_write(_seed)
            n_once = s.execute_read(count_ns)
            s.execute_write(_seed)                          # re-MERGE same keys
            n_twice = s.execute_read(count_ns)
            print(f"[resolve]   re-MERGE idempotent: {n_once} -> {n_twice} nodes "
                  f"(5 Entity + 1 Episodic; stable = no dup)")
            fail += [] if (n_once == n_twice == 6) else ["resolve not idempotent"]

            # 2) SUPERSEDE a functional edge: ASSIGNED_TO alice@T0 -> bob@T1
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "ASSIGNED_TO", "test:ag:alice", T0, TNS, "ep1"))
            before = s.execute_read(current_targets, "test:iss:1", "ASSIGNED_TO")
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "ASSIGNED_TO", "test:ag:bob", T1, TNS, "ep2"))
            after = s.execute_read(current_targets, "test:iss:1", "ASSIGNED_TO")
            alice_cur = s.execute_read(edge_state, "test:iss:1", "ASSIGNED_TO", "test:ag:alice")
            bob_cur = s.execute_read(edge_state, "test:iss:1", "ASSIGNED_TO", "test:ag:bob")
            print(f"[supersede] ASSIGNED_TO before={before} after={after} "
                  f"| alice current={alice_cur} bob current={bob_cur}")
            fail += [] if (after == ["test:ag:bob"] and alice_cur is False and bob_cur is True) \
                else ["functional supersede wrong: exactly-one-current violated"]

            # 3) ADDITIVE coexist: BLOCKS 1->2 and 1->3 both stay current (arity:inf, overflow:reject)
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "BLOCKS", "test:iss:2", T1, TNS, "ep2"))
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "BLOCKS", "test:iss:3", T1, TNS, "ep2"))
            blk = s.execute_read(current_targets, "test:iss:1", "BLOCKS")
            print(f"[additive]  BLOCKS current={blk} (expect both, coexist)")
            fail += [] if blk == ["test:iss:2", "test:iss:3"] else ["additive did not coexist"]

            # 4) REMOVE (verbs add+remove): retract BLOCKS 1->2; 1->3 survives
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "BLOCKS", "test:iss:2", T2, TNS, op="remove"))
            blk2 = s.execute_read(current_targets, "test:iss:1", "BLOCKS")
            print(f"[remove]    BLOCKS current={blk2} (expect only iss:3)")
            fail += [] if blk2 == ["test:iss:3"] else ["remove did not retract one edge"]

            # 4a) RESURRECT: re-adding a removed edge makes it current again (codex round-2 bug)
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "BLOCKS", "test:iss:2", T2, TNS, "ep3"))
            blk_res = s.execute_read(current_targets, "test:iss:1", "BLOCKS")
            print(f"[resurrect] re-add removed BLOCKS->iss:2 current={blk_res} (expect both again)")
            fail += [] if blk_res == ["test:iss:2", "test:iss:3"] else ["retract-then-readd stayed historical"]
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "BLOCKS", "test:iss:2", T2, TNS, op="remove"))  # restore state

            # 4b) REMOVE on add-only verb must be rejected by the rule (IMPLEMENTS = verbs:add)
            try:
                s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "IMPLEMENTS", "test:iss:2", T2, TNS, op="remove"))
                rej = False
            except ValueError:
                rej = True
            print(f"[verbs]     remove on add-only IMPLEMENTS rejected={rej}")
            fail += [] if rej else ["add-only verb allowed remove"]

            # 5) DIRTY-FLAG: content edit bumps content_rev + sets dirty
            d0, r0 = s.execute_read(dirty_state, "test:iss:1")
            s.execute_write(lambda tx: mark_dirty(tx, "test:iss:1", T2))
            d1, r1 = s.execute_read(dirty_state, "test:iss:1")
            print(f"[dirty]     before(dirty={d0},rev={r0}) -> after(dirty={d1},rev={r1})")
            fail += [] if (d1 is True and r1 == r0 + 1) else ["dirty-flag did not bump/set"]

            # 6) REJECT + arity:1 (PART_OF): a 2nd DIFFERENT parent is rejected, not silently added
            s.execute_write(lambda tx: resolve_entity(tx, "Project", "test:proj:a", T0, TNS, short="a", long_="a"))
            s.execute_write(lambda tx: resolve_entity(tx, "Project", "test:proj:b", T0, TNS, short="b", long_="b"))
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "PART_OF", "test:proj:a", T0, TNS, "ep1"))
            try:
                s.execute_write(lambda tx: apply_edge(tx, "test:iss:1", "PART_OF", "test:proj:b", T1, TNS, "ep2"))
                rej_arity = False
            except ValueError:
                rej_arity = True
            part = s.execute_read(current_targets, "test:iss:1", "PART_OF")
            print(f"[reject]    PART_OF 2nd parent rejected={rej_arity} | current={part} (arity:1 + overflow:reject)")
            fail += [] if (rej_arity and part == ["test:proj:a"]) else ["reject+arity:1 not enforced"]

            # 7) CYCLE GUARD (DEPENDS_ON = graph_invariant): T2->T3 ok, T3->T2 refused
            s.execute_write(lambda tx: apply_edge(tx, "test:iss:2", "DEPENDS_ON", "test:iss:3", T0, TNS, "ep1"))
            try:
                s.execute_write(lambda tx: apply_edge(tx, "test:iss:3", "DEPENDS_ON", "test:iss:2", T1, TNS, "ep2"))
                cyc_blocked = False
            except ValueError:
                cyc_blocked = True
            print(f"[cycle]     DEPENDS_ON back-edge refused={cyc_blocked} (graph_invariant)")
            fail += [] if cyc_blocked else ["cycle guard not enforced"]

            # 8) SET_SNAPSHOT (OWNS): reconcile {a,b} -> {b,c} = add c, remove a, keep b
            s.execute_write(lambda tx: resolve_entity(tx, "Project", "test:proj:c", T0, TNS, short="c", long_="c"))
            s.execute_write(lambda tx: apply_set_snapshot(tx, "test:ag:alice", "OWNS", ["test:proj:a", "test:proj:b"], T0, TNS, "ep1"))
            diff = s.execute_write(lambda tx: apply_set_snapshot(tx, "test:ag:alice", "OWNS", ["test:proj:b", "test:proj:c"], T1, TNS, "ep2"))
            owns = s.execute_read(current_targets, "test:ag:alice", "OWNS")
            print(f"[set_snap]  OWNS reconcile -> {diff} | current={owns}")
            fail += [] if (owns == ["test:proj:b", "test:proj:c"] and diff["added"] == ["test:proj:c"]
                           and diff["removed"] == ["test:proj:a"]) else ["set_snapshot reconcile wrong"]

            s.execute_write(_cleanup)

            # 9) CROSS-NAMESPACE ISOLATION (the codex bug): supersede in nsA must NOT touch nsB.
            #    One shared subject holds ASSIGNED_TO edges in two namespaces; re-anchor nsA only.
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.key STARTS WITH 'xns:' DETACH DELETE n"))
            for k in ["xns:subj", "xns:agA", "xns:agA2", "xns:agB"]:
                s.execute_write(lambda tx, k=k: resolve_entity(tx, "Agent", k, T0, "shared", short=k, long_=k))
            s.execute_write(lambda tx: apply_edge(tx, "xns:subj", "ASSIGNED_TO", "xns:agA", T0, "nsA", "epA"))
            s.execute_write(lambda tx: apply_edge(tx, "xns:subj", "ASSIGNED_TO", "xns:agB", T0, "nsB", "epB"))
            # re-anchor in nsA only (agA -> agA2). nsB edge (agB) must survive as current.
            s.execute_write(lambda tx: apply_edge(tx, "xns:subj", "ASSIGNED_TO", "xns:agA2", T1, "nsA", "epA2"))
            nsA = s.execute_read(current_targets, "xns:subj", "ASSIGNED_TO", "nsA")
            nsB = s.execute_read(current_targets, "xns:subj", "ASSIGNED_TO", "nsB")
            print(f"[isolation] after re-anchor in nsA: nsA current={nsA} | nsB current={nsB}")
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.key STARTS WITH 'xns:' DETACH DELETE n"))
            fail += [] if (nsA == ["xns:agA2"] and nsB == ["xns:agB"]) \
                else ["NAMESPACE ISOLATION BREACH: supersede in nsA leaked into nsB"]

    print("LLM calls in path: 0 (pure Cypher MERGE / MATCH-SET)")
    if fail:
        print("E1_MUT_FAIL:", fail); sys.exit(1)
    print("E1_MUT_OK")


if __name__ == "__main__":
    demo()
