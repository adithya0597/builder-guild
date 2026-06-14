"""FIX-ABSTAIN: the sufficiency x confidence abstain mechanism — the validated
B2 shape from CONTEXT_EVALS §0 (Sufficient Context, Google ICLR'25, paper-walked).

Decision (resolved 2026-06-04, hybrid): implement the mechanism NOW so the Stage-A gate has the
validated abstain SHAPE (not the harmful risky-claim proxy), but run it SUGGEST-ONLY (advisory,
never autonomous-acts) until the H2b golden-set calibration (G3) fits the logistic weights;
then grant a per-namespace lease and the mode becomes 'autonomous' for that role only.

Why never sufficiency ALONE: §0 finding — LLMs answer correctly 35-62% of the time even on
INSUFFICIENT context, so abstaining on low sufficiency alone *destroys* accuracy. The validated
mechanism combines sufficiency with self-confidence in a logistic and thresholds the output
(+5-10% selective accuracy over confidence-alone). A low-sufficiency-but-high-confidence claim
must therefore still ACT.

G3: CALIBRATED is now a per-namespace dict. Default all False. Roles from
scope.py ROLE_NAMESPACES. auto_revert() is REVOKE-ONLY — granting a lease is human-only.
"""
import math
import sys

# Stage-gate: per-namespace dict. Default all False. Roles: engineering, finance, operations,
# product, market, governance, shared. Granting a lease is HUMAN-ONLY — no code sets True.
# auto_revert() REVOKES only (sets False when below bar). Read via CALIBRATED.get(role, False).
CALIBRATED = {
    "engineering": False,
    "finance":     False,
    "operations":  False,
    "product":     False,
    "market":      False,
    "governance":  False,
    "shared":      False,
}

# PROVISIONAL weights — NOT calibrated. Placeholders with the right SHAPE; magnitudes are guesses
# flagged as uncalibrated until the H2b logistic fit on a per-CXO golden set (G3 / Stage B).
W_SUFFICIENCY = 2.0    # PROVISIONAL
W_CONFIDENCE = 2.0     # PROVISIONAL
BIAS = -1.5            # PROVISIONAL
TAU = 0.5              # PROVISIONAL selective-action threshold


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def selective_score(sufficiency, self_confidence):
    """Logistic combiner over BOTH signals — never sufficiency alone."""
    return _sigmoid(W_SUFFICIENCY * sufficiency + W_CONFIDENCE * self_confidence + BIAS)


def abstain_gate(sufficiency, self_confidence, role="shared"):
    """Returns {decision, mode, score, calibrated}. decision in {act, abstain};
    mode in {suggest, autonomous} (suggest = advisory, Stage A until calibrated for that role)."""
    is_cal = CALIBRATED.get(role, False)
    score = selective_score(sufficiency, self_confidence)
    return {
        "decision": "act" if score >= TAU else "abstain",
        "mode": "autonomous" if is_cal else "suggest",
        "score": round(score, 4),
        "calibrated": is_cal,
        "weights_provisional": not is_cal,
    }


def stage_a_decision(claims, action, sufficiency, self_confidence, role="shared"):
    """Compose: faithfulness HARD violations (unsupported/conflict/stale) gate FIRST and
    deterministically; otherwise the sufficiency x confidence logistic IS the selective
    abstain gate. The APC confidence-threshold (gate.py) is autonomous-AUTHORIZATION, which is
    moot in Stage A — everything here is advisory (mode=suggest) until calibrated for that role."""
    from gate import gate
    is_cal = CALIBRATED.get(role, False)
    mode = "autonomous" if is_cal else "suggest"
    hard = any(c["support_status"] == "UNSUPPORTED" or c.get("conflict") or c.get("stale")
               for c in claims)
    if hard:
        # gate() takes generator_self_confidence on 0..100; abstain uses 0..1 -> convert
        fstate, freason = gate(claims, action, self_confidence * 100, requery=lambda c: c)
        return {"final": fstate, "mode": mode, "via": "faithfulness", "reason": freason}
    if any(c["support_status"] == "PARTIAL" for c in claims):
        return {"final": "partial", "mode": mode, "via": "faithfulness"}
    ab = abstain_gate(sufficiency, self_confidence, role=role)   # clean claims -> selective gate
    return {"final": "pass" if ab["decision"] == "act" else "abstain", "mode": ab["mode"],
            "via": "sufficiency×confidence", "score": ab["score"]}


def execute(decision, action_fn):
    """Enforcement consumer — makes 'suggest-only' FUNCTIONAL, not just a label. An action is
    auto-executed ONLY when mode=='autonomous' (i.e. CALIBRATED for that role) AND final=='pass'.
    While suggest-only (uncalibrated), even a 'pass' is BLOCKED and routed to a human. This is
    the layer that enforces the gate — without it, mode='suggest' is just metadata."""
    if decision["mode"] != "autonomous":
        return {"executed": False, "routed_to": "human",
                "reason": f"suggest-only (uncalibrated); gate said '{decision['final']}' (advisory)"}
    if decision["final"] != "pass":
        return {"executed": False, "routed_to": "human", "reason": f"gate={decision['final']}"}
    return {"executed": True, "result": action_fn()}


