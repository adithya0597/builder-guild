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


def stage(session, s_key, rel, o_key, ns, origin, now, ep=None, evidence=None, source=None, batch_id=None):
    """Stage ONE candidate as a :Candidate node (no edge, no :Entity). status/staged_at are set
    ON CREATE only -> a re-stage of the same (ns,s,rel,o,origin) is idempotent and never resets an
    already-reviewed candidate. evidence/source are optional review-surface metadata (rationale text
    + a source ref); None -> the Cypher SET writes null, which removes the property (same idiom as
    ep). batch_id is optional per-call grouping metadata (same null->absent idiom); default None ->
    zero behavior change for existing callers. Returns the deterministic cand_id."""
    cid = _cand_id(ns, s_key, rel, o_key, origin)
    session.execute_write(lambda tx: tx.run(
        "MERGE (c:Candidate {cand_id:$id}) "
        "ON CREATE SET c.status='pending', c.s_key=$s, c.rel=$rel, c.o_key=$o, "
        "              c.namespace=$ns, c.origin=$origin, c.ep=$ep, c.staged_at=datetime($now), "
        "              c.evidence=$evidence, c.source=$source, c.batch_id=$batch_id",
        id=cid, s=s_key, rel=rel, o=o_key, ns=ns, origin=origin, ep=ep, now=now,
        evidence=evidence, source=source, batch_id=batch_id))
    return cid


def stage_llm(session, edges, now, batch_id=None):
    """The origin='llm' ingest entrypoint that can ONLY stage. Takes pre-built edge tuples
    (s_key, rel, o_key, ns), (s_key, rel, o_key, ns, ep), or (s_key, rel, o_key, ns, ep, evidence,
    source) and loops stage(..., origin='llm'). Holds NO reference to mutate.apply_edge ->
    structurally unable to direct-write an edge. batch_id (optional, default None) is applied to
    EVERY edge in this call -> the whole extraction run shares one batch_id."""
    ids = []
    for e in edges:
        ep = e[4] if len(e) > 4 else None
        evidence = e[5] if len(e) > 5 else None
        source = e[6] if len(e) > 6 else None
        ids.append(stage(session, e[0], e[1], e[2], e[3], "llm", now, ep, evidence, source, batch_id))
    return ids


def _get(tx, cand_id):
    # properties(c) names no absent optional key (ep is unset when staged with ep=None), so the read
    # never trips Neo4j's "property key does not exist" notification. Returns the property map or None.
    rec = tx.run("MATCH (c:Candidate {cand_id:$id}) RETURN properties(c) AS p", id=cand_id).single()
    return rec["p"] if rec else None


def approve(session, cand_id, now):
    """pending -> approved (records reviewed_at). Raises ValueError (naming the id and required
    status, mirroring promote()'s guard) when cand_id is missing or not 'pending' — a no-match must
    never look like a success to the CLI/operator. Race-safe: locks the candidate first (same _plock
    as promote()), so a concurrent approve/reject/promote on the same cand_id serializes here; the
    loser's guarded CAS then raises with a message naming the lost race."""
    def _work(tx):
        # lock-first, same _plock promote() uses (see promote()'s comment, staging.py:143-148, for
        # why): serializes approve/reject/promote against EACH OTHER on the SAME cand_id.
        tx.run("MATCH (c:Candidate {cand_id:$id}) SET c._plock=$now", id=cand_id, now=now)
        c = _get(tx, cand_id)
        if c is None:
            raise ValueError(f"approve: no candidate {cand_id}")
        if c["status"] != "pending":
            raise ValueError(f"approve requires status=pending, got '{c['status']}' for {cand_id}")
        won = tx.run("MATCH (c:Candidate {cand_id:$id, status:'pending'}) "
                     "SET c.status='approved', c.reviewed_at=datetime($now) RETURN c.cand_id AS id",
                     id=cand_id, now=now).single()
        if won is None:
            raise ValueError(f"approve: lost status race — candidate {cand_id} no longer 'pending' "
                              f"(concurrent approve/reject won); nothing written")
    session.execute_write(_work)


