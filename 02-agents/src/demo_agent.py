"""The smallest correct agent: consume governed context, never own it.

Asks through serve() (the ONLY read path), acts only via the gate's decision, records an
action-audit row. Run with PYTHONPATH including 01-context/src and 02-agents/src, against the
demo graph (01-context/src/etl.py). Prints DEMO_AGENT_OK.
"""
import sys
from serve import serve
from fix_decision import record_decision, attach_outcome


def agent_step(question, role, action=None):
    """One agent turn: ask -> gated decision -> (maybe) act -> audit record."""
    r = serve(question, role, action=action)
    rec = record_decision(r)
    if r["executed"]:                       # only true when CALIBRATED and gate passed
        print(f"  [act]     executing on {r['primary']} (autonomous lease active)")
    elif r["decision"] in ("pass", "partial"):
        print(f"  [suggest] {r['primary']}: {r['presentable_facts'][:2]} -> routed to human "
              f"(mode={r['mode']})")
    else:
        print(f"  [abstain] {r['decision']}: insufficient/forbidden — no action proposed")
    return r, rec


def demo():
    fail = []
    # 1) an in-scope question. The decision depends on your seeded graph; the INVARIANT does not:
    #    while uncalibrated, the agent never auto-executes, whatever the gate said.
    r1, rec1 = agent_step("Who is issue ACME-2 assigned to?", "engineering")
    fail += [] if (r1.get("executed") is not True and r1.get("mode", "suggest") == "suggest") else \
        ["uncalibrated agent must never auto-execute"]

    # 2) a question outside the agent's role slice: expect abstention, zero leakage
    r2, _ = agent_step("What is the exact budget cap dollar amount?", "engineering")
    leaked = r2.get("trace", {}).get("isolation", {}).get("leaked", [])
    fail += [] if not leaked else [f"isolation leak: {leaked}"]

    # 3) the audit loop closes with a real outcome later — simulate one
    rec1 = attach_outcome(rec1, "good", "suggestion accepted by the human and resolved the issue")
    fail += [] if rec1["decision_quality"] == 1.0 else ["audit loop broken"]
    print(f"  [audit]   {rec1['action_id']}: faithfulness={rec1['faithfulness']} "
          f"outcome={rec1['outcome']} decision_quality={rec1['decision_quality']}")

    if fail:
        print("DEMO_AGENT_FAIL:", fail); sys.exit(1)
    print("DEMO_AGENT_OK")


if __name__ == "__main__":
    demo()