def auto_revert(role, kappa, gain, kappa_bar=0.8, gain_bar=0.0):
    """Revoke-only lease enforcement. Sets CALIBRATED[role]=False when the sweep result falls
    below either bar. Granting (setting True) is HUMAN-ONLY — this function never sets True.
    Idempotent: calling on an already-False namespace is a no-op.

    Args:
        role:      namespace key (must be in CALIBRATED)
        kappa:     measured judge-human kappa from the sweep
        gain:      measured selective-accuracy gain (pp) from the sweep
        kappa_bar: revoke threshold (default 0.8); revoke if kappa < kappa_bar
        gain_bar:  revoke threshold (default 0.0); revoke if gain < gain_bar
    Returns:
        {"role": role, "revoked": bool, "reason": str}
    """
    if role not in CALIBRATED:
        return {"role": role, "revoked": False, "reason": f"unknown role {role!r}"}
    below = kappa < kappa_bar or gain < gain_bar
    if below and CALIBRATED[role]:
        CALIBRATED[role] = False
        reason = f"kappa={kappa:.3f}<{kappa_bar} or gain={gain:.3f}<{gain_bar} -> revoked"
        return {"role": role, "revoked": True, "reason": reason}
    reason = (f"kappa={kappa:.3f}>={kappa_bar} and gain={gain:.3f}>={gain_bar} -> no action"
              if not below else f"already False -> no-op")
    return {"role": role, "revoked": False, "reason": reason}


def demo():
    fail = []
    sup = lambda i: {"id": i, "support_status": "SUPPORTED", "stale": False, "conflict": False}
    routine = {"category": "routine", "reversible": True}

    # CALIBRATED must be a dict with all values False (no namespace has been granted a lease)
    all_false = all(v is False for v in CALIBRATED.values())
    print(f"[mode]    CALIBRATED is dict={isinstance(CALIBRATED, dict)} all_false={all_false}")
    fail += [] if (isinstance(CALIBRATED, dict) and all_false) \
        else ["CALIBRATED must be a dict with all values False (no lease granted yet)"]

    # THE KEY CASE: low sufficiency, HIGH confidence -> must ACT (not abstain). A sufficiency-alone
    # gate would wrongly abstain here; the combined logistic does not.
    g_low_suf_hi_conf = abstain_gate(sufficiency=0.2, self_confidence=0.9, role="engineering")
    g_suff_alone_would = "abstain" if 0.2 < 0.5 else "act"   # naive sufficiency-only gate
    print(f"[key]    sufficiency=0.2 confidence=0.9 -> {g_low_suf_hi_conf['decision']} "
          f"(score={g_low_suf_hi_conf['score']}) | sufficiency-ALONE would={g_suff_alone_would}")
    fail += [] if (g_low_suf_hi_conf["decision"] == "act" and g_suff_alone_would == "abstain") \
        else ["combined gate must NOT abstain on low-suff+high-conf (the §0 finding)"]

    # low + low -> abstain
    g_low_low = abstain_gate(0.2, 0.2, role="engineering")
    print(f"[abstain] sufficiency=0.2 confidence=0.2 -> {g_low_low['decision']} (score={g_low_low['score']})")
    fail += [] if g_low_low["decision"] == "abstain" else ["low+low should abstain"]

    # high + high -> act
    g_hi = abstain_gate(0.9, 0.9, role="engineering")
    print(f"[act]     sufficiency=0.9 confidence=0.9 -> {g_hi['decision']} (score={g_hi['score']})")
    fail += [] if g_hi["decision"] == "act" else ["high+high should act"]

    # SUGGEST-ONLY: mode is advisory + weights flagged provisional while no lease granted
    cal_eng = CALIBRATED.get("engineering", False)
    print(f"[mode]    calibrated[engineering]={cal_eng} -> mode={g_hi['mode']} weights_provisional={g_hi['weights_provisional']}")
    fail += [] if (g_hi["mode"] == "suggest" and g_hi["weights_provisional"] is True and cal_eng is False) \
        else ["Stage A must be suggest-only with provisional weights"]

    # COMPOSED with the faithfulness gate: a hard faithfulness violation still wins (faithfulness first)
    d1 = stage_a_decision([sup("c1")], routine, sufficiency=0.9, self_confidence=0.9, role="engineering")
    d2 = stage_a_decision([sup("c1")], routine, sufficiency=0.2, self_confidence=0.2, role="engineering")
    d3 = stage_a_decision([{"id": "c1", "support_status": "UNSUPPORTED", "stale": False, "conflict": False}],
                          routine, sufficiency=0.9, self_confidence=0.9, role="engineering")
    print(f"[compose] supported+suff/conf high -> {d1['final']} (mode={d1['mode']}, via {d1['via']})")
    print(f"[compose] supported+suff/conf low  -> {d2['final']} (mode={d2['mode']}, via {d2['via']})")
    print(f"[compose] UNSUPPORTED claim        -> {d3['final']} (mode={d3['mode']}, via {d3['via']})")
    fail += [] if (d1["final"] == "pass" and d2["final"] == "abstain" and d3["final"] == "abstain"
                   and d1["mode"] == "suggest") else ["composition wrong"]

    # ENFORCEMENT: a 'pass' decision must NOT auto-execute while suggest-only (uncalibrated).
    acted = {"ran": False}
    def do_action():
        acted["ran"] = True
        return "ACTION PERFORMED"
    res = execute(d1, do_action)          # d1 = pass, but mode=suggest (CALIBRATED[eng]=False)
    print(f"[enforce] pass-decision under suggest-only -> {res}")
    fail += [] if (res["executed"] is False and acted["ran"] is False and res["routed_to"] == "human") \
        else ["suggest-only did NOT block autonomous action (label-only, not enforced)"]

    if fail:
        print("FIX_ABSTAIN_FAIL:", fail); sys.exit(1)
    print("FIX_ABSTAIN_OK")


if __name__ == "__main__":
    demo()