def reject(session, cand_id, reason, now):
    """pending/approved -> rejected (records review_reason + reviewed_at). Raises ValueError (naming
    the id and required status, mirroring promote()'s guard) when cand_id is missing or not
    pending/approved. Never touches the graph — a :Candidate property write only, leaving an
    auditable rejected record. Race-safe: locks the candidate first (same _plock as approve()/
    promote()), so reject dominates a concurrent approve (both may legally succeed, ending
    'rejected') and is refused after a concurrent promote (raises, edge and status untouched)."""
    def _work(tx):
        # lock-first, same _plock approve()/promote() use — serializes reject against a concurrent
        # approve/promote on the SAME cand_id.
        tx.run("MATCH (c:Candidate {cand_id:$id}) SET c._plock=$now", id=cand_id, now=now)
        c = _get(tx, cand_id)
        if c is None:
            raise ValueError(f"reject: no candidate {cand_id}")
        if c["status"] not in ("pending", "approved"):
            raise ValueError(f"reject requires status in ['pending','approved'], got '{c['status']}' for {cand_id}")
        won = tx.run("MATCH (c:Candidate {cand_id:$id}) WHERE c.status IN ['pending','approved'] "
                     "SET c.status='rejected', c.review_reason=$reason, c.reviewed_at=datetime($now) "
                     "RETURN c.cand_id AS id", id=cand_id, reason=reason, now=now).single()
        if won is None:
            raise ValueError(f"reject: lost status race — candidate {cand_id} no longer in "
                              f"['pending','approved'] (concurrent promote/reject won); nothing written")
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
        # FIX-RACE (builder-guild-485): lock the Candidate node itself before reading it, so two
        # concurrent promote() calls on the SAME cand_id serialize HERE regardless of the staged
        # relation's arity. apply_edge's own subject _wlock (mutate.py `if functional and lock:`)
        # only fires for arity:1 relations — an arity:inf candidate (BLOCKS, OWNS, RELATED_TO, ...)
        # would otherwise race straight through to the CAS below with no serialization at all.
        tx.run("MATCH (c:Candidate {cand_id:$id}) SET c._plock=$now", id=cand_id, now=now)
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
        won = tx.run("MATCH (c:Candidate {cand_id:$id, status:'approved'}) "
                     "SET c.status='promoted', c.promoted_at=datetime($now) "
                     "RETURN c.cand_id AS id", id=cand_id, now=now).single()
        if won is None:
            raise ValueError(
                f"promote: lost status race — candidate {cand_id} no longer 'approved' "
                f"(concurrent promote/reject won); nothing written")
        return True
    return session.execute_write(_work)


def list_candidates(session, status=None, batch_id=None):
    """Deterministic listing (ORDER BY cand_id), optionally filtered to one status and/or one
    batch_id (composable — both filters apply together when both are given)."""
    def _read(tx):
        clauses = []
        if status:
            clauses.append("c.status=$status")
        if batch_id:
            clauses.append("c.batch_id=$batch_id")
        where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
        q = ("MATCH (c:Candidate) " + where +
             "RETURN c.cand_id AS cand_id, c.status AS status, c.s_key AS s_key, c.rel AS rel, "
             "       c.o_key AS o_key, c.namespace AS namespace, c.origin AS origin, "
             "       c.staged_at AS staged_at, c.review_reason AS review_reason, "
             "       c.evidence AS evidence, c.source AS source ORDER BY c.cand_id")
        return [dict(r) for r in tx.run(q, status=status, batch_id=batch_id)]
    return session.execute_read(_read)


# ── batch ops: thin loops over the EXISTING per-candidate CAS-locked approve/reject/promote — no
#    new locking primitive, no new edge-write path. A per-candidate ValueError (wrong-state / lost
#    race) is collected as an error entry, never aborting the rest of the batch (etl dead-letter
#    idiom) ──────────────────────────────────────────────────────────────────────────────────────
def batch_approve(session, batch_id, now):
    if not batch_id:
        raise ValueError("batch_approve: empty batch_id would operate graph-wide; refusing")
    results = {}
    for c in list_candidates(session, batch_id=batch_id):
        try:
            approve(session, c["cand_id"], now)
            results[c["cand_id"]] = "ok"
        except ValueError as e:
            results[c["cand_id"]] = f"error: {e}"
    return results


