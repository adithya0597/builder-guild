"""EPIST: multi-source epistemics — weight sources by epistemic role, then
resolve cross-source conflicts STRUCTURALLY (by authority + bi-temporal validity, no LLM),
per HYBRID_RETRIEVAL_ARCHITECTURE PART 4.

Source epistemic roles (authority for a FACT claim):
  graph     = fact-authority  — the bi-temporal KB is the source of truth for a fact
  pageindex = prose-authority — authoritative for document prose, not for structured facts
  vector    = recall-only     — surfaces candidates; never authoritative on its own (a vector hit
                                is a lexical/semantic neighbor, which is why a stale chunk can
                                contradict the live graph)
Weights are per-ROLE tunable (different CXO slices can re-rank prose vs fact authority); a default
profile is provided. Conflict on a (subject,predicate) SLOT is resolved by: highest source
authority first, then bi-temporal validity (current > historical) — deterministic, auditable.
A genuine SAME-authority, both-current conflict is SURFACED, never silently picked.
"""
import sys

# default per-source authority for FACT claims; ROLE_WEIGHTS can override per CXO role
DEFAULT_AUTHORITY = {"graph": 1.0, "pageindex": 0.7, "vector": 0.3}
ROLE_WEIGHTS = {
    "engineering": {"graph": 1.0, "pageindex": 0.6, "vector": 0.3},   # facts dominate
    "comms":       {"graph": 0.8, "pageindex": 1.0, "vector": 0.4},   # prose dominates
    "_default":    DEFAULT_AUTHORITY,
}


def weights_for(role):
    return ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["_default"])


def resolve_slot(claims, role="_default"):
    """claims: [{source, slot, value, validity}] all for the SAME slot. Returns the resolution."""
    w = weights_for(role)
    distinct = {c["value"] for c in claims}
    if len(distinct) == 1:
        return {"slot": claims[0]["slot"], "value": next(iter(distinct)),
                "resolution": "agreement", "dropped": []}
    # conflict: rank by (authority, validity-current-first)
    ranked = sorted(claims, key=lambda c: (w.get(c["source"], 0.0),
                                           1 if c["validity"] == "current" else 0), reverse=True)
    top, runner = ranked[0], ranked[1]
    tie = (w.get(top["source"], 0.0) == w.get(runner["source"], 0.0)
           and top["validity"] == runner["validity"])
    if tie:
        return {"slot": top["slot"], "value": None, "resolution": "SURFACE_conflict",
                "candidates": [(c["source"], c["value"]) for c in ranked], "dropped": []}
    return {"slot": top["slot"], "value": top["value"], "winner": top["source"],
            "resolution": "structural",
            "dropped": [(c["source"], c["value"]) for c in ranked[1:]]}


def demo():
    fail = []
    role = "engineering"
    print(f"[weights] role={role!r} source authority: {weights_for(role)}")

    # CASE A — structural conflict: graph(fact-authority,current) vs vector(recall, stale chunk)
    status_claims = [
        {"source": "graph",     "slot": "issue:X.status", "value": "closed", "validity": "current"},
        {"source": "vector",    "slot": "issue:X.status", "value": "open",   "validity": "current"},
        {"source": "pageindex", "slot": "issue:X.status", "value": "open",   "validity": "current"},
    ]
    rA = resolve_slot(status_claims, role)
    print(f"[conflict] issue:X.status -> {rA['resolution']} value={rA['value']} "
          f"winner={rA.get('winner')} dropped={rA['dropped']}")
    fail += [] if (rA["resolution"] == "structural" and rA["value"] == "closed"
                   and rA["winner"] == "graph"
                   and ("vector", "open") in rA["dropped"]) else ["CASE A: graph must win structurally"]

    # CASE B — bi-temporal tiebreak: same source, current beats historical
    prio_claims = [
        {"source": "graph", "slot": "issue:X.priority", "value": "P2", "validity": "historical"},
        {"source": "graph", "slot": "issue:X.priority", "value": "P0", "validity": "current"},
    ]
    rB = resolve_slot(prio_claims, role)
    print(f"[conflict] issue:X.priority -> {rB['resolution']} value={rB['value']} dropped={rB['dropped']}")
    fail += [] if (rB["value"] == "P0" and ("graph", "P2") in rB["dropped"]) \
        else ["CASE B: current must beat historical"]

    # CASE C — genuine same-authority both-current conflict -> SURFACE, never silently pick
    dup = [
        {"source": "graph", "slot": "issue:Y.owner", "value": "alice", "validity": "current"},
        {"source": "graph", "slot": "issue:Y.owner", "value": "bob",   "validity": "current"},
    ]
    rC = resolve_slot(dup, role)
    print(f"[conflict] issue:Y.owner -> {rC['resolution']} candidates={rC.get('candidates')}")
    fail += [] if (rC["resolution"] == "SURFACE_conflict" and rC["value"] is None) \
        else ["CASE C: genuine conflict must surface, not auto-pick"]

    # CASE D — role re-weighting: for comms, prose(pageindex) outranks graph on a prose slot
    prose = [
        {"source": "graph",     "slot": "doc.tone", "value": "terse",   "validity": "current"},
        {"source": "pageindex", "slot": "doc.tone", "value": "detailed", "validity": "current"},
    ]
    rD_eng = resolve_slot(prose, "engineering")
    rD_comms = resolve_slot(prose, "comms")
    print(f"[role]    doc.tone eng->{rD_eng['value']} (graph) | comms->{rD_comms['value']} (pageindex)")
    fail += [] if (rD_eng["value"] == "terse" and rD_comms["value"] == "detailed") \
        else ["CASE D: per-role weighting not applied"]

    print("LLM calls in conflict path: 0 (structural = authority + bi-temporal, deterministic)")
    if fail:
        print("EPIST_FAIL:", fail); sys.exit(1)
    print("EPIST_OK")


if __name__ == "__main__":
    demo()
