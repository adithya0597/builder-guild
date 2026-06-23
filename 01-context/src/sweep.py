"""G1-sweep (the Freshness epic) + the FIX-STALE (the Freshness epic) sweep liveness monitor.

A content edit sets n.dirty=true (mutate.mark_dirty). A lazy, batched sweep re-embeds the dirty
nodes (Grunt-tier model = the same local EmbeddingGemma) and clears the flag. The sweep is
0-HOP: it re-embeds ONLY the edited node, never neighbors — because embeddings here are
INTRINSIC-CONTENT only (no GraphSAGE-style neighbour aggregation), so an edge change cannot
alter a neighbour's vector. (This is the FIX-STALE 0-hop-vs-1-hop resolution, documented in
ONTOLOGY_SCHEMA §11.)

sweep_queue_depth() is the FIX-STALE liveness monitor: it emits the re-embed backlog as a metric
and raises an alarm above a threshold, so cold dirty nodes can't silently rot.
"""
import sys
from neo4j import GraphDatabase

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
QUEUE_ALARM_THRESHOLD = 1000   # dirty backlog above this -> alarm (sweep falling behind)


def sweep_queue_depth(drv):
    """FIX-STALE liveness metric: count of dirty (re-embed-pending) nodes + alarm flag."""
    with drv.session() as s:
        n = s.run("MATCH (n:Entity) WHERE n.dirty=true RETURN count(n) AS c").single()["c"]
    metric = {"metric": "reembed_queue_depth", "value": n, "alarm": n > QUEUE_ALARM_THRESHOLD}
    print(f"[monitor] {metric['metric']}={metric['value']} alarm={metric['alarm']}")
    return metric


def sweep_once(drv, now, batch=100):
    """Re-embed up to `batch` dirty nodes (0-hop). Returns the keys swept."""
    from embed import embed_node
    with drv.session() as s:
        dirty = s.run(
            "MATCH (n:Entity) WHERE n.dirty=true "
            "RETURN n.key AS k, n.long_context AS c, coalesce(n.chunk_kind,'prose') AS kind "
            "LIMIT $b", b=batch).data()
        for d in dirty:
            s.execute_write(lambda tx, d=d: embed_node(tx, d["k"], d["c"], d["kind"], now))
    return [d["k"] for d in dirty]


def demo():
    from mutate import resolve_entity, mark_dirty, apply_edge
    from embed import embed_node
    NS, T0, T1 = "sweep_test", "2026-06-04T00:00:00Z", "2026-06-04T01:00:00Z"
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))
            # A = edited node ; B = neighbour (A-[:RELATES_TO]->B) to prove 0-hop
            s.execute_write(lambda tx: resolve_entity(tx, "Episodic", "sw:A", T0, NS, short="A", long_="initial content about caching"))
            s.execute_write(lambda tx: resolve_entity(tx, "Episodic", "sw:B", T0, NS, short="B", long_="neighbour about logging"))
            s.execute_write(lambda tx: embed_node(tx, "sw:A", "initial content about caching", "prose", T0))
            s.execute_write(lambda tx: embed_node(tx, "sw:B", "neighbour about logging", "prose", T0))
            # crk/n3y: route the fixture edge through the single write engine (apply_edge) with an
            # EXPLICIT clock T0 — no handwritten current-edge write, no ambient datetime() (was the 2nd clock-split).
            s.execute_write(lambda tx: apply_edge(tx, "sw:A", "RELATED_TO", "sw:B", T0, NS))

            before = s.run("MATCH (n:Entity{key:'sw:A'}) RETURN n.embedding AS v, n.content_rev AS cr, n.embedded_content_rev AS ecr").single()
            b_before = s.run("MATCH (n:Entity{key:'sw:B'}) RETURN n.embedded_at AS at, n.embedding AS v").single()

            # CONTENT EDIT on A: new content + mark dirty (content_rev bumps, dirty=true)
            s.execute_write(lambda tx: tx.run("MATCH (n:Entity{key:'sw:A'}) SET n.long_context=$c",
                                              c="rewritten content about distributed consensus"))
            s.execute_write(lambda tx: mark_dirty(tx, "sw:A", T1))

            q_before = sweep_queue_depth(drv)                      # FIX-STALE monitor: 1 pending
            dirty_state = s.run("MATCH (n:Entity{key:'sw:A'}) RETURN n.dirty AS d, n.content_rev AS cr").single()

            swept = sweep_once(drv, T1)                            # lazy batched re-embed

            after = s.run("MATCH (n:Entity{key:'sw:A'}) RETURN n.embedding AS v, n.dirty AS d, n.content_rev AS cr, n.embedded_content_rev AS ecr").single()
            b_after = s.run("MATCH (n:Entity{key:'sw:B'}) RETURN n.embedded_at AS at, n.embedding AS v").single()
            q_after = sweep_queue_depth(drv)                       # 0 pending after sweep
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))

    vec_changed = before["v"] != after["v"]
    b_untouched = (b_before["at"] == b_after["at"] and b_before["v"] == b_after["v"])
    print(f"[edit]    sw:A content_rev {before['cr']}->{dirty_state['cr']} dirty={dirty_state['d']} (was embedded_rev {before['ecr']})")
    print(f"[sweep]   swept={swept} | A.embedding changed={vec_changed} dirty_now={after['d']} embedded_rev_now={after['ecr']} (==content_rev {after['cr']})")
    print(f"[0-hop]   neighbour sw:B re-embedded? {not b_untouched}  (must be False — intrinsic embeddings, 0-hop)")
    print(f"[monitor] queue depth {q_before['value']} -> {q_after['value']}")

    fail += [] if dirty_state["d"] is True and dirty_state["cr"] == before["cr"] + 1 else ["edit did not set dirty/bump rev"]
    fail += [] if swept == ["sw:A"] else [f"sweep wrong set: {swept}"]
    fail += [] if vec_changed else ["vector not updated by sweep"]
    fail += [] if after["d"] is False and after["ecr"] == after["cr"] else ["dirty not cleared / rev not synced"]
    fail += [] if b_untouched else ["0-hop violated: neighbour re-embedded"]
    fail += [] if q_before["value"] == 1 and q_after["value"] == 0 else ["queue-depth metric wrong"]

    if fail:
        print("G1_SWEEP_FAIL:", fail); sys.exit(1)
    print("G1_SWEEP_OK")


if __name__ == "__main__":
    demo()