def batch_reject(session, batch_id, now, reason):
    if not batch_id:
        raise ValueError("batch_reject: empty batch_id would operate graph-wide; refusing")
    results = {}
    for c in list_candidates(session, batch_id=batch_id):
        try:
            reject(session, c["cand_id"], reason, now)
            results[c["cand_id"]] = "ok"
        except ValueError as e:
            results[c["cand_id"]] = f"error: {e}"
    return results


def batch_promote(session, batch_id, now):
    if not batch_id:
        raise ValueError("batch_promote: empty batch_id would operate graph-wide; refusing")
    results = {}
    for c in list_candidates(session, batch_id=batch_id):
        try:
            promote(session, c["cand_id"], now)
            results[c["cand_id"]] = "ok"
        except ValueError as e:
            results[c["cand_id"]] = f"error: {e}"
    return results


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
                c1 = stage(s, SUBJ, REL, OBJ, SNS, "human", S0, evidence="stg-evidence", source="stg-source")
                exists = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id}) RETURN count(c) AS c", id=c1).single()["c"])
                card, facts = s.execute_read(lambda tx: etl.node_card(tx, SUBJ, allowed))
                cnt = s.execute_read(lambda tx: _edge_count(tx, SUBJ, REL, OBJ))
                kw = s.execute_read(lambda tx: ladder.keyword_rung(tx, allowed, OBJ))     # OBJ not yet an :Entity -> []
                gr = s.execute_read(lambda tx: ladder.graph_rung(tx, allowed, {"rel": REL, "obj": OBJ}))
                fail += [] if exists == 1 else [("stage did not create exactly one :Candidate", exists)]
                fail += [] if (facts == [] and cnt == 0) else [("pending visible to node_card/direct count", facts, cnt)]
                fail += [] if (kw == [] and gr == []) else [("pending visible to ladder rungs (kw,gr)", kw, gr)]

                # (a)/(d)-WITH: evidence/source persisted on stage
                c1_staged = s.execute_read(lambda tx: _get(tx, c1))
                fail += [] if (c1_staged["evidence"] == "stg-evidence" and c1_staged["source"] == "stg-source") \
                    else [("stage did not persist evidence/source", c1_staged.get("evidence"), c1_staged.get("source"))]

                # (b) approve -> seed object -> promote; edge is now current and went THROUGH apply_edge
                approve(s, c1, S1)
                c1_after_approve = s.execute_read(lambda tx: _get(tx, c1))
                fail += [] if (c1_after_approve["evidence"] == "stg-evidence" and c1_after_approve["source"] == "stg-source") \
                    else [("approve altered evidence/source", c1_after_approve.get("evidence"), c1_after_approve.get("source"))]
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

                # (a)/(d)-WITH: promote leaves candidate evidence/source unchanged and never writes them onto the edge
                c1_after_promote = s.execute_read(lambda tx: _get(tx, c1))
                fail += [] if (c1_after_promote["evidence"] == "stg-evidence" and c1_after_promote["source"] == "stg-source") \
                    else [("promote altered candidate evidence/source", c1_after_promote.get("evidence"), c1_after_promote.get("source"))]
                edge_props = s.execute_read(lambda tx: tx.run(
                    "MATCH (:Entity {key:$s})-[r:RELATES_TO {name:$rel}]->(:Entity {key:$o}) "
                    "WHERE r.invalid_at > datetime() RETURN properties(r) AS p",
                    s=SUBJ, rel=REL, o=OBJ).single()["p"])
                fail += [] if ("evidence" not in edge_props and "source" not in edge_props) \
                    else [("promote leaked evidence/source onto the graph edge", edge_props)]

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
                c3_staged = s.execute_read(lambda tx: _get(tx, c3))
                fail += [] if (c3_staged.get("evidence") is None and c3_staged.get("source") is None) \
                    else [("stage without evidence/source persisted a value", c3_staged.get("evidence"), c3_staged.get("source"))]
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

                # (a)/(d)-WITHOUT: evidence/source stay absent through the approve -> promote(fails) ->
                # materialize -> promote(succeeds) retry path
                c3_final = s.execute_read(lambda tx: _get(tx, c3))
                fail += [] if (c3_final.get("evidence") is None and c3_final.get("source") is None) \
                    else [("evidence/source appeared on a no-evidence candidate", c3_final.get("evidence"), c3_final.get("source"))]

                # (b) list_candidates()/_fmt_candidate() surface evidence/source when present, clean when absent
                lc = list_candidates(s)
                lc1 = next(c for c in lc if c["cand_id"] == c1)
                lc3 = next(c for c in lc if c["cand_id"] == c3)
                fail += [] if (lc1["evidence"] == "stg-evidence" and lc1["source"] == "stg-source") \
                    else [("list_candidates lost evidence/source for c1", lc1.get("evidence"), lc1.get("source"))]
                fail += [] if (lc3["evidence"] is None and lc3["source"] is None) \
                    else [("list_candidates fabricated evidence/source for c3", lc3.get("evidence"), lc3.get("source"))]
                fmt1, fmt3 = _fmt_candidate(lc1), _fmt_candidate(lc3)
                fail += [] if "evidence=" in fmt1 else [("_fmt_candidate missing evidence= for c1", fmt1)]
                fail += [] if "evidence=" not in fmt3 else [("_fmt_candidate showed evidence= for evidence-less c3", fmt3)]

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
                llm_ids = stage_llm(s, [(SUBJ, REL, OBJ3, SNS, None, "stg-evidence-llm", "stg-source-llm")], S1)
                after = s.execute_read(_total_rel)
                origin = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id}) RETURN c.origin AS o", id=llm_ids[0]).single()["o"])
                leaked = s.execute_read(lambda tx: ladder.keyword_rung(tx, allowed, OBJ3))   # no :Entity created
                fail += [] if (after == before and origin == "llm" and leaked == []) \
                    else [("stage_llm created an edge/entity or mis-tagged origin", before, after, origin, leaked)]

                # (a) stage_llm: 7-tuple with an ep hole (None) still lands evidence/source correctly
                llm_staged = s.execute_read(lambda tx: _get(tx, llm_ids[0]))
                fail += [] if (llm_staged.get("evidence") == "stg-evidence-llm" and llm_staged.get("source") == "stg-source-llm") \
                    else [("stage_llm 7-tuple did not persist evidence/source", llm_staged.get("evidence"), llm_staged.get("source"))]

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


