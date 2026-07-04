"""builder-guild-b9y: namespace-scoped rollback + orphaned :Candidate sweep (sibling of staging.py).

WHY: an operator needs to wipe-and-re-ingest a namespace cleanly during dev (etl_history.py --real
against a live external source is the motivating case) without reaching for the etl.py:186 shape —
a whole-graph wipe with no namespace predicate at all, safe only because that demo assumes a
throwaway graph with nothing else in it. This module is namespace-AGNOSTIC: both subcommands take
any explicit namespace string that survives `_require_ns`; nothing here hardcodes 'history', and
this module never imports or runs etl.py.

Safety clauses (acceptance a-f, plus hardening clause g), all provable by --selftest in its own
throwaway namespace(s):
  (a) explicit namespace, no default — every destructive op requires an explicit ns arg.
  (b) refusals — 'shared', '', '*'/wildcard are all rejected by _require_ns.
  (c) dry-run default — --apply is required to actually delete anything.
  (d) no unscoped wipe — self-scan asserts this file never contains the etl.py:186 shape.
  (e) orphan sweep — a :Candidate whose endpoint never resolved to an :Entity.
  (f) gateway green — production deletes are raw scoped Cypher, not a mutate write fn, so
      tools/check_write_gateway.py's scan surface is untouched by this module.
  (g) preview EQUALS apply, BY CONSTRUCTION, over the TYPE-AGNOSTIC delete-set — --apply removes every
      node carrying ns and every relationship of ANY type that is stamped ns OR incident to an ns node
      (HAS_CHUNK / IN_COMMUNITY / MENTIONS / RELATES_TO alike — all carry namespace stamps). The dry-run
      counts that exact set (_DELSET) and prints a per-TYPE breakdown so an operator sees the full
      blast-radius before --apply — a chunk-heavy namespace can carry far more HAS_CHUNK than RELATES_TO.
      The current/historical split is reported for RELATES_TO only (the sole type carrying invalid_at).
      --selftest proves, per topology — including a non-RELATES_TO incident rel AND a non-RELATES_TO edge
      stamped ns with both endpoints elsewhere — that the previewed total equals what --apply removes.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from neo4j import GraphDatabase

import mutate            # selftest fixtures: resolve healthy endpoints (the legit caller, never a handwritten :Entity CREATE)
import staging            # selftest fixtures: stage() candidates (the legit caller, never a handwritten :Candidate CREATE)

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))  # local/CI dev cred (not a secret)

_NS_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# self-scan target (clause d): the etl.py:186 unscoped-wipe shape. Written with \s*/\b so this
# line never matches its own detector; any prose reference to the disaster above stays non-literal
# too — cite file:line only, never paste the real parens/spacing of the shape itself.
_UNSCOPED = re.compile(r"MATCH\s*\(\s*n\s*\)\s*DETACH\s+DELETE\s+n\b")


def _require_ns(ns):
    if not ns or ns == "shared" or not _NS_RE.fullmatch(ns):
        raise ValueError(f"rollback: refusing namespace {ns!r} (empty/'shared'/wildcard/non-identifier)")


def _clean(session, ns):
    # the exact _clean(ns) idiom already used across ~10 selftests (staging.py:207, etl_history.py,
    # mutate.py, embed.py, sweep.py, cycle_check.py, invariant_check.py). No guard here on purpose —
    # this is the raw primitive; rollback_namespace (below) is the guarded public entrypoint that
    # wraps it, and the selftest also calls this directly for its own hermetic housekeeping.
    session.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=ns))


# THE relationship delete-set --apply removes, defined ONCE (clause g), TYPE-AGNOSTIC. --apply removes
# every node carrying $ns and every relationship of ANY type that is stamped $ns OR incident to a
# $ns-owned node. _DELSET is that exact set; the dry-run counts it and the post-apply re-count asserts
# it is 0, so the preview cannot understate what --apply destroys. The stamp disjunct is NOT gated to
# RELATES_TO — HAS_CHUNK/IN_COMMUNITY carry namespace stamps too, so a type gate would leave a
# non-RELATES_TO edge stamped $ns with both endpoints out-of-ns neither counted nor deleted. Both
# --apply's explicit rel-delete and the preview use this one predicate, so they cannot drift:
#   r.namespace=$ns                    — the edge's OWN stamp, ANY type (a stamped edge can carry $ns
#                                        while NEITHER endpoint node does; the explicit rel-delete
#                                        catches it — a node DETACH, seeing no in-ns endpoint, cannot).
#   startNode/endNode(r).namespace=$ns — incident to an ns node: the set _clean's DETACH takes with it.
_DELSET = "r.namespace=$ns OR startNode(r).namespace=$ns OR endNode(r).namespace=$ns"


def _delset_rels(tx, ns):
    """Per-type counts of _DELSET (the relationship delete-set --apply removes, ALL types). Returns
    (by_type, cur): by_type maps rel-type -> count(DISTINCT r); cur = RELATES_TO rows still current.
    Only RELATES_TO carries invalid_at, so the current/historical split is RELATES_TO-only — hence the
    type gate on the cur sub-count, NOT on the total. Directed ()-[r]->() binds each rel once."""
    rows = tx.run(
        f"MATCH ()-[r]->() WHERE {_DELSET} RETURN type(r) AS t, count(DISTINCT r) AS c, "
        "sum(CASE WHEN type(r)='RELATES_TO' AND r.invalid_at > datetime() THEN 1 ELSE 0 END) AS cur",
        ns=ns)
    by_type, cur = {}, 0
    for row in rows:
        by_type[row["t"]], cur = row["c"], cur + row["cur"]
    return by_type, cur


def _rels_str(by_type):
    return " ".join(f"{t}={c}" for t, c in sorted(by_type.items())) if by_type else "none"


def rollback_namespace(session, ns, apply=False):
    """Namespace-scoped rollback. Reports, then (under --apply) removes, THE delete-set: all nodes
    carrying `ns` plus every relationship in _DELSET — every rel of ANY type stamped ns OR incident to
    an ns node (type-agnostic: HAS_CHUNK/IN_COMMUNITY carry stamps too). Dry-run and apply derive from
    the SAME _DELSET definition, so the preview cannot understate what apply destroys. The dry-run
    prints a per-TYPE breakdown (an operator sees the HAS_CHUNK/IN_COMMUNITY/... blast-radius, which
    on a chunk-heavy namespace dwarfs RELATES_TO); the current/historical split is RELATES_TO-only
    (the sole type carrying invalid_at). --apply deletes every _DELSET rel of any type (the explicit
    rel-delete, catching stamped edges whose endpoints are out-of-ns), then DETACH-deletes the ns nodes,
    then re-counts _DELSET. Returns (nodes, edges_current, rels_total) — all three 0 after a successful
    --apply."""
    _require_ns(ns)

    def _counts(tx):
        nodes = tx.run("MATCH (n) WHERE n.namespace=$ns RETURN count(n) AS c", ns=ns).single()["c"]
        by_type, cur = _delset_rels(tx, ns)
        return nodes, cur, sum(by_type.values()), by_type

    nodes, cur, total, by_type = session.execute_read(_counts)
    hist = by_type.get("RELATES_TO", 0) - cur
    if not apply:
        print(f"rollback-namespace {ns}: nodes={nodes} rels_total={total} [{_rels_str(by_type)}] "
              f"(RELATES_TO current={cur} historical={hist}) "
              f"— dry-run, nothing deleted — pass --apply")
        return nodes, cur, total
    print(f"rollback-namespace {ns}: nodes={nodes} rels_total={total} [{_rels_str(by_type)}] "
          f"(RELATES_TO current={cur} historical={hist})")
    # --apply, two mechanisms whose union == _DELSET (what the preview counted): (1) the explicit
    # rel-delete removes every relationship of ANY type matching _DELSET — including a non-RELATES_TO
    # edge stamped ns whose BOTH endpoints are out-of-ns, which a node DETACH (seeing no in-ns endpoint)
    # cannot reach; (2) _clean's DETACH DELETE removes the ns nodes — now rel-free, since every incident
    # rel matched _DELSET's endpoint terms and is already gone, so DETACH is defensive on edges here.
    session.execute_write(lambda tx: tx.run(
        f"MATCH ()-[r]->() WHERE {_DELSET} DELETE r", ns=ns))
    _clean(session, ns)
    nodes2, cur2, total2, by_type2 = session.execute_read(_counts)
    print(f"rollback-namespace {ns}: applied — nodes={nodes2} rels_total={total2} "
          f"[{_rels_str(by_type2)}] (RELATES_TO current={cur2} "
          f"historical={by_type2.get('RELATES_TO', 0) - cur2})")
    return nodes2, cur2, total2


def sweep_candidates(session, ns, apply=False):
    """Orphan = a :Candidate whose endpoint would fail staging.promote()'s own endpoint-ownership
    check (staging.py:156-165): resolved to an :Entity owned by this namespace or 'shared'. Reuses
    that definition rather than inventing a fresh one. Dry-run lists the id set; --apply deletes
    EXACTLY that materialized set (not a re-run query), so the reported and deleted sets are
    provably identical within one invocation."""
    _require_ns(ns)

    def _orphans(tx):
        return [r["cand_id"] for r in tx.run(
            "MATCH (c:Candidate {namespace:$ns}) "
            "OPTIONAL MATCH (s:Entity {key:c.s_key}) WHERE s.namespace IN [$ns,'shared'] "
            "OPTIONAL MATCH (o:Entity {key:c.o_key}) WHERE o.namespace IN [$ns,'shared'] "
            "WITH c, s, o WHERE s IS NULL OR o IS NULL "
            "RETURN c.cand_id AS cand_id", ns=ns)]

    ids = session.execute_read(_orphans)
    print(f"sweep-candidates {ns}: orphans={ids}" +
          ("" if apply else " (dry-run, nothing deleted — pass --apply)"))
    if not apply:
        return ids
    # PIR P3: namespace predicate belt-and-suspenders with the id list — a delete must never be
    # able to reach outside the namespace the operator named, even under a hypothetical cand_id
    # collision or a future non-sha1 id scheme.
    session.execute_write(lambda tx: tx.run(
        "MATCH (c:Candidate {namespace:$ns}) WHERE c.cand_id IN $ids DETACH DELETE c", ns=ns, ids=ids))
    print(f"sweep-candidates {ns}: deleted {ids}")
    return ids


# ── --selftest: hermetic fixtures, own throwaway namespace, self-cleaning ────
SNS = "_rollback_selftest"
SNS_EXT = "_rollback_selftest_ext"       # a SECOND namespace — the "elsewhere" ns for the (g) topologies
SNS_OTHER = "_rollback_selftest_other"   # a THIRD namespace, used only by the (e) cross-ns id-collision case
S0 = "2026-07-03T00:00:00Z"
H0 = "2020-01-01T00:00:00Z"              # (g) historical case: add at H0, supersede at H1>H0 — both safely
H1 = "2020-01-01T01:00:00Z"              # in the past so the superseded row reads historical at ANY wall-clock


def _count_ns(tx, ns):
    return tx.run("MATCH (n) WHERE n.namespace=$ns RETURN count(n) AS c", ns=ns).single()["c"]


def _all_ns_rels(tx):
    # INDEPENDENT "what did --apply remove" gauge for the (g) cases: every relationship of ANY type
    # touching either test namespace by endpoint OR stamp (any type) — a strict SUPERSET of SNS's
    # delete-set, over ALL rel types, so a before/after diff around --apply measures removals WITHOUT
    # reusing _DELSET (that is what makes preview==removed a real check, not a tautology). ns-scoped,
    # so concurrent writes in unrelated namespaces (history/engineering/...) can't perturb the diff.
    return tx.run(
        "MATCH ()-[r]->() WHERE startNode(r).namespace IN [$a,$b] OR endNode(r).namespace IN [$a,$b] "
        "OR r.namespace IN [$a,$b] "
        "RETURN count(DISTINCT r) AS c", a=SNS, b=SNS_EXT).single()["c"]


def _b_in_ns(tx):            # (g/a) edge stamped SNS on two SNS endpoints — the ordinary case
    mutate.resolve_entity(tx, "Issue", "issue:G-A-S", S0, SNS, short="a", long_="a")
    mutate.resolve_entity(tx, "Agent", "agent:G-A-O", S0, SNS, short="a", long_="a")
    mutate.apply_edge(tx, "issue:G-A-S", "ASSIGNED_TO", "agent:G-A-O", S0, SNS)


def _b_stamp_elsewhere(tx):  # (g/b) edge stamped SNS but BOTH endpoints in SNS_EXT (stamp != endpoints)
    mutate.resolve_entity(tx, "Agent", "agent:G-B-S", S0, SNS_EXT, short="b", long_="b")
    mutate.resolve_entity(tx, "Agent", "agent:G-B-O", S0, SNS_EXT, short="b", long_="b")
    mutate.apply_edge(tx, "agent:G-B-S", "ASSIGNED_TO", "agent:G-B-O", S0, SNS)


def _b_collateral(tx):       # (g/c) edge stamped ELSEWHERE (SNS_EXT) but BOTH endpoints in SNS — the
    mutate.resolve_entity(tx, "Issue", "issue:G-C-S", S0, SNS, short="c", long_="c")   # collateral case a
    mutate.resolve_entity(tx, "Agent", "agent:G-C-O", S0, SNS, short="c", long_="c")   # stamp-only preview missed
    mutate.apply_edge(tx, "issue:G-C-S", "ASSIGNED_TO", "agent:G-C-O", S0, SNS_EXT)


def _b_historical(tx):       # (g/a-hist) one current + one superseded (historical) edge, both SNS
    mutate.resolve_entity(tx, "Issue", "issue:G-H-S", H0, SNS, short="h", long_="h")
    mutate.resolve_entity(tx, "Agent", "agent:G-H-1", H0, SNS, short="h", long_="h")
    mutate.resolve_entity(tx, "Agent", "agent:G-H-2", H0, SNS, short="h", long_="h")
    mutate.apply_edge(tx, "issue:G-H-S", "ASSIGNED_TO", "agent:G-H-1", H0, SNS)   # current...
    mutate.apply_edge(tx, "issue:G-H-S", "ASSIGNED_TO", "agent:G-H-2", H1, SNS)   # ...then evicts G-H-1 -> historical


def _b_nonrel(tx):       # (g/n) a NON-RELATES_TO rel (:MENTIONS) between two SNS nodes — removed by
    mutate.resolve_entity(tx, "Issue", "issue:G-N-S", S0, SNS, short="n", long_="n")   # _clean's DETACH but
    mutate.resolve_entity(tx, "Agent", "agent:G-N-O", S0, SNS, short="n", long_="n")   # missed by a RELATES_TO-only preview
    tx.run("MATCH (a:Entity {key:$s}),(b:Entity {key:$o}) MERGE (a)-[:MENTIONS]->(b)",  # raw MERGE: not apply_edge (which only makes RELATES_TO)
           s="issue:G-N-S", o="agent:G-N-O")


def _b_stamp_nonrel(tx):  # (g/s) a NON-RELATES_TO edge (:HAS_CHUNK) stamped SNS but BOTH endpoints in
    mutate.resolve_entity(tx, "Agent", "agent:G-S-1", S0, SNS_EXT, short="s", long_="s")   # SNS_EXT — the type-agnostic
    mutate.resolve_entity(tx, "Agent", "agent:G-S-2", S0, SNS_EXT, short="s", long_="s")   # stamp case: preview+apply must
    tx.run("MATCH (a:Entity {key:$s}),(b:Entity {key:$o}) MERGE (a)-[r:HAS_CHUNK]->(b) SET r.namespace=$ns",  # count+delete by the ns STAMP, not endpoints
           s="agent:G-S-1", o="agent:G-S-2", ns=SNS)


def _topo_case(s, label, build, expect_total, expect_cur, ext_survivors):
    """Build ONE (g) topology in a freshly-cleaned SNS/SNS_EXT, then PROVE the dry-run's rel count
    equals what --apply physically removes (independent before/after via _all_ns_rels, over ALL rel
    types) and that the delete-set is empty afterward. Returns [] on pass, else a one-item failure list."""
    _clean(s, SNS)
    _clean(s, SNS_EXT)
    s.execute_write(build)
    nodes_dry, cur_dry, tot_dry = rollback_namespace(s, SNS, apply=False)
    rels_before = s.execute_read(_all_ns_rels)
    nodes_before = s.execute_read(lambda tx: _count_ns(tx, SNS))
    ext_before = s.execute_read(lambda tx: _count_ns(tx, SNS_EXT))
    rollback_namespace(s, SNS, apply=True)
    rels_after = s.execute_read(_all_ns_rels)
    nodes_after = s.execute_read(lambda tx: _count_ns(tx, SNS))
    ext_after = s.execute_read(lambda tx: _count_ns(tx, SNS_EXT))
    delset_after = s.execute_read(lambda tx: sum(_delset_rels(tx, SNS)[0].values()))
    rels_removed, nodes_removed = rels_before - rels_after, nodes_before - nodes_after
    ok = (tot_dry == expect_total == rels_removed and cur_dry == expect_cur
          and nodes_dry == nodes_removed and delset_after == 0 and nodes_after == 0
          and ext_before == ext_after == ext_survivors)
    print(f"[g/{label}] preview_rels={tot_dry} == apply_removed={rels_removed} "
          f"(RELATES_TO current={cur_dry}); delset_after={delset_after} "
          f"nodes_after={nodes_after} ext_survivors={ext_after}/{ext_survivors} "
          f"{'OK' if ok else 'FAIL'}")
    return [] if ok else [("clause g/" + label, dict(
        tot_dry=tot_dry, cur_dry=cur_dry, expect_total=expect_total, expect_cur=expect_cur,
        rels_removed=rels_removed, nodes_dry=nodes_dry, nodes_removed=nodes_removed,
        delset_after=delset_after, nodes_after=nodes_after,
        ext_before=ext_before, ext_after=ext_after, ext_survivors=ext_survivors))]


def _selftest():
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            try:
                _clean(s, SNS)
                _clean(s, SNS_EXT)
                _clean(s, SNS_OTHER)

                # (a) EXPLICIT NAMESPACE, NO DEFAULT — direct calls with a missing namespace raise
                # before any Cypher runs; count is unchanged (whatever it was).
                before_a = s.execute_read(lambda tx: _count_ns(tx, SNS))
                try:
                    sweep_candidates(s, None)
                    a1 = False
                except ValueError:
                    a1 = True
                try:
                    rollback_namespace(s, "")
                    a2 = False
                except ValueError:
                    a2 = True
                after_a = s.execute_read(lambda tx: _count_ns(tx, SNS))
                fail += [] if (a1 and a2 and before_a == after_a) else \
                    [("clause a: missing-namespace call not refused cleanly", a1, a2, before_a, after_a)]

                # (b) REFUSALS — 'shared', '', '*' each raise via _require_ns; nothing runs before
                # the raise so there is nothing to re-count against.
                refused = {bad: False for bad in ("shared", "", "*")}
                for bad in refused:
                    try:
                        _require_ns(bad)
                    except ValueError:
                        refused[bad] = True
                after_b = s.execute_read(lambda tx: _count_ns(tx, SNS))
                fail += [] if (all(refused.values()) and after_a == after_b) else \
                    [("clause b: a refusal namespace was not rejected", refused, after_a, after_b)]

                # (c) DRY-RUN DEFAULT then --apply lands at (0, 0) — seed a real node pair + a
                # current edge so the edge count is non-vacuous (not just "zero because none existed").
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Issue", "issue:RB-1", S0, SNS, short="RB-1", long_="RB-1"))
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", "agent:RB-1", S0, SNS, short="RB-1", long_="RB-1"))
                s.execute_write(lambda tx: mutate.apply_edge(tx, "issue:RB-1", "ASSIGNED_TO", "agent:RB-1", S0, SNS))
                nodes_dry, cur_dry, tot_dry = rollback_namespace(s, SNS, apply=False)
                unchanged = s.execute_read(lambda tx: _count_ns(tx, SNS))
                fail += [] if (nodes_dry == 2 and cur_dry == 1 and tot_dry == 1 and unchanged == nodes_dry) else \
                    [("clause c: dry-run counts wrong or altered the graph", nodes_dry, cur_dry, tot_dry, unchanged)]
                nodes_ap, cur_ap, tot_ap = rollback_namespace(s, SNS, apply=True)
                fail += [] if (nodes_ap == 0 and cur_ap == 0 and tot_ap == 0) else \
                    [("clause c: --apply did not land at all-zero (stricter total-scope check)",
                      nodes_ap, cur_ap, tot_ap)]

                # (g) PREVIEW == APPLY, BY CONSTRUCTION, over the TYPE-AGNOSTIC delete-set. For every
                # topology, the dry-run's reported rel count EXACTLY equals what --apply physically
                # removes (measured independently by _all_ns_rels, over ALL types), and the delete-set
                # is empty afterward. s-stamp-nonrel is the type-agnostic stamp case: a :HAS_CHUNK
                # stamped ns with BOTH endpoints elsewhere — the OLD type-gated stamp disjunct counted
                # AND deleted it as 0; now the explicit rel-delete removes it and its out-of-ns endpoint
                # NODES survive (ext_survivors=2). n-non-relates: a :MENTIONS incident to an ns node
                # (DETACH removes it; a RELATES_TO-only preview missed it). c-collateral is round-3;
                # a-historical keeps round-2 (total=2 cur=1); b-stamp-elsewhere keeps round-1.
                fail += _topo_case(s, "a-in-ns",          _b_in_ns,           1, 1, 0)
                fail += _topo_case(s, "b-stamp-elsewhere", _b_stamp_elsewhere, 1, 1, 2)
                fail += _topo_case(s, "c-collateral",      _b_collateral,      1, 1, 0)
                fail += _topo_case(s, "a-historical",      _b_historical,      2, 1, 0)
                fail += _topo_case(s, "n-non-relates",     _b_nonrel,          1, 0, 0)
                fail += _topo_case(s, "s-stamp-nonrel",    _b_stamp_nonrel,    1, 0, 2)

                # (d) NO UNSCOPED WIPE — self-scan this module's own source
                hits = _UNSCOPED.findall(Path(__file__).read_text())
                fail += [] if hits == [] else [("clause d: unscoped-wipe shape found in own source", hits)]

                # (e) ORPHAN SWEEP — one orphan (o_key never resolved to an :Entity) + one healthy
                # candidate (both endpoints resolved); dry-run lists exactly the orphan, --apply
                # removes exactly it, the healthy candidate survives.
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Issue", "issue:RB-2", S0, SNS, short="RB-2", long_="RB-2"))
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", "agent:RB-HEALTHY", S0, SNS, short="h", long_="h"))
                healthy_id = staging.stage(s, "issue:RB-2", "ASSIGNED_TO", "agent:RB-HEALTHY", SNS, "human", S0)
                orphan_id = staging.stage(s, "issue:RB-2", "ASSIGNED_TO", "agent:RB-GHOST", SNS, "human", S0)
                dry_orphans = sweep_candidates(s, SNS, apply=False)
                fail += [] if dry_orphans == [orphan_id] else \
                    [("clause e: dry-run orphan list wrong", dry_orphans, orphan_id, healthy_id)]
                applied = sweep_candidates(s, SNS, apply=True)
                remaining = s.execute_read(lambda tx: [r["cand_id"] for r in tx.run(
                    "MATCH (c:Candidate {namespace:$ns}) RETURN c.cand_id AS cand_id", ns=SNS)])
                fail += [] if (applied == [orphan_id] and remaining == [healthy_id]) else \
                    [("clause e: --apply did not remove exactly the orphan", applied, remaining)]

                # PIR P3: prove the delete statement's OWN {namespace:$ns} predicate has real
                # effect, belt-and-suspenders with the id list. NOTE: a genuine cross-namespace
                # cand_id COLLISION turns out to be schema-impossible here — 01_constraints.cypher's
                # `candidate_cand_id IS UNIQUE` is GLOBAL, not per-namespace (confirmed directly:
                # forcing a duplicate raises a Neo4j ConstraintError) — so this exercises the guarded
                # delete's exact Cypher shape with an ids list that (as a future bug or refactor
                # might) wrongly includes healthy_id (SNS, legitimately deletable) alongside
                # other_id, a real candidate that lives in a DIFFERENT namespace.
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Issue", "issue:RB-OTHER", S0, SNS_OTHER, short="o", long_="o"))
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", "agent:RB-OTHER", S0, SNS_OTHER, short="o", long_="o"))
                other_id = staging.stage(s, "issue:RB-OTHER", "ASSIGNED_TO", "agent:RB-OTHER", SNS_OTHER, "human", S0)
                s.execute_write(lambda tx: tx.run(
                    "MATCH (c:Candidate {namespace:$ns}) WHERE c.cand_id IN $ids DETACH DELETE c",
                    ns=SNS, ids=[healthy_id, other_id]))
                sns_after = s.execute_read(lambda tx: [r["cand_id"] for r in tx.run(
                    "MATCH (c:Candidate {namespace:$ns}) RETURN c.cand_id AS cand_id", ns=SNS)])
                other_survives = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id, namespace:$ns}) RETURN count(c) AS c",
                    id=other_id, ns=SNS_OTHER).single()["c"])
                fail += [] if (sns_after == [] and other_survives == 1) else \
                    [("clause e: namespace-scoped delete let an out-of-namespace id through, or wrongly reached it",
                      sns_after, other_survives)]

                # (f) GATEWAY GREEN — regression, unmodified by anything in this module
                gw_path = Path(__file__).parent.parent.parent / "tools" / "check_write_gateway.py"
                gw = subprocess.run([sys.executable, str(gw_path)], capture_output=True, text=True, timeout=30)
                fail += [] if (gw.returncode == 0 and "WRITE_GATEWAY_OK" in gw.stdout) else \
                    [("clause f: write-gateway gate not green", gw.returncode, gw.stdout, gw.stderr)]
            finally:
                _clean(s, SNS)
                _clean(s, SNS_EXT)
                _clean(s, SNS_OTHER)
    if fail:
        print("ROLLBACK_FAIL:", fail)
        sys.exit(1)
    print("ROLLBACK_OK")


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="rollback.py", description="namespace-scoped rollback + orphaned :Candidate sweep")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sweep-candidates")
    ps.add_argument("namespace")
    ps.add_argument("--apply", action="store_true")
    pr = sub.add_parser("rollback-namespace")
    pr.add_argument("namespace")
    pr.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            if args.cmd == "sweep-candidates":
                sweep_candidates(s, args.namespace, args.apply)
            elif args.cmd == "rollback-namespace":
                rollback_namespace(s, args.namespace, args.apply)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        _cli(sys.argv[1:])
