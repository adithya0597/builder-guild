"""builder-guild-7mg: the ingest-time candidate-stage + approval gate (the missing truth-gate).

WHY: abstain.py is a SERVE-time READ gate; etl.ingest writes straight through mutate.apply_edge,
which validates STRUCTURE (relation/arity/cycle) NOT truth. So an LLM extractor feeding apply_edge
would write hallucinated-but-well-shaped facts. This module is the gate that sits BEFORE apply_edge:
an LLM (or any low-trust source) can only STAGE a candidate; a human/promote step is the sole path
to a real edge.

Invariants honored:
  - Candidates are :Candidate NODES (never :Entity, never a RELATES_TO edge). Every existing reader/
    sweep (serve/ladder/node_card, invariant_check, cycle_check) matches :Entity + RELATES_TO, so a
    PENDING candidate is structurally invisible to reads. No promote = no edge = nothing to see.
  - promote() is the ONLY function that writes an edge, and it delegates to mutate.apply_edge — the
    SOLE sanctioned write gateway (tools/check_write_gateway.py stays green: this module hand-writes
    zero RELATES_TO edges; its only RELATES_TO Cypher are plain MATCH..count reads).
  - stage() / stage_llm() are write-INCAPABLE by construction: they touch :Candidate nodes only and
    hold NO reference to mutate.apply_edge, so an ingest entrypoint literally cannot create an edge.
  - Explicit `now` on every write (never ambient datetime inside a mutation — the repo temporal
    reproducibility invariant). The human CLI supplies wall-clock now once at the boundary.
  - Deterministic cand_id = sha1(json.dumps([ns,s_key,rel,o_key,origin])) -> re-stage is idempotent
    (MERGE ON CREATE only, so a re-stage never resets an approved/rejected/promoted candidate). JSON
    (not a bare '|'-join) keeps the 5 fields collision-proof when a field itself contains '|'.
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from neo4j import GraphDatabase

import mutate            # promote() delegates edge writes to the sole gateway (mutate.apply_edge)
import etl               # node_card — the read used to assert pending-candidate invisibility
import ladder            # keyword_rung / graph_rung — literal ladder-level invisibility probes
import invariant_check   # single-current sweep — clause (e), scoped to the selftest namespace
import cycle_check       # cycle sweep — clause (e), scoped to the selftest namespace

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))  # local/CI dev cred (not a secret)


def _cand_id(ns, s_key, rel, o_key, origin):
    # json.dumps quotes+escapes each field, so a literal '|' inside a field can't shift the field
    # boundary and collide with a neighboring tuple (a bare '|'.join() could: ('a|b','c') vs ('a','b|c')).
    payload = json.dumps([ns, s_key, rel, o_key, origin], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha1(payload.encode()).hexdigest()


def stage(session, s_key, rel, o_key, ns, origin, now, ep=None):
    """Stage ONE candidate as a :Candidate node (no edge, no :Entity). status/staged_at are set
    ON CREATE only -> a re-stage of the same (ns,s,rel,o,origin) is idempotent and never resets an
    already-reviewed candidate. Returns the deterministic cand_id."""
    cid = _cand_id(ns, s_key, rel, o_key, origin)
    session.execute_write(lambda tx: tx.run(
        "MERGE (c:Candidate {cand_id:$id}) "
        "ON CREATE SET c.status='pending', c.s_key=$s, c.rel=$rel, c.o_key=$o, "
        "              c.namespace=$ns, c.origin=$origin, c.ep=$ep, c.staged_at=datetime($now)",
        id=cid, s=s_key, rel=rel, o=o_key, ns=ns, origin=origin, ep=ep, now=now))
    return cid


def stage_llm(session, edges, now):
    """The origin='llm' ingest entrypoint that can ONLY stage. Takes pre-built edge tuples
    (s_key, rel, o_key, ns) or (s_key, rel, o_key, ns, ep) and loops stage(..., origin='llm').
    Holds NO reference to mutate.apply_edge -> structurally unable to direct-write an edge."""
    ids = []
    for e in edges:
        ep = e[4] if len(e) > 4 else None
        ids.append(stage(session, e[0], e[1], e[2], e[3], "llm", now, ep))
    return ids


def _get(tx, cand_id):
    # properties(c) names no absent optional key (ep is unset when staged with ep=None), so the read
    # never trips Neo4j's "property key does not exist" notification. Returns the property map or None.
    rec = tx.run("MATCH (c:Candidate {cand_id:$id}) RETURN properties(c) AS p", id=cand_id).single()
    return rec["p"] if rec else None


def approve(session, cand_id, now):
    """pending -> approved (records reviewed_at). Raises ValueError (naming the id and required
    status, mirroring promote()'s guard) when cand_id is missing or not 'pending' — a no-match must
    never look like a success to the CLI/operator."""
    def _work(tx):
        c = _get(tx, cand_id)
        if c is None:
            raise ValueError(f"approve: no candidate {cand_id}")
        if c["status"] != "pending":
            raise ValueError(f"approve requires status=pending, got '{c['status']}' for {cand_id}")
        tx.run("MATCH (c:Candidate {cand_id:$id}) SET c.status='approved', c.reviewed_at=datetime($now)",
               id=cand_id, now=now)
    session.execute_write(_work)


def reject(session, cand_id, reason, now):
    """pending/approved -> rejected (records review_reason + reviewed_at). Raises ValueError (naming
    the id and required status, mirroring promote()'s guard) when cand_id is missing or not
    pending/approved. Never touches the graph — a :Candidate property write only, leaving an
    auditable rejected record."""
    def _work(tx):
        c = _get(tx, cand_id)
        if c is None:
            raise ValueError(f"reject: no candidate {cand_id}")
        if c["status"] not in ("pending", "approved"):
            raise ValueError(f"reject requires status in ['pending','approved'], got '{c['status']}' for {cand_id}")
        tx.run("MATCH (c:Candidate {cand_id:$id}) SET c.status='rejected', c.review_reason=$reason, "
               "c.reviewed_at=datetime($now)", id=cand_id, reason=reason, now=now)
    session.execute_write(_work)


def promote(session, cand_id, now):
    """approved -> promoted: materialize the edge THROUGH mutate.apply_edge (the sole gateway), then
    flag the candidate promoted — atomically in one tx (if apply_edge raises, status does not flip).
    apply_edge's final MERGE MATCHes both endpoints as existing :Entity nodes BY KEY ONLY — it does not
    care which namespace owns them. So before calling it, we verify each endpoint is owned by the
    candidate's OWN namespace OR by 'shared' (n.namespace IN {candidate.namespace, 'shared'}) — 'shared'
    is the cross-cutting reference slice every namespace may point into (scope.py's ROLE_NAMESPACES
    gives every role [own_ns, 'shared']; etl.py seeds StatusValue nodes as issue -HAS_STATUS-> status:x
    under ns='shared'), so a domain edge into a shared reference node is a valid fact, not a bypass.
    A missing endpoint, or one owned by a DIFFERENT non-shared namespace, still raises; otherwise a
    candidate staged in namespace A could silently splice an edge onto entities owned by an unrelated
    namespace B (the staging gate would become a namespace-isolation bypass). This is a pre-condition,
    not a post-check: edge_state
    can't catch this after the fact because it only verifies the EDGE carries the expected namespace
    tag — which is always true, since apply_edge stamps whatever namespace it's given regardless of
    who owns the endpoints. A violation raises and nothing is written (whole tx rolls back).
    apply_edge's final MERGE also still needs both endpoints to have been RESOLVED at all; if either
    was never resolved, that MATCH finds zero rows and apply_edge returns normally having written
    nothing (an evict-overflow relation may even have superseded the incumbent first). So the edge is
    ALSO verified via mutate.edge_state before flipping status; if it isn't current, we raise instead —
    the whole tx rolls back (undoing any partial apply_edge write too) and the candidate stays
    'approved', not 'promoted' over a fact that was silently never written.
    Idempotent: an already-'promoted' candidate is a no-op (returns False); otherwise returns True."""
    def _work(tx):
        c = _get(tx, cand_id)
        if c is None:
            raise ValueError(f"promote: no candidate {cand_id}")
        if c["status"] == "promoted":
            return False                                  # clause (d): idempotent no-op
        if c["status"] != "approved":
            raise ValueError(f"promote requires status=approved, got '{c['status']}'")
        owner = tx.run(
            "OPTIONAL MATCH (s:Entity {key:$s}) OPTIONAL MATCH (o:Entity {key:$o}) "
            "RETURN s.namespace AS s_ns, o.namespace AS o_ns",
            s=c["s_key"], o=c["o_key"]).single()
        if any(ns not in (c["namespace"], "shared") for ns in (owner["s_ns"], owner["o_ns"])):
            raise ValueError(
                f"promote: namespace isolation — {c['s_key']} -{c['rel']}-> {c['o_key']} candidate "
                f"is staged in '{c['namespace']}' but subject owner={owner['s_ns']!r}, "
                f"object owner={owner['o_ns']!r} — endpoints must be owned by '{c['namespace']}' or "
                f"'shared', stays 'approved'")
        mutate.apply_edge(tx, c["s_key"], c["rel"], c["o_key"], now, c["namespace"], c.get("ep"))
        if mutate.edge_state(tx, c["s_key"], c["rel"], c["o_key"], c["namespace"]) is not True:
            raise ValueError(f"promote: edge {c['s_key']} -{c['rel']}-> {c['o_key']} did not "
                              f"materialize (endpoint not a resolved :Entity?) — stays 'approved'")
        tx.run("MATCH (c:Candidate {cand_id:$id}) "
               "SET c.status='promoted', c.promoted_at=datetime($now)", id=cand_id, now=now)
        return True
    return session.execute_write(_work)


def list_candidates(session, status=None):
    """Deterministic listing (ORDER BY cand_id), optionally filtered to one status."""
    def _read(tx):
        q = ("MATCH (c:Candidate) " + ("WHERE c.status=$status " if status else "") +
             "RETURN c.cand_id AS cand_id, c.status AS status, c.s_key AS s_key, c.rel AS rel, "
             "       c.o_key AS o_key, c.namespace AS namespace, c.origin AS origin, "
             "       c.staged_at AS staged_at, c.review_reason AS review_reason ORDER BY c.cand_id")
        return [dict(r) for r in tx.run(q, status=status)]
    return session.execute_read(_read)


# ── selftest read helpers (plain RELATES_TO MATCH reads — no write verb near the pattern, so the
#    write-gateway grep-gate stays green with staging.py OUTSIDE its allowlist) ─────────────────
def _edge_count(tx, s_key, rel, o_key):
    return tx.run(
        "MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel}]->(o:Entity {key:$o}) "
        "WHERE r.invalid_at > datetime() RETURN count(r) AS c",
        s=s_key, rel=rel, o=o_key).single()["c"]


def _total_rel(tx):
    return tx.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c").single()["c"]


def _clean(session, ns):
    session.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=ns))


def _selftest():
    """Prove the gate (acceptance a-e + orchestrator directives) in an isolated, self-cleaning
    namespace. Uses ASSIGNED_TO (arity:1) so clause (e)'s single-current sweep is meaningfully
    exercised. The OBJECT entity is seeded just before promote (subject up front): apply_edge needs
    both endpoints, and keeping the object un-materialized while pending is what makes the directive's
    'ladder rungs return zero while pending' probe NON-VACUOUS (keyword_rung fires on it post-promote).
    """
    SNS = "_staging_selftest"
    SNS_B = "_staging_selftest_b"          # a SECOND namespace, used only by the (g) cross-namespace case
    REL = "ASSIGNED_TO"
    STATUS_KEY = "status:STG-TEST-OPEN"    # test-unique shared-namespace node, used only by case (h)
    SUBJ, OBJ, OBJ2, OBJ3 = "issue:STG-1", "agent:STG-ALICE", "agent:STG-BOB", "agent:STG-CAROL"
    S0, S1, S2, S3 = ("2026-06-30T00:00:00Z", "2026-06-30T01:00:00Z",
                      "2026-06-30T02:00:00Z", "2026-06-30T03:00:00Z")
    allowed = [SNS]
    fail = []

    # bead 7mg fix 1 — collision guard (pure-python, no graph): the old bare '|'-joined scheme let a
    # field boundary shift and collide, e.g. (s_key="foo|BAR", rel="X") vs (s_key="foo", rel="BAR|X")
    # both joined to "...foo|BAR|X...". json.dumps must keep these two distinct tuples apart.
    collided = (_cand_id("ns", "foo|BAR", "X", "o", "human")
                == _cand_id("ns", "foo", "BAR|X", "o", "human"))
    fail += [] if not collided else [("cand_id collision reintroduced for '|'-containing fields",)]

    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            try:
                _clean(s, SNS)
                _clean(s, SNS_B)
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Issue", SUBJ, S0, SNS, short=SUBJ, long_=SUBJ, ep="stg-ep"))

                # (a) stage an edge SUBJ -ASSIGNED_TO-> OBJ; it must be invisible to every read while pending
                c1 = stage(s, SUBJ, REL, OBJ, SNS, "human", S0)
                exists = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id}) RETURN count(c) AS c", id=c1).single()["c"])
                card, facts = s.execute_read(lambda tx: etl.node_card(tx, SUBJ, allowed))
                cnt = s.execute_read(lambda tx: _edge_count(tx, SUBJ, REL, OBJ))
                kw = s.execute_read(lambda tx: ladder.keyword_rung(tx, allowed, OBJ))     # OBJ not yet an :Entity -> []
                gr = s.execute_read(lambda tx: ladder.graph_rung(tx, allowed, {"rel": REL, "obj": OBJ}))
                fail += [] if exists == 1 else [("stage did not create exactly one :Candidate", exists)]
                fail += [] if (facts == [] and cnt == 0) else [("pending visible to node_card/direct count", facts, cnt)]
                fail += [] if (kw == [] and gr == []) else [("pending visible to ladder rungs (kw,gr)", kw, gr)]

                # (b) approve -> seed object -> promote; edge is now current and went THROUGH apply_edge
                approve(s, c1, S1)
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", OBJ, S1, SNS, short=OBJ, long_=OBJ, ep="stg-ep"))
                did1 = promote(s, c1, S2)
                st = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, REL, OBJ, SNS))
                tg = s.execute_read(lambda tx: mutate.current_targets(tx, SUBJ, REL, SNS))
                _, facts_p = s.execute_read(lambda tx: etl.node_card(tx, SUBJ, allowed))
                gr2 = s.execute_read(lambda tx: ladder.graph_rung(tx, allowed, {"rel": REL, "obj": OBJ}))
                kw2 = s.execute_read(lambda tx: ladder.keyword_rung(tx, allowed, OBJ))
                fail += [] if (did1 is True and st is True and tg == [OBJ] and gr2 == [SUBJ]
                               and kw2 == [OBJ] and (REL + " -> " + OBJ) in facts_p) \
                    else [("promote did not materialize edge through apply_edge", did1, st, tg, gr2, kw2, facts_p)]

                # (d) re-promote an already-promoted candidate = no-op, current stays length 1 (idempotent)
                did2 = promote(s, c1, S3)
                tg2 = s.execute_read(lambda tx: mutate.current_targets(tx, SUBJ, REL, SNS))
                fail += [] if (did2 is False and len(tg2) == 1) else [("re-promote not idempotent", did2, tg2)]

                # (f) promote must REFUSE when the candidate's object is not yet a materialized :Entity —
                # apply_edge's endpoint MATCH would silently no-op (ASSIGNED_TO is arity:1 overflow:evict,
                # so it would even supersede the current ALICE edge first). Approve+promote must raise,
                # leave the candidate 'approved' (not 'promoted'), write zero edges, and leave the
                # pre-existing SUBJ->OBJ current edge untouched (whole-tx rollback).
                OBJ4 = "agent:STG-DAVE"
                c3 = stage(s, SUBJ, REL, OBJ4, SNS, "human", S1)
                approve(s, c3, S2)
                try:
                    promote(s, c3, S3)
                    refused = False
                except ValueError:
                    refused = True
                c3_after = s.execute_read(lambda tx: _get(tx, c3))
                tg3 = s.execute_read(lambda tx: mutate.current_targets(tx, SUBJ, REL, SNS))
                cnt3 = s.execute_read(lambda tx: _edge_count(tx, SUBJ, REL, OBJ4))
                fail += [] if (refused and c3_after["status"] == "approved" and cnt3 == 0 and tg3 == [OBJ]) \
                    else [("promote lost/flipped status despite missing object entity",
                           refused, c3_after["status"] if c3_after else None, cnt3, tg3)]

                # materialize the object -> re-promote now succeeds and the edge is current
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", OBJ4, S3, SNS, short=OBJ4, long_=OBJ4, ep="stg-ep"))
                did3 = promote(s, c3, S3)
                st3 = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, REL, OBJ4, SNS))
                fail += [] if (did3 is True and st3 is True) \
                    else [("promote did not succeed once the object was materialized", did3, st3)]

                # (g) promote must REFUSE a cross-namespace splice: OBJ5 is a real, resolved :Entity —
                # just owned by a DIFFERENT namespace (SNS_B) than the candidate (SNS). apply_edge's
                # endpoint MATCH would happily find it by key alone and splice a SNS-stamped edge onto
                # a SNS_B-owned entity. Approve+promote must raise, leave the candidate 'approved', and
                # write zero SUBJ->OBJ5 edges — the current SUBJ->OBJ4 edge from (f) must stay untouched.
                OBJ5 = "agent:STG-EVE"
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", OBJ5, S0, SNS_B, short=OBJ5, long_=OBJ5, ep="stg-ep-b"))
                c4 = stage(s, SUBJ, REL, OBJ5, SNS, "human", S1)
                approve(s, c4, S2)
                try:
                    promote(s, c4, S3)
                    refused_ns = False
                except ValueError:
                    refused_ns = True
                c4_after = s.execute_read(lambda tx: _get(tx, c4))
                cnt4 = s.execute_read(lambda tx: _edge_count(tx, SUBJ, REL, OBJ5))
                tg4 = s.execute_read(lambda tx: mutate.current_targets(tx, SUBJ, REL, SNS))
                fail += [] if (refused_ns and c4_after["status"] == "approved" and cnt4 == 0 and tg4 == [OBJ4]) \
                    else [("promote allowed a cross-namespace splice",
                           refused_ns, c4_after["status"] if c4_after else None, cnt4, tg4)]

                # (h) promote must ALLOW an edge onto a SHARED reference entity even though the
                # candidate is staged in SNS — this is the real ingest pattern (etl.py seeds
                # issue -HAS_STATUS-> status:<value> under ns='shared'). STATUS_KEY is test-unique
                # and lives under the REAL 'shared' namespace; it is deleted in the finally block
                # below so no shared-namespace residue survives the selftest.
                s.execute_write(lambda tx: mutate.resolve_entity(
                    tx, "StatusValue", STATUS_KEY, S1, "shared", short=STATUS_KEY, long_=STATUS_KEY, ep="stg-ep-shared"))
                c5 = stage(s, SUBJ, "HAS_STATUS", STATUS_KEY, SNS, "human", S1)
                approve(s, c5, S2)
                did5 = promote(s, c5, S3)
                st5 = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, "HAS_STATUS", STATUS_KEY, SNS))
                fail += [] if (did5 is True and st5 is True) \
                    else [("promote refused a valid shared-namespace endpoint", did5, st5)]

                # (c) reject a 2nd candidate: graph untouched + an auditable rejected record survives
                c2 = stage(s, SUBJ, REL, OBJ2, SNS, "human", S1)
                reject(s, c2, "hallucinated-not-in-source", S2)
                cnt2 = s.execute_read(lambda tx: _edge_count(tx, SUBJ, REL, OBJ2))
                rj = [c for c in list_candidates(s, status="rejected") if c["cand_id"] == c2]
                fail += [] if (cnt2 == 0 and rj and rj[0]["review_reason"] == "hallucinated-not-in-source") \
                    else [("reject touched graph or lost audit record", cnt2, rj)]

                # directive: stage_llm stages ONLY :Candidate origin='llm' and creates ZERO edges
                before = s.execute_read(_total_rel)
                llm_ids = stage_llm(s, [(SUBJ, REL, OBJ3, SNS)], S1)
                after = s.execute_read(_total_rel)
                origin = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id}) RETURN c.origin AS o", id=llm_ids[0]).single()["o"])
                leaked = s.execute_read(lambda tx: ladder.keyword_rung(tx, allowed, OBJ3))   # no :Entity created
                fail += [] if (after == before and origin == "llm" and leaked == []) \
                    else [("stage_llm created an edge/entity or mis-tagged origin", before, after, origin, leaked)]

                # (i) approve()/reject() must RAISE (not silently no-op) when the target candidate is
                # missing or not in a valid status — an operator must never see "approved: <id>" or
                # "rejected: <id>" printed by the CLI when zero rows actually changed underneath it.
                try:
                    approve(s, "bogus-cand-id-does-not-exist", S3)
                    approve_refused = False
                except ValueError:
                    approve_refused = True
                fail += [] if approve_refused else [("approve() did not raise for a missing cand_id",)]

                c1_before = s.execute_read(lambda tx: _get(tx, c1))    # c1 is already 'promoted' (case b/d)
                try:
                    reject(s, c1, "too-late", S3)
                    reject_refused = False
                except ValueError:
                    reject_refused = True
                c1_after = s.execute_read(lambda tx: _get(tx, c1))
                fail += [] if (reject_refused and c1_before["status"] == "promoted"
                               and c1_after["status"] == c1_before["status"]) \
                    else [("reject() did not raise or changed status of an already-promoted candidate",
                           reject_refused, c1_before["status"] if c1_before else None,
                           c1_after["status"] if c1_after else None)]

                # (e) invariant + cycle sweeps green for this namespace after promote (scoped so a
                #     pre-existing violation elsewhere can't taint the assertion)
                inv = [v for v in s.execute_read(invariant_check.check) if v["ns"] == SNS]
                cyc = [v for v in s.execute_read(cycle_check.check) if v["ns"] == SNS]
                fail += [] if (inv == [] and cyc == []) else [("promote broke a sweep in-namespace", inv, cyc)]
            finally:
                _clean(s, SNS)
                _clean(s, SNS_B)
                s.execute_write(lambda tx: tx.run("MATCH (n {key:$k}) DETACH DELETE n", k=STATUS_KEY))
    if fail:
        print("STAGING_FAIL:", fail)
        sys.exit(1)
    print("STAGING_OK")


def _fmt_candidate(c):
    """One aligned, human-scannable line. Namespace is called out explicitly (ns=...) since it's the
    blast-radius signal a reviewer must see before approving — 'shared' means every role reads it
    once promoted."""
    extra = ""
    if c.get("staged_at"):
        extra += f"  staged={c['staged_at']}"
    if c.get("review_reason"):
        extra += f"  reason={c['review_reason']}"
    return (f"{c['cand_id'][:12]}  {c['status']:<9} ns={c['namespace']:<12} "
            f"{c['s_key']} -{c['rel']}-> {c['o_key']}  origin={c['origin']}{extra}")


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="staging.py", description="candidate-stage + approval gate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("--status", choices=["all", "pending", "approved", "rejected", "promoted"],
                     default="pending")
    pa = sub.add_parser("approve"); pa.add_argument("id")
    pr = sub.add_parser("reject"); pr.add_argument("id"); pr.add_argument("reason")
    pp = sub.add_parser("promote"); pp.add_argument("id")
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")   # human action -> wall-clock, threaded explicitly
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            if args.cmd == "list":
                status = None if args.status == "all" else args.status
                for c in list_candidates(s, status):
                    print(_fmt_candidate(c))
            elif args.cmd == "approve":
                approve(s, args.id, now); print(f"approved: {args.id}")
            elif args.cmd == "reject":
                reject(s, args.id, args.reason, now); print(f"rejected: {args.id} ({args.reason})")
            elif args.cmd == "promote":
                print(f"promoted: {args.id}" if promote(s, args.id, now) else f"noop (already promoted): {args.id}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        _cli(sys.argv[1:])