def _selftest_batch():
    """Proves the batch surface (acceptance builder-guild-w6j) in its own self-cleaning namespace."""
    SNS = "_staging_selftest_batch"
    REL = "ASSIGNED_TO"
    SUBJ = "issue:BATCH-1"
    now = "2026-07-09T00:00:00Z"
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            try:
                _clean(s, SNS)
                s.execute_write(lambda tx: mutate.resolve_entity(
                    tx, "Issue", SUBJ, now, SNS, short=SUBJ, long_=SUBJ, ep="stg-ep"))

                b1a = stage(s, SUBJ, REL, "agent:BATCH-A", SNS, "human", now, batch_id="b1")
                b1b = stage(s, SUBJ, REL, "agent:BATCH-B", SNS, "human", now, batch_id="b1")
                b2a = stage(s, SUBJ, REL, "agent:BATCH-C", SNS, "human", now, batch_id="b2")
                no_batch = stage(s, SUBJ, REL, "agent:BATCH-D", SNS, "human", now)

                # batch filter is exact -> exactly the 2 'b1' candidates, none of 'b2' or no-batch
                lc_b1 = list_candidates(s, batch_id="b1")
                fail += [] if {c["cand_id"] for c in lc_b1} == {b1a, b1b} \
                    else [("list_candidates(batch_id='b1') wrong set", [c["cand_id"] for c in lc_b1])]

                # no-batch candidate carries no batch_id property at all (null -> absent, same idiom as ep)
                nb = s.execute_read(lambda tx: _get(tx, no_batch))
                fail += [] if "batch_id" not in nb else [("no-batch candidate got a batch_id property", nb.get("batch_id"))]

                # list_candidates() with no filter still returns everything staged above
                all_ids = {c["cand_id"] for c in list_candidates(s) if c["namespace"] == SNS}
                fail += [] if {b1a, b1b, b2a, no_batch} <= all_ids \
                    else [("list_candidates(no filter) missing candidates", all_ids)]

                # a 3rd 'b1' candidate already in a terminal state ('rejected') before batch_approve runs
                b1c = stage(s, SUBJ, REL, "agent:BATCH-E", SNS, "human", now, batch_id="b1")
                reject(s, b1c, "pre-rejected-for-batch-test", now)

                results = batch_approve(s, "b1", now)
                b1a_st = s.execute_read(lambda tx: _get(tx, b1a))["status"]
                b1b_st = s.execute_read(lambda tx: _get(tx, b1b))["status"]
                b1c_st = s.execute_read(lambda tx: _get(tx, b1c))["status"]
                fail += [] if (results.get(b1a) == "ok" and results.get(b1b) == "ok"
                               and str(results.get(b1c, "")).startswith("error")
                               and b1a_st == "approved" and b1b_st == "approved" and b1c_st == "rejected") \
                    else [("batch_approve did not approve both + error on terminal candidate",
                           results, b1a_st, b1b_st, b1c_st)]

                # batch_reject: thin loop over reject() too, same collected-errors contract
                r1 = stage(s, SUBJ, REL, "agent:BATCH-F", SNS, "human", now, batch_id="b3")
                rresults = batch_reject(s, "b3", now, "batch-reject-reason")
                r1_c = s.execute_read(lambda tx: _get(tx, r1))
                fail += [] if (rresults.get(r1) == "ok" and r1_c["status"] == "rejected"
                               and r1_c["review_reason"] == "batch-reject-reason") \
                    else [("batch_reject did not reject via existing reject()", rresults, r1_c)]

                # batch_promote: thin loop over promote() -> materializes an edge through apply_edge
                s.execute_write(lambda tx: mutate.resolve_entity(
                    tx, "Agent", "agent:BATCH-G", now, SNS, short="agent:BATCH-G", long_="agent:BATCH-G", ep="stg-ep"))
                p1 = stage(s, SUBJ, "HAS_STATUS", "agent:BATCH-G", SNS, "human", now, batch_id="b4")
                approve(s, p1, now)
                presults = batch_promote(s, "b4", now)
                st = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, "HAS_STATUS", "agent:BATCH-G", SNS))
                fail += [] if (presults.get(p1) == "ok" and st is True) \
                    else [("batch_promote did not materialize the edge via existing promote()", presults, st)]
                # empty batch_id must refuse rather than operate graph-wide (bead c7u-style guard)
                for op, args in ((batch_approve, (now,)), (batch_reject, (now, "x")), (batch_promote, (now,))):
                    for bad in (None, ""):
                        try:
                            op(s, bad, *args)
                            fail.append((f"{op.__name__}(batch_id={bad!r}) did not raise",))
                        except ValueError:
                            pass
            finally:
                _clean(s, SNS)
    if fail:
        print("STAGE_BATCH_FAIL:", fail)
        sys.exit(1)
    print("STAGE_BATCH_OK")


