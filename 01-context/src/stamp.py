"""F4-stamp: retrieval-time validity + freshness stamping, a freshness judge
that drops superseded facts, and an action gate that refuses to act on stale/superseded facts.

READ-side only (no mutation). Extends serve.py's node-card so every fact carries:
  validity in {current, historical}  — current = edge.invalid_at IS NULL (bi-temporal)
  fresh    in {fresh, stale}         — stale = the card's source node is dirty (content changed,
                                       re-embed pending, PART 3-B) so recall may be out of date
The freshness judge drops historical facts; the action gate ALLOWS only current+fresh, else REFUSE.

Naming note (coordinated with FIX-RECON): `validity` and `fresh` are the two ORTHOGONAL
axes of a fact's trustworthiness — a fact can be current-but-stale (node edited, edge still valid)
or historical-but-clean. They are never collapsed into one "confidence" scalar.
"""
import sys
from neo4j import GraphDatabase

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")

# one node-card: the source node's dirty flag + every outgoing fact's bi-temporal validity
CARD_Q = """
MATCH (i:Entity {key:$key}) WHERE i.namespace IN $allowed
OPTIONAL MATCH (i)-[r:RELATES_TO]->(o:Entity)
  WHERE r.namespace IN $allowed AND o.namespace IN $allowed   // target must ALSO be in-scope (no leak)
RETURN coalesce(i.dirty,false) AS node_dirty,
  [x IN collect(CASE WHEN r IS NULL THEN NULL ELSE {
     fact: r.name + ' -> ' + o.key,
     validity: CASE WHEN r.invalid_at IS NULL THEN 'current' ELSE 'historical' END
   } END) WHERE x IS NOT NULL] AS facts
"""


def stamp_card(rec):
    """Add a {validity, fresh} stamp to each fact. fresh derives from the node's dirty flag."""
    fresh = "stale" if rec["node_dirty"] else "fresh"
    return [{**f, "fresh": fresh} for f in rec["facts"]]


def freshness_judge(stamped):
    """Drop superseded facts — only current-validity facts reach the action layer."""
    return [f for f in stamped if f["validity"] == "current"]


def action_gate(fact):
    """Refuse to act on anything not current AND fresh. Returns (decision, reason)."""
    if fact["validity"] != "current":
        return "REFUSE", f"superseded ({fact['validity']})"
    if fact["fresh"] != "fresh":
        return "REFUSE", f"stale ({fact['fresh']} — node re-embed pending)"
    return "ALLOW", "current+fresh"


def card(key, allowed):
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        rec = s.run(CARD_Q, key=key, allowed=allowed).single()
        return stamp_card(rec) if rec else []


# ── demo / acceptance (isolated, self-cleaning) ──────────────────────────────
def demo():
    from mutate import resolve_entity, apply_edge, mark_dirty
    NS, T0, T1 = "stamp_test", "2026-06-04T00:00:00Z", "2026-06-04T01:00:00Z"
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))
            # S1: clean node — assignee current, status superseded (open->closed)
            for k, lbl in [("st:s1", "Issue"), ("st:ag", "Agent"),
                           ("st:open", "StatusValue"), ("st:closed", "StatusValue")]:
                s.execute_write(lambda tx, k=k, lbl=lbl: resolve_entity(tx, lbl, k, T0, NS, short=k, long_=k))
            s.execute_write(lambda tx: apply_edge(tx, "st:s1", "ASSIGNED_TO", "st:ag", T0, NS, "e1"))
            s.execute_write(lambda tx: apply_edge(tx, "st:s1", "HAS_STATUS", "st:open", T0, NS, "e1"))
            s.execute_write(lambda tx: apply_edge(tx, "st:s1", "HAS_STATUS", "st:closed", T1, NS, "e2"))  # supersede open
            # S2: dirty node (content edited, re-embed pending) — assignee current but STALE
            s.execute_write(lambda tx: resolve_entity(tx, "Issue", "st:s2", T0, NS, short="st:s2", long_="st:s2"))
            s.execute_write(lambda tx: apply_edge(tx, "st:s2", "ASSIGNED_TO", "st:ag", T0, NS, "e1"))
            s.execute_write(lambda tx: mark_dirty(tx, "st:s2", T1))

            # ISOLATION (codex round-2): an OUT-of-scope target must not surface in an in-scope card.
            # st:leak is in 'other_ns'; the BLOCKS edge is in-scope (NS) but its target is not.
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace='other_ns' DETACH DELETE n"))
            s.execute_write(lambda tx: resolve_entity(tx, "Issue", "st:leak", T0, "other_ns", short="leak", long_="leak"))
            s.execute_write(lambda tx: apply_edge(tx, "st:s1", "BLOCKS", "st:leak", T0, NS, "e1"))

            s1 = stamp_card(s.run(CARD_Q, key="st:s1", allowed=[NS]).single())
            s2 = stamp_card(s.run(CARD_Q, key="st:s2", allowed=[NS]).single())
            leaked = [f for f in s1 if "st:leak" in f["fact"]]
            print(f"[isolation] out-of-scope target st:leak in card? {bool(leaked)} (must be False)")
            fail += [] if not leaked else ["READ-SIDE LEAK: out-of-namespace target surfaced in card"]
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace IN [$ns,'other_ns'] DETACH DELETE n", ns=NS))

    print("[stamp]  S1 (clean) facts:")
    for f in sorted(s1, key=lambda x: x["fact"]):
        print(f"           {f['fact']:<32} validity={f['validity']:<10} fresh={f['fresh']}")
    print("[stamp]  S2 (dirty) facts:")
    for f in sorted(s2, key=lambda x: x["fact"]):
        print(f"           {f['fact']:<32} validity={f['validity']:<10} fresh={f['fresh']}")

    # every fact stamped on both axes
    fail += [] if all({"validity", "fresh"} <= set(f) for f in s1 + s2) else ["unstamped fact"]

    # freshness judge drops superseded
    kept = freshness_judge(s1)
    dropped = [f["fact"] for f in s1 if f not in kept]
    print(f"[judge]  S1 current-kept={[f['fact'] for f in kept]}")
    print(f"[judge]  S1 superseded-dropped={dropped}")
    fail += [] if any("st:open" in d for d in dropped) and all(f["validity"] == "current" for f in kept) \
        else ["judge did not drop superseded"]

    # action gate: ALLOW current+fresh, REFUSE superseded, REFUSE current+stale
    open_fact = next(f for f in s1 if "st:open" in f["fact"])
    assignee_clean = next(f for f in s1 if f["fact"].startswith("ASSIGNED_TO"))
    assignee_dirty = next(f for f in s2 if f["fact"].startswith("ASSIGNED_TO"))
    g_clean = action_gate(assignee_clean)
    g_super = action_gate(open_fact)
    g_stale = action_gate(assignee_dirty)
    print(f"[gate]   current+fresh  ASSIGNED_TO(S1)  -> {g_clean}")
    print(f"[gate]   superseded     HAS_STATUS=open  -> {g_super}")
    print(f"[gate]   current+stale  ASSIGNED_TO(S2)  -> {g_stale}")
    fail += [] if (g_clean[0] == "ALLOW" and g_super[0] == "REFUSE" and g_stale[0] == "REFUSE") \
        else ["action gate decision wrong"]

    if fail:
        print("F4_STAMP_FAIL:", fail); sys.exit(1)
    print("F4_STAMP_OK")


if __name__ == "__main__":
    demo()
