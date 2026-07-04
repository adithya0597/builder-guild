"""builder-guild-485: staging concurrency race test (approve/reject/promote).

Mirrors race_test.py's barrier pattern (ONE shared driver, one session() per thread, both threads
started together via threading.Barrier(2) for maximal contention) but exercises staging's
approve/reject/promote instead of raw mutate.apply_edge. One generic _race(fn_a, fn_b) runner,
invoked over TRIALS fresh candidates for 4 pairings:
  1. promote  vs promote   (GATES STAGING_RACE_OK — clause a)
  2. approve  vs reject    (GATES — clause b)
  3. approve  vs approve   (informational — extra coverage)
  4. promote  vs reject    (GATES — gtb-plan-v3 clause d, phantom-edge race closed)

Namespace "staging_race_test" is disjoint from race_test.py's "race_test" and staging.py's
"_staging_selftest" — 3 sibling gates, 3 disjoint namespaces, safe to run concurrently.
Fresh object key per trial: cand_id = sha1(ns,s,rel,o,origin) (staging._cand_id), so a REUSED
o_key reuses cand_id, hits MERGE ON CREATE, and silently skips re-exercising the race.
"""
import sys
import threading

from neo4j import GraphDatabase

import cycle_check
import invariant_check
import mutate
from staging import AUTH, URI, approve, promote, reject, stage

NS = "staging_race_test"
SUBJ = "stgrace:iss"
REL = "ASSIGNED_TO"
REL5 = "RELATED_TO"      # arity:inf (Entity->Entity) — apply_edge takes NO subject _wlock for this
T = "2026-07-01T00:00:00Z"
TRIALS = 10


def _race(fn_a, fn_b):
    """Run fn_a/fn_b concurrently, synchronized at a 2-party barrier for maximal contention.
    Returns (results, errors) — 2-lists indexed [a, b]; a slot holds None if that side raised
    (the exception goes to the matching slot of `errors` instead)."""
    barrier = threading.Barrier(2)
    results, errors = [None, None], [None, None]

    def _run(i, fn):
        barrier.wait()
        try:
            results[i] = fn()
        except Exception as e:
            errors[i] = e

    threads = [threading.Thread(target=_run, args=(0, fn_a)), threading.Thread(target=_run, args=(1, fn_b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def _edge_count(tx, o_key, rel=REL):
    return tx.run("MATCH (s:Entity {key:$s})-[r:RELATES_TO {name:$rel}]->(o:Entity {key:$o}) "
                  "RETURN count(r) AS c", s=SUBJ, rel=rel, o=o_key).single()["c"]


def _cand_status(tx, cand_id):
    return tx.run("MATCH (c:Candidate {cand_id:$id}) RETURN c.status AS s", id=cand_id).single()["s"]


def _stage_pending(drv, o_key):
    """scenario 2/3 setup: approve/reject never touch the graph, so the object never needs to
    be a materialized :Entity."""
    with drv.session() as s:
        return stage(s, SUBJ, REL, o_key, NS, "human", T)


def _stage_approved(drv, o_key, rel=REL):
    """scenario 1/4/5 setup: promote() needs a resolved object :Entity to succeed."""
    with drv.session() as s:
        cand_id = stage(s, SUBJ, rel, o_key, NS, "human", T)
        approve(s, cand_id, T)
        s.execute_write(lambda tx: mutate.resolve_entity(tx, "Agent", o_key, T, NS, short=o_key, long_=o_key))
    return cand_id


def scenario_promote_promote(drv, trial):
    o_key = f"stgrace:promote:{trial}"
    cand_id = _stage_approved(drv, o_key)

    def _promote():
        with drv.session() as s:
            return promote(s, cand_id, T)

    results, errors = _race(_promote, _promote)
    with drv.session() as s:
        edge = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, REL, o_key, NS))
        status = s.execute_read(lambda tx: _cand_status(tx, cand_id))
    return results, errors, edge, status


def scenario_promote_promote_arity_inf(drv, trial):
    """scenario 5: promote vs promote over an arity:inf relation (RELATED_TO) — GATES, same
    assertions as scenario 1. apply_edge's subject _wlock only fires for arity:1 relations
    (mutate.py `if functional and lock:`), so this is the one scenario that exercises promote()'s
    own Candidate-level _plock without help from that subject lock."""
    o_key = f"stgrace:relto:{trial}"
    cand_id = _stage_approved(drv, o_key, rel=REL5)

    def _promote():
        with drv.session() as s:
            return promote(s, cand_id, T)

    results, errors = _race(_promote, _promote)
    with drv.session() as s:
        edge = s.execute_read(lambda tx: mutate.edge_state(tx, SUBJ, REL5, o_key, NS))
        status = s.execute_read(lambda tx: _cand_status(tx, cand_id))
    return results, errors, edge, status


def scenario_approve_reject(drv, trial):
    o_key = f"stgrace:apprej:{trial}"
    cand_id = _stage_pending(drv, o_key)

    def _approve():
        with drv.session() as s:
            approve(s, cand_id, T)
            return "approved"

    def _reject():
        with drv.session() as s:
            reject(s, cand_id, "race-test", T)
            return "rejected"

    results, errors = _race(_approve, _reject)
    with drv.session() as s:
        status = s.execute_read(lambda tx: _cand_status(tx, cand_id))
        edges = s.execute_read(lambda tx: _edge_count(tx, o_key))
    return results, errors, status, edges


def scenario_approve_approve(drv, trial):
    o_key = f"stgrace:appapp:{trial}"
    cand_id = _stage_pending(drv, o_key)

    def _approve():
        with drv.session() as s:
            approve(s, cand_id, T)
            return "approved"

    results, errors = _race(_approve, _approve)
    with drv.session() as s:
        status = s.execute_read(lambda tx: _cand_status(tx, cand_id))
    return results, errors, status


def scenario_promote_reject(drv, trial):
    o_key = f"stgrace:promrej:{trial}"
    cand_id = _stage_approved(drv, o_key)

    def _promote():
        with drv.session() as s:
            return promote(s, cand_id, T)

    def _reject():
        with drv.session() as s:
            reject(s, cand_id, "race-test", T)
            return "rejected"

    results, errors = _race(_promote, _reject)
    with drv.session() as s:
        status = s.execute_read(lambda tx: _cand_status(tx, cand_id))
        edges = s.execute_read(lambda tx: _edge_count(tx, o_key))
    return results, errors, status, edges


def _tally(d, k):
    d[k] = d.get(k, 0) + 1


def _cleanup(drv):
    with drv.session() as s:
        s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))