def _fmt_candidate(c):
    """One aligned, human-scannable line. Namespace is called out explicitly (ns=...) since it's the
    blast-radius signal a reviewer must see before approving — 'shared' means every role reads it
    once promoted."""
    extra = ""
    if c.get("staged_at"):
        extra += f"  staged={c['staged_at']}"
    if c.get("review_reason"):
        extra += f"  reason={c['review_reason']!r}"
    # evidence/source are LLM-origin (low-trust) text rendered at the reviewer's trust-decision
    # moment — repr() them so ANSI/OSC escapes can't spoof the terminal line being reviewed.
    if c.get("evidence"):
        extra += f"  evidence={c['evidence']!r}"
    if c.get("source"):
        extra += f"  source={c['source']!r}"
    # s_key/rel/o_key are LLM-origin (propose_edge lets an agent set all three) — repr() them for the
    # same anti-spoof reason as evidence/source above: a crafted key can otherwise fake a column
    # (e.g. a spoofed "origin=human [approved]" suffix) in the reviewer's approval line.
    return (f"{c['cand_id'][:12]}  {c['status']:<9} ns={c['namespace']:<12} "
            f"{c['s_key']!r} -{c['rel']!r}-> {c['o_key']!r}  origin={c['origin']}{extra}")


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
        _selftest_batch()
    else:
        _cli(sys.argv[1:])
