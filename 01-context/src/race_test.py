"""FIX-RACE (the Context-Engineering epic): prove per-subject write-lock serialization gives exactly ONE
current functional edge under concurrent re-ingest.

Two threads concurrently apply ASSIGNED_TO for the SAME subject to DIFFERENT agents, started
together at a barrier. Without the lock the supersede->create read-then-write gap can leave
TWO current edges; with the lock the writers serialize -> exactly one current (last committer
wins, the other is superseded). Runs N trials each way and reports the distribution.
"""
import sys
import threading
from neo4j import GraphDatabase
from mutate import URI, AUTH, resolve_entity, apply_edge, current_targets

TNS = "race_test"
T = "2026-06-04T00:00:00Z"
TRIALS = 25


def seed(tx):
    for k, lbl in [("race:iss", "Issue"), ("race:a", "Agent"), ("race:b", "Agent")]:
        resolve_entity(tx, lbl, k, T, TNS, short=k, long_=k)
    # wipe any prior edges so each trial starts edge-free (the worst case for the race)
    tx.run("MATCH (:Entity {key:'race:iss'})-[r:RELATES_TO]->() DELETE r")


def cleanup(tx):
    tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=TNS)


def writer(drv, target, barrier, use_lock, errors):
    barrier.wait()  # both threads cross together -> maximal contention
    try:
        with drv.session() as s:
            s.execute_write(lambda tx: apply_edge(
                tx, "race:iss", "ASSIGNED_TO", target, T, TNS, ep="race-ep", lock=use_lock))
    except Exception as e:
        # the driver auto-retries transient deadlocks, so anything reaching here is UNEXPECTED.
        # record it (do NOT swallow) so a hidden failure can't masquerade as a passing run.
        errors.append(f"{target}: {type(e).__name__}: {str(e)[:80]}")


def run(use_lock):
    counts, errors = {}, []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(cleanup)
        for _ in range(TRIALS):
            with drv.session() as s:
                s.execute_write(seed)
            barrier = threading.Barrier(2)
            ts = [threading.Thread(target=writer, args=(drv, t, barrier, use_lock, errors))
                  for t in ("race:a", "race:b")]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            with drv.session() as s:
                n_cur = len(s.execute_read(current_targets, "race:iss", "ASSIGNED_TO"))
            counts[n_cur] = counts.get(n_cur, 0) + 1
        with drv.session() as s:
            s.execute_write(cleanup)
    return counts, errors


def main():
    fail = []
    nolock, nl_err = run(use_lock=False)
    locked, lk_err = run(use_lock=True)
    print(f"[no-lock] current-edge-count distribution over {TRIALS} concurrent trials: {nolock}  errors={nl_err}")
    print(f"[locked ] current-edge-count distribution over {TRIALS} concurrent trials: {locked}  errors={lk_err}")
    ok_lock = set(locked) == {1}
    race_seen = max(nolock) > 1
    print(f"locked-always-exactly-one={ok_lock} | no-lock-demonstrated-double={race_seen}")
    # 1) the lock must guarantee exactly-one current edge, every trial
    if not ok_lock:
        fail.append("lock did not guarantee exactly-one current edge")
    # 2) NO unexpected errors anywhere — a swallowed error must not mask a failure (codex #7)
    if lk_err or nl_err:
        fail.append(f"unexpected writer errors (locked={lk_err}, no-lock={nl_err})")
    # 3) the no-lock race must ACTUALLY manifest — else the test proved nothing about the race
    if not race_seen:
        fail.append("no-lock race did not manifest; test did not demonstrate the race it claims")
    if fail:
        print("FIX_RACE_FAIL:", fail); sys.exit(1)
    print("FIX_RACE_OK")


if __name__ == "__main__":
    main()