def main():
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        try:
            _cleanup(drv)
            with drv.session() as s:
                s.execute_write(lambda tx: mutate.resolve_entity(tx, "Issue", SUBJ, T, NS, short=SUBJ, long_=SUBJ))

            # scenario 1: promote vs promote — GATES clause (a). Post-CAS-fix, the losing thread
            # either returns False (its read landed after the winner's commit -> early idempotent
            # no-op) or raises ValueError("...lost status race...") (its read landed before the
            # winner's commit, so it only discovers the loss at the CAS) — either is a valid loss;
            # any OTHER exception is a real bug.
            sums, lost_race = {}, 0
            for trial in range(TRIALS):
                results, errors, edge, status = scenario_promote_promote(drv, trial)
                won = sum(1 for r in results if r)
                _tally(sums, won)
                for e in errors:
                    if e is None:
                        continue
                    if isinstance(e, ValueError) and "lost status race" in str(e):
                        lost_race += 1
                    else:
                        fail.append(("s1 unexpected exception", trial, e))
                if won != 1:
                    fail.append(("s1 sum(returns) != 1", trial, results))
                if edge is not True or status != "promoted":
                    fail.append(("s1 edge/status mismatch", trial, edge, status))
            print(f"[s1 promote-vs-promote]  sum(returns) distribution over {TRIALS} trials: {sums}  "
                  f"loser-raised-'lost status race': {lost_race}/{TRIALS}")

            # scenario 2: approve vs reject — GATES gtb-plan-v3 clause (c). Lifecycle CAS
            # (builder-guild-gtb) makes reject dominate: its source set {pending, approved} is a
            # superset that includes approve's own outcome state, so reject now succeeds regardless
            # of ordering — final status is always 'rejected' and reject() never raises. Both
            # threads returning without exception is LEGAL (approve-then-reject legally serializes,
            # no lost update); do NOT assert sum(successes)==1 — both_succeeded stays tallied/
            # printed only, never gated.
            statuses, edges_seen, both_succeeded = {}, {}, 0
            for trial in range(TRIALS):
                results, errors, status, edges = scenario_approve_reject(drv, trial)
                _tally(statuses, status)
                _tally(edges_seen, edges)
                if errors[0] is None and errors[1] is None:
                    both_succeeded += 1
                if status != "rejected":
                    fail.append(("s2 final status != rejected", trial, status))
                if edges != 0:
                    fail.append(("s2 graph write leaked", trial, edges))
                if errors[0] is not None and not isinstance(errors[0], ValueError):
                    fail.append(("s2 approve() raised non-ValueError", trial, errors[0]))
                if errors[1] is not None:
                    fail.append(("s2 reject() raised (must never)", trial, errors[1]))
            print(f"[s2 approve-vs-reject]   status distribution over {TRIALS} trials: {statuses}  "
                  f"edges={edges_seen}  both_succeeded={both_succeeded}/{TRIALS}")

            # scenario 3: approve vs approve — informational only
            statuses3, errs3 = {}, []
            for trial in range(TRIALS):
                results, errors, status = scenario_approve_approve(drv, trial)
                _tally(statuses3, status)
                errs3 += [e for e in errors if e]
            print(f"[info] s3 approve-vs-approve status distribution: {statuses3}  errors={errs3}")

            # scenario 4: promote vs reject — GATES gtb-plan-v3 clause (d). Lifecycle CAS
            # (builder-guild-gtb) closes the phantom-edge race: promote's source is {approved} only
            # and reject's excludes 'promoted', so whichever fresh-reads second sees the other's
            # already-committed status and raises before writing anything — exactly one side
            # succeeds, the loser raises ValueError, and ('rejected', edges>=1) is unreachable.
            statuses4, edges4, errs4 = {}, {}, []
            for trial in range(TRIALS):
                results, errors, status, edges = scenario_promote_reject(drv, trial)
                _tally(statuses4, status)
                _tally(edges4, edges)
                errs4 += [e for e in errors if e]
                if (status, edges) not in (("promoted", 1), ("rejected", 0)):
                    fail.append(("s4 phantom edge", trial, status, edges))
                succeeded = sum(1 for e in errors if e is None)
                if succeeded != 1:
                    fail.append(("s4 not exactly-one-succeeded", trial, results, errors))
                for e in errors:
                    if e is not None and not isinstance(e, ValueError):
                        fail.append(("s4 loser raised non-ValueError", trial, e))
            print(f"[s4 promote-vs-reject]  status distribution over {TRIALS} trials: {statuses4}  "
                  f"current-edge-count: {edges4}  errors={errs4}")

            # scenario 5: promote vs promote over RELATED_TO (arity:inf) — GATES, same assertions
            # as s1. apply_edge's subject _wlock only fires for arity:1 (mutate.py), so this is the
            # scenario that proves promote()'s own Candidate-level _plock (not the subject lock)
            # is what serializes an arity:inf candidate's concurrent promotes.
            sums5, lost_race5 = {}, 0
            for trial in range(TRIALS):
                results, errors, edge, status = scenario_promote_promote_arity_inf(drv, trial)
                won = sum(1 for r in results if r)
                _tally(sums5, won)
                for e in errors:
                    if e is None:
                        continue
                    if isinstance(e, ValueError) and "lost status race" in str(e):
                        lost_race5 += 1
                    else:
                        fail.append(("s5 unexpected exception", trial, e))
                if won != 1:
                    fail.append(("s5 sum(returns) != 1", trial, results))
                if edge is not True or status != "promoted":
                    fail.append(("s5 edge/status mismatch", trial, edge, status))
            print(f"[s5 promote-vs-promote/RELATED_TO(arity:inf)]  sum(returns) distribution over {TRIALS} "
                  f"trials: {sums5}  loser-raised-'lost status race': {lost_race5}/{TRIALS}")

            with drv.session() as s:
                inv = [v for v in s.execute_read(invariant_check.check) if v["ns"] == NS]
                cyc = [v for v in s.execute_read(cycle_check.check) if v["ns"] == NS]
            if inv or cyc:
                fail.append(("invariant/cycle sweep violation", inv, cyc))
        finally:
            _cleanup(drv)
            with drv.session() as s:
                leftover = s.execute_read(lambda tx: tx.run(
                    "MATCH (n) WHERE n.namespace=$ns RETURN count(n) AS c", ns=NS).single()["c"])
            if leftover:
                fail.append(("hermeticity leak — nodes remain after cleanup", leftover))

    if fail:
        print("STAGING_RACE_FAIL:", fail)
        sys.exit(1)
    print("STAGING_RACE_OK")


if __name__ == "__main__":
    main()
