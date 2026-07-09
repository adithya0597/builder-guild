"""The smallest correct agent: consume governed context, never own it.

Asks through serve() (the ONLY read path), acts only via the gate's decision, records an
action-audit row. Run with PYTHONPATH including 01-context/src, 02-agents/src, 03-evals/src, against the
demo graph (01-context/src/etl.py). Prints DEMO_AGENT_OK.
"""
import os
import sys
# ox5: make the script self-contained — serve lives in 01-context/src; fix_decision/planner in 02-agents/src
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "01-context", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 02-agents/src (fix_decision, planner)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "03-evals", "src"))  # eval_planner's oz4 fixture
from neo4j import GraphDatabase
from serve import serve, URI, AUTH
from fix_decision import record_decision, attach_outcome
from planner import plan
from eval_planner import _seed_fixture, _cleanup_fixture   # oz4 reuse — zero `mutate.` in this file


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

    # 4) planner loop: a multi-step question must self-choose >=2 distinct retrievals AND
    #    actually ANSWER (genuine-answer gate, same as eval_planner.py demo) — not just stop.
    #    Self-seeds/tears-down its OWN transient 2-hop via eval_planner's oz4 fixture helpers
    #    (mirrors eval_planner.demo(), eval_planner.py:390-397, exactly): the live ACME graph has
    #    0 SPI-* nodes, so a bare plan() call with no seeding always abstains. Reusing the proven
    #    fixture (not re-deriving it) is also what keeps this file free of any `mutate.` reference.
    QUESTION = "what blocks SPI-6 and who is it assigned to"
    drv = GraphDatabase.driver(URI, auth=AUTH)
    try:
        _cleanup_fixture(drv)              # drop any stale prior fixture first
        _seed_fixture(drv)                 # oz4 self-owned transient 2-hop
        rp = plan(QUESTION, "engineering", max_steps=4)
    finally:
        _cleanup_fixture(drv)              # always tear down, even on assertion error
        drv.close()
    p = rp["planner"]
    p_final = p["steps"][-1]["confidence_signal"]["decision"] if p["steps"] else "abstain"
    p_iso = all(s["isolation_clean"] for s in p["steps"])
    # RELEVANT-evidence gate (mirrors eval_planner.demo()): the asked relation is "who owns
    # the blocker" -> seeded answer is agent:cto via an ASSIGNED_TO edge. Require BOTH the
    # owner entity and the relation edge in the answer, not just any non-empty blob (codex M4).
    p_evidence = " ".join((rp.get("presentable_facts") or []) + (rp.get("composed_evidence") or []))
    p_relevant = ("agent:cto" in p_evidence) and ("ASSIGNED_TO" in p_evidence)
    p_answered = p_final in ("pass", "partial") and p_relevant
    fail += [] if (p["distinct_retrievals"] >= 2 and p["terminated_on"] == "confidence"
                   and p_answered and p_iso) else \
        [f"planner: not a genuine multi-step answer (distinct={p['distinct_retrievals']} "
         f"terminated_on={p['terminated_on']!r} final={p_final!r} relevant={p_relevant} "
         f"iso_clean={p_iso})"]
    print(f"  [planner] steps_used={p['steps_used']} distinct_retrievals={p['distinct_retrievals']} "
          f"terminated_on={p['terminated_on']} final_decision={p_final} "
          f"relevant_evidence={p_relevant} (expect ASSIGNED_TO->agent:cto) iso_clean={p_iso}")

    if fail:
        print("DEMO_AGENT_FAIL:", fail); sys.exit(1)
    print("DEMO_AGENT_OK")


if __name__ == "__main__":
    demo()
