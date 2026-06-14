"""GATE: faithfulness + APC decision/action gate -> pass | partial | abstain |
escalate. Ports the ai-product-council governance engine (VoteCalculator / DecisionRouter /
SycophancyDetector — "pure logic, zero model deps") per HYBRID_RETRIEVAL_ARCHITECTURE §4.

Inputs per request:
  claims: [{id, support_status in {SUPPORTED,PARTIAL,UNSUPPORTED}, stale:bool, conflict:bool}]
          (support_status from the §4 faithfulness contract; stale from F4-stamp; conflict from EPIST)
  action: {category in {routine,architectural,security,irreversible}, reversible:bool}
  generator_self_confidence: 0..100  (the disambiguated name — FIX-RECON)

Decision order (faithfulness BEFORE confidence — no citation, no claim):
  1. UNSUPPORTED claim -> one CRAG requery; if still unsupported it is a hard violation.
  2. hard violation (unsupported | conflict | stale) feeding the action:
        irreversible/security/non-reversible -> ESCALATE (human) ; else -> ABSTAIN.
  3. PARTIAL support, no hard violation:
        low-impact reversible -> PARTIAL (answer partial, action withheld) ; else -> ESCALATE.
  4. all SUPPORTED, clean:
        category in {security, irreversible} -> ESCALATE  (mandatory human auditor, regardless
            of confidence — the reversibility rule: irreversible/outward-facing = hard stop)
        elif confidence >= impact-scaled threshold -> PASS ; else -> ESCALATE.
"""
import sys

THRESHOLD = {"routine": 0.50, "architectural": 0.67, "security": 0.80, "irreversible": 0.90}
CATEGORICAL_HUMAN = {"security", "irreversible"}   # mandatory human auditor regardless of confidence


def gate(claims, action, generator_self_confidence, requery=None):
    cat = action["category"]
    reversible = action["reversible"]
    conf = generator_self_confidence / 100.0
    thr = THRESHOLD[cat]

    # 1. one CRAG requery on each unsupported claim (caller-supplied; identity = requery failed)
    if requery:
        claims = [requery(c) if c["support_status"] == "UNSUPPORTED" else c for c in claims]

    unsupported = [c for c in claims if c["support_status"] == "UNSUPPORTED"]
    conflicted = [c for c in claims if c.get("conflict")]
    stale = [c for c in claims if c.get("stale")]
    partial = [c for c in claims if c["support_status"] == "PARTIAL"]
    hard = unsupported or conflicted or stale

    # 2. hard faithfulness violation feeding the action
    if hard:
        reason = (f"unsupported={[c['id'] for c in unsupported]} "
                  f"conflict={[c['id'] for c in conflicted]} stale={[c['id'] for c in stale]}")
        if cat in CATEGORICAL_HUMAN or not reversible:
            return "escalate", f"hard violation on risky action ({cat}): {reason}"
        return "abstain", f"hard violation, reversible low-risk: {reason}"

    # 3. partial support, no hard violation
    if partial:
        if reversible and cat == "routine":
            return "partial", f"partial support {[c['id'] for c in partial]}; action withheld"
        return "escalate", f"partial support feeding {cat} action -> human"

    # 4. all SUPPORTED, clean
    if cat in CATEGORICAL_HUMAN:
        return "escalate", f"{cat} = categorical hard-stop: mandatory human auditor (conf={conf:.2f} ignored)"
    if conf >= thr:
        return "pass", f"all supported, conf {conf:.2f} >= {cat} threshold {thr:.2f}"
    return "escalate", f"conf {conf:.2f} < {cat} threshold {thr:.2f}"


def demo():
    fail = []
    sup = lambda i: {"id": i, "support_status": "SUPPORTED", "stale": False, "conflict": False}

    cases = [
        # (name, claims, action, conf, expected_state)
        ("PASS routine supported",
         [sup("c1"), sup("c2")], {"category": "routine", "reversible": True}, 85, "pass"),
        ("PARTIAL low-risk",
         [sup("c1"), {"id": "c2", "support_status": "PARTIAL", "stale": False, "conflict": False}],
         {"category": "routine", "reversible": True}, 90, "partial"),
        ("ABSTAIN unsupported reversible (requery fails)",
         [sup("c1"), {"id": "c2", "support_status": "UNSUPPORTED", "stale": False, "conflict": False}],
         {"category": "routine", "reversible": True}, 90, "abstain"),
        ("ESCALATE irreversible even if supported",
         [sup("c1")], {"category": "irreversible", "reversible": False}, 99, "escalate"),
        ("ESCALATE conflict feeding security action",
         [{"id": "c1", "support_status": "SUPPORTED", "stale": False, "conflict": True}],
         {"category": "security", "reversible": False}, 95, "escalate"),
        ("ESCALATE stale fact feeding architectural action",
         [{"id": "c1", "support_status": "SUPPORTED", "stale": True, "conflict": False}],
         {"category": "architectural", "reversible": True}, 80, "abstain"),
        ("ESCALATE low confidence vs architectural threshold",
         [sup("c1")], {"category": "architectural", "reversible": True}, 60, "escalate"),
    ]
    # requery that fails to find support (identity) — models a genuine unsupported claim
    requery_fail = lambda c: c
    for name, claims, action, conf, expected in cases:
        state, reason = gate(claims, action, conf, requery=requery_fail)
        ok = state == expected
        print(f"[{'OK ' if ok else 'XX '}] {state:<8} (exp {expected:<8}) {name}")
        print(f"         -> {reason}")
        fail += [] if ok else [f"{name}: got {state} exp {expected}"]

    # all four output states must have been exercised
    produced = {gate(c, a, cf, requery=requery_fail)[0] for _, c, a, cf, _ in cases}
    fail += [] if {"pass", "partial", "abstain", "escalate"} <= produced else ["not all 4 states produced"]
    print(f"states produced: {sorted(produced)}")

    if fail:
        print("GATE_FAIL:", fail); sys.exit(1)
    print("GATE_OK")


if __name__ == "__main__":
    demo()
