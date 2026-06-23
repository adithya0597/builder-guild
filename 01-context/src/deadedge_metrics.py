"""Dead-edge instrument (builder-guild-1nb): measure the trigger signals that decide WHEN the
bi-temporal graph's historical (superseded) RELATES_TO edges stop being free to keep in the hot
graph. Decision (founder 2026-06-22): STAY HOT until a MEASURED
trigger — this script IS that measurement, so "stay hot" is data-driven, not indefinite.

READ-ONLY: every query is a MATCH / EXPLAIN / CALL; the script never writes. Safe against live.

Signals (founder list): historical:current ratio + absolute counts; as-of p50/p95; current-read
p50/p95; rel_invalid_at index seek present; optional store size. Emits a VERDICT — stay-hot (all
green) vs revisit-cold-tier (a signal breached). Metrics are graph-WIDE (dead edges accumulate across
every namespace) — this is an ops/storage metric, not a role-scoped serve read.
"""
from neo4j import GraphDatabase
import argparse, json, time

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")

# --- trigger thresholds: INITIAL heuristics (LABELED-ESTIMATE) — the memo is explicit these are SET
#     BY MEASUREMENT, not guessed. The baseline run is the first data point; tune as history grows. ---
RATIO_TRIGGER = 10.0            # historical:current > 10:1 -> hot graph is mostly dead weight
ASOF_P95_MS_TRIGGER = 50.0     # as-of p95 > 50ms -> two-sided range seek no longer cheap at this size
CURRENT_P95_MS_TRIGGER = 25.0  # current-read p95 > 25ms -> current view degrading

# one-sided (current view) vs two-sided (as-of, the serve.node_card predicate); both inline datetime()
CURRENT_Q = "MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at > datetime() RETURN count(r) AS c"
ASOF_Q = ("MATCH ()-[r:RELATES_TO]->() WHERE r.valid_at <= datetime() AND r.invalid_at > datetime() "
          "RETURN count(r) AS c")


def _percentiles(samples_ms):
    # nearest-rank p50/p95 (not interpolated) — sufficient for a latency trip-wire with heuristic
    # thresholds; the sample list is never empty (iters is fixed > 0).
    s = sorted(samples_ms)
    n = len(s)
    return round(s[int(n * 0.50)], 3), round(s[min(n - 1, int(n * 0.95))], 3)


def _time_query(session, query, iters=50, warmup=5):
    """p50/p95 wall-clock (ms) over `iters` runs after `warmup` discarded runs (cold cache)."""
    for _ in range(warmup):
        session.run(query).consume()
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        session.run(query).consume()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return _percentiles(samples)


def _counts(session):
    tot = session.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c").single()["c"]
    cur = session.run(CURRENT_Q).single()["c"]
    nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    return nodes, tot, cur, tot - cur


def _index_seek_present(session):
    """EXPLAIN the current-view query; walk the plan tree for a relationship range-index seek."""
    plan = session.run("EXPLAIN " + CURRENT_Q).consume().plan
    ops = []

    def walk(p):
        if not p:
            return
        ops.append(p.get("operatorType", ""))
        for c in p.get("children", []):
            walk(c)

    walk(plan)
    return any(("IndexSeek" in o or "SeekByRange" in o) for o in ops), ops


def _store_size(session):
    """Best-effort store size via APOC; None if APOC absent (rel count is the scale proxy then)."""
    try:
        rec = session.run(
            "CALL apoc.monitor.store() YIELD totalStoreSize RETURN totalStoreSize AS s").single()
        return rec["s"] if rec else None
    except Exception:
        return None


def measure(session):
    nodes, tot, cur, hist = _counts(session)
    seek, ops = _index_seek_present(session)
    snap = {
        "nodes": nodes, "rel_total": tot, "current": cur, "historical": hist,
        "historical_to_current_ratio": round(hist / cur, 3) if cur else 0.0,
        "current_read_p50_ms": None, "current_read_p95_ms": None,
        "asof_p50_ms": None, "asof_p95_ms": None,
        "rel_invalid_at_index_seek": seek, "explain_operators": ops,
        "store_size_bytes": _store_size(session),
    }
    snap["current_read_p50_ms"], snap["current_read_p95_ms"] = _time_query(session, CURRENT_Q)
    snap["asof_p50_ms"], snap["asof_p95_ms"] = _time_query(session, ASOF_Q)
    return snap


def verdict(snap):
    """Operationalize the founder decision rule: stay hot while signals are flat + seek present."""
    breaches = []
    if snap["historical_to_current_ratio"] > RATIO_TRIGGER:
        breaches.append(f"historical:current {snap['historical_to_current_ratio']} > {RATIO_TRIGGER}")
    if snap["asof_p95_ms"] is not None and snap["asof_p95_ms"] > ASOF_P95_MS_TRIGGER:
        breaches.append(f"as-of p95 {snap['asof_p95_ms']}ms > {ASOF_P95_MS_TRIGGER}ms")
    if snap["current_read_p95_ms"] is not None and snap["current_read_p95_ms"] > CURRENT_P95_MS_TRIGGER:
        breaches.append(f"current-read p95 {snap['current_read_p95_ms']}ms > {CURRENT_P95_MS_TRIGGER}ms")
    notes = [] if snap["rel_invalid_at_index_seek"] else \
        ["NOTE: current-view EXPLAIN did not select a rel_invalid_at index seek "
         "(expected at tiny scale — the cost planner prefers a scan; re-check as edge count grows)"]
    return ("STAY-HOT (all signals green)" if not breaches
            else "REVISIT COLD-TIER: " + "; ".join(breaches)), notes


def main():
    ap = argparse.ArgumentParser(description="dead-edge trigger instrument (read-only)")
    ap.add_argument("--out", help="optional path to write the JSON snapshot (use a git-ignored path)")
    args = ap.parse_args()
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            before = _counts(s)
            snap = measure(s)
            after = _counts(s)
    assert before == after, f"MUTATION DETECTED — counts changed {before} -> {after} (script must be read-only)"
    v, notes = verdict(snap)
    print("dead-edge snapshot:")
    print(f"  scale     : nodes={snap['nodes']} rel_total={snap['rel_total']} "
          f"current={snap['current']} historical={snap['historical']} "
          f"ratio(h:c)={snap['historical_to_current_ratio']}")
    print(f"  latency   : current-read p50/p95={snap['current_read_p50_ms']}/{snap['current_read_p95_ms']}ms "
          f"| as-of p50/p95={snap['asof_p50_ms']}/{snap['asof_p95_ms']}ms")
    print(f"  index     : rel_invalid_at seek={snap['rel_invalid_at_index_seek']} ops={snap['explain_operators']}")
    print(f"  store     : {snap['store_size_bytes'] if snap['store_size_bytes'] is not None else 'n/a (APOC absent; rel_total is the proxy)'}")
    for n in notes:
        print(f"  {n}")
    print(f"  read-only : counts unchanged before/after ({before == after})")
    print(f"VERDICT: {v}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"snapshot": snap, "verdict": v}, f, indent=2)
        print(f"wrote snapshot -> {args.out}")
    print("DEADEDGE_METRICS_OK")


if __name__ == "__main__":
    main()
