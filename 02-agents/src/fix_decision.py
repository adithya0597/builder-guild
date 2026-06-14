"""FIX-DECISION: the decision-outcome / action-audit loop — the gate that closes
proxy→objective. CONTEXT_EVALS §0/§1 dim 10: FAITHFULNESS (every answer claim is grounded in a
retrieved unit) does NOT imply DECISION QUALITY (the gated action led to a good outcome). A system
can be perfectly faithful to its context and still drive a bad decision (the context was sufficient
+ grounded but the ACTION was wrong for the goal). Faithfulness is a proxy; decision quality is the
objective. This loop records the gated action, attaches the realized outcome, and measures the GAP.

End-to-end on a REAL sample: one live serve() call → record → attach outcome → audit. Then a small
illustrative set proves the proxy gap (faithful-but-bad-outcome).

HONEST SCOPE: there is no real downstream-outcome telemetry yet — outcomes here are MOCK-labelled.
This module is the SEAM where real outcomes get recorded (e.g. 'the action the agent took after this
answer was later reverted / succeeded'); the calibration that uses it is H2b/Stage-B. It does not
gate serve() and does not flip CALIBRATED.
"""
import sys
from serve import serve


def record_decision(serve_result):
    """Capture the audit-relevant fields from a real serve() output. faithfulness = proxy
    (are grounded/presentable facts present), distinct from the not-yet-known outcome."""
    facts = serve_result.get("presentable_facts", [])
    return {
        "action_id": f"{serve_result.get('role')}::{serve_result.get('primary')}",
        "query": serve_result.get("query"),
        "decision": serve_result.get("decision"),
        "executed": serve_result.get("executed"),
        "faithfulness": 1.0 if facts else 0.0,    # PROXY (grounded facts present)
        "outcome": "pending",                       # objective — unknown until observed
        "decision_quality": None,
    }


def attach_outcome(record, outcome, rationale):
    """Record the realized outcome (the OBJECTIVE). outcome in {good, bad}. decision_quality is
    derived from the outcome, NOT from faithfulness — that independence is the whole point."""
    assert outcome in ("good", "bad"), outcome
    record = dict(record)
    record["outcome"] = outcome
    record["decision_quality"] = 1.0 if outcome == "good" else 0.0
    record["outcome_rationale"] = rationale
    return record


def audit(records):
    """Aggregate faithfulness vs decision-quality and surface the proxy gap per record."""
    done = [r for r in records if r["outcome"] != "pending"]
    fmean = sum(r["faithfulness"] for r in done) / len(done) if done else 0.0
    dmean = sum(r["decision_quality"] for r in done) / len(done) if done else 0.0
    # the cases that prove faithfulness != decision quality
    faithful_but_bad = [r["action_id"] for r in done if r["faithfulness"] >= 0.5 and r["decision_quality"] == 0.0]
    unfaithful_but_good = [r["action_id"] for r in done if r["faithfulness"] < 0.5 and r["decision_quality"] == 1.0]
    return {"n": len(done), "faithfulness_mean": round(fmean, 3),
            "decision_quality_mean": round(dmean, 3), "proxy_gap": round(abs(fmean - dmean), 3),
            "faithful_but_bad": faithful_but_bad, "unfaithful_but_good": unfaithful_but_good}


def demo():
    fail = []

    # 1) END-TO-END ON A REAL SAMPLE ACTION (the acceptance criterion)
    res = serve("rate limit backoff for the inference client", "engineering")
    rec = record_decision(res)
    rec = attach_outcome(rec, "good", "the backoff fix referenced by the answer resolved the rate-limit incident")
    print(f"[real]    serve->record: action_id={rec['action_id']} decision={rec['decision']} "
          f"faithfulness={rec['faithfulness']} outcome={rec['outcome']} dq={rec['decision_quality']}")
    loop_ran = (rec["outcome"] in ("good", "bad") and rec["decision_quality"] in (0.0, 1.0)
                and rec["action_id"] and rec["decision"] in ("pass", "partial", "abstain", "escalate"))
    fail += [] if loop_ran else ["end-to-end loop did not run on the real sample action"]

    # 2) THE PROXY GAP: a faithful answer with a BAD outcome (faithfulness != decision quality)
    faithful_bad = attach_outcome(
        {"action_id": "engineering::issue:SPI-6", "query": "what should we ship next", "decision": "pass",
         "executed": False, "faithfulness": 1.0, "outcome": "pending", "decision_quality": None},
        "bad", "answer faithfully cited a BLOCKED issue as the next ship item -> wrong action for the goal")
    # an unfaithful answer that happened to yield a good outcome (the other half of the gap)
    unfaithful_good = attach_outcome(
        {"action_id": "engineering::issue:SPI-2", "query": "is the client patched", "decision": "abstain",
         "executed": False, "faithfulness": 0.0, "outcome": "pending", "decision_quality": None},
        "good", "abstained (no grounded fact) but abstaining WAS the correct action -> good outcome")
    rep = audit([rec, faithful_bad, unfaithful_good])
    print(f"[audit]   {rep}")
    print(f"[gap]     faithfulness_mean={rep['faithfulness_mean']} vs decision_quality_mean="
          f"{rep['decision_quality_mean']} -> proxy_gap={rep['proxy_gap']}")
    # the loop must SURFACE both proxy-failure directions
    fail += [] if (rep["faithful_but_bad"] == ["engineering::issue:SPI-6"]
                   and rep["unfaithful_but_good"] == ["engineering::issue:SPI-2"]) else \
        ["audit failed to surface the faithfulness!=decision-quality cases"]

    if fail:
        print("FIX_DECISION_FAIL:", fail); sys.exit(1)
    print("FIX_DECISION_OK")


if __name__ == "__main__":
    demo()
