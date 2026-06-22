"""FIX-RECON: the per-card validity+freshness reconciliation rule, for the
S6 case a served node-card mixes per-NODE freshness (`dirty`) with per-EDGE validity
(`superseded`) — e.g. a clean node carrying one superseded fact among five current.

THE RULE (the two axes are ORTHOGONAL; never collapsed into one scalar):
  1. edge validity (current|historical) and node freshness (fresh|stale) are independent.
  2. a superseded fact NEVER marks its node stale  — node freshness is a property of node
     content (`dirty`), not of any one edge.
  3. a dirty node NEVER revalidates a superseded fact — validity is bi-temporal, not a vote.
  4. presentable  = current facts (superseded are QUARANTINED to an auditable list, not
     silently dropped).
  5. actionable   = current AND node-fresh (both axes must pass to act).
  6. the card stamp is a TUPLE {node_fresh, n_current, n_superseded, actionable} — there is
     no single "card confidence" number.
  7. a FUNCTIONAL (arity:1) relation showing >1 current edge is an upstream exactly-one-current
     breach (the sentinel + single-writer should make it impossible) — it is QUARANTINED to
     `ambiguous_functional` and the card is NEVER actionable while one exists.

Naming collision (the second half of S6): "confidence" named three different quantities.
They are now disambiguated everywhere (see RECALL_NAMING below + docs):
  retrieval_score          — evidence relevance from the retriever (was evidence.confidence)
  generator_self_confidence — the model's stated confidence in its own generation
  claim_faithfulness        — per-claim support-by-evidence (the §4 faithfulness score)
None of the three is called "confidence" unqualified.
"""
import sys
from collections import Counter

RECALL_NAMING = {
    "retrieval_score": "evidence relevance from the retriever [0,1] (was: evidence.confidence)",
    "generator_self_confidence": "the model's stated confidence in its own generation [0,1]",
    "claim_faithfulness": "per-claim support-by-evidence, the §4 faithfulness score [0,1]",
}


def reconcile(node_fresh, facts, functional_rels=frozenset()):
    """facts: [{fact, validity in {current,historical}}]. node_fresh in {fresh,stale}.
    functional_rels: relation names with arity:1 (ASSIGNED_TO, HAS_STATUS, PART_OF, ...); a
    functional relation with >1 current edge is an upstream exactly-one-current breach.
    Returns the reconciled card stamp keeping the two axes orthogonal."""
    current = [f for f in facts if f["validity"] == "current"]
    superseded = [f for f in facts if f["validity"] == "historical"]
    node_is_fresh = node_fresh == "fresh"
    # read-side invariant guard (defense-in-depth): the sentinel + single-writer make >1 current on
    # an arity:1 relation impossible; if one slips through we QUARANTINE it (never silently act).
    rel_counts = Counter(f["fact"].split(" -> ", 1)[0] for f in current)
    ambiguous_functional = sorted(r for r in functional_rels if rel_counts.get(r, 0) > 1)
    return {
        "node_fresh": node_fresh,                  # axis 1: node content freshness (unaffected by edges)
        "presentable": current,                    # axis 2: only current edges shown
        "superseded": superseded,                  # quarantined, retained for provenance/audit
        "n_current": len(current),
        "n_superseded": len(superseded),
        "ambiguous_functional": ambiguous_functional,  # arity:1 rels with >1 current (invariant breach)
        # actionable requires BOTH axes to pass AND no ambiguous functional edge; never a collapsed scalar
        "actionable": bool(current) and node_is_fresh and not ambiguous_functional,
    }


def demo():
    fail = []

    # CASE 1 (the S6 case): clean node, 1 superseded fact among 5
    facts5 = [{"fact": f"F{i}", "validity": "current"} for i in range(4)] + \
             [{"fact": "F_old", "validity": "historical"}]
    c1 = reconcile("fresh", facts5)
    print(f"[case1] clean node, 1 superseded among 5:")
    print(f"        node_fresh={c1['node_fresh']} n_current={c1['n_current']} "
          f"n_superseded={c1['n_superseded']} actionable={c1['actionable']}")
    print(f"        presentable={[f['fact'] for f in c1['presentable']]} "
          f"quarantined={[f['fact'] for f in c1['superseded']]}")
    # rule 2: the superseded fact did NOT mark the node stale; rule 4: 4 presentable, 1 quarantined
    fail += [] if (c1["node_fresh"] == "fresh" and c1["n_current"] == 4 and c1["n_superseded"] == 1
                   and "F_old" not in [f["fact"] for f in c1["presentable"]]
                   and c1["actionable"] is True) else ["case1: clean+superseded reconcile wrong"]

    # CASE 2: dirty node, all facts current — dirty must NOT revalidate, but blocks action
    facts_clean = [{"fact": f"G{i}", "validity": "current"} for i in range(3)]
    c2 = reconcile("stale", facts_clean)
    print(f"[case2] dirty node, all-current facts: node_fresh={c2['node_fresh']} "
          f"n_current={c2['n_current']} actionable={c2['actionable']}")
    # rule 3+5: facts still presentable, but not actionable because node is stale
    fail += [] if (c2["n_current"] == 3 and c2["actionable"] is False
                   and len(c2["presentable"]) == 3) else ["case2: dirty-node reconcile wrong"]

    # CASE 3: dirty node + a superseded fact — both axes degrade INDEPENDENTLY
    c3 = reconcile("stale", facts5)
    print(f"[case3] dirty node + superseded fact: node_fresh={c3['node_fresh']} "
          f"n_current={c3['n_current']} n_superseded={c3['n_superseded']} actionable={c3['actionable']}")
    fail += [] if (c3["node_fresh"] == "stale" and c3["n_current"] == 4
                   and c3["n_superseded"] == 1 and c3["actionable"] is False) \
        else ["case3: independent-axis degrade wrong"]

    # CASE 4 (read-side guard): a functional relation with 2 current edges is QUARANTINED, not actionable
    facts_amb = [{"fact": "ASSIGNED_TO -> agent:a", "validity": "current"},
                 {"fact": "ASSIGNED_TO -> agent:b", "validity": "current"}]
    c4 = reconcile("fresh", facts_amb, functional_rels={"ASSIGNED_TO"})
    print(f"[case4] functional ASSIGNED_TO with 2 current: ambiguous={c4['ambiguous_functional']} "
          f"actionable={c4['actionable']} (expect breach flagged, not actionable)")
    fail += [] if (c4["ambiguous_functional"] == ["ASSIGNED_TO"] and c4["actionable"] is False) \
        else ["case4: functional >1-current guard not enforced"]

    # naming: three disambiguated names, none is bare "confidence"
    print(f"[naming] disambiguated recall names: {list(RECALL_NAMING)}")
    fail += [] if ("confidence" not in RECALL_NAMING and len(RECALL_NAMING) == 3
                   and "retrieval_score" in RECALL_NAMING
                   and "claim_faithfulness" in RECALL_NAMING) else ["naming not disambiguated"]

    if fail:
        print("FIX_RECON_FAIL:", fail); sys.exit(1)
    print("FIX_RECON_OK")


if __name__ == "__main__":
    demo()
