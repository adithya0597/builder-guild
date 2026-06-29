"""eval_planner.py — acceptance tests for the Agentic RAG planner loop (G1).

Tests (all P1-P5 use _serve injection — NO Neo4j needed):
    P1  >=2-self-chosen:  multi-step question; distinct_retrievals>=2, modes differ,
                          terminated_on=="confidence"
    P2  bounded:          gibberish query; steps_used<=max_steps, terminated_on=="abstain",
                          decision abstain
    P3  signal-driven:    stub returns abstain-WITH-facts on step 1, pass on neighbor-query
                          at step 2; step 2's query_chosen CONTAINS the planted neighbor key
    P4  isolation-caught: inject _serve returning trace.isolation.clean=False;
                          assert plan() raises AssertionError
    P5  no-op guard:      no (query, pattern) pair repeats across steps

demo() is Neo4j-gated (prints PLANNER_OK iff >=2 distinct retrievals + bounded terminal
+ all isolation_clean on a live multi-step question).

Prints PLANNER_OK iff P1-P5 all pass. sys.exit(1) on any failure.
"""
import os
import sys

# Make 01-context/src and 02-agents/src importable. Import-time sys.path.insert follows the
# repo's eval-module convention (mirrors eval_corrective.py / cal3_fit.py) — kept deliberately.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "02-agents", "src"))

from planner import plan
# bc7 self-owned transient fixture seeders (oz4 pattern; mirrors gt2_draft.py / eval_corrective.py).
# Reuse mutate's URI/AUTH (the shared localhost dev cred) rather than re-inlining it — one source.
from mutate import resolve_entity, apply_edge, URI, AUTH


def _run_test(name, fn):
    """Run a test function; return (ok, error_str). Mirrors eval_corrective._run_test."""
    try:
        fn()
        return True, None
    except AssertionError as e:
        return False, f"AssertionError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Shared stub helpers
# ---------------------------------------------------------------------------

def _make_pass_result(query, primary="issue:SPI-3", fact="ASSIGNED_TO -> agent:cto"):
    """A serve()-shaped result with a SUPPORTED fact -> pass decision."""
    return {
        "query": query,
        "decision": "pass",
        "primary": primary,
        "presentable_facts": [f"{primary}: {fact}"],
        "composed_evidence": [],
        "trace": {
            "isolation": {"clean": True, "leaked": []},
            "gate_abstain": {
                "sufficiency": 0.67,
                "self_confidence": 0.95,
                "confidence_basis": "graph_structural_exact",
                "score": 0.82,
                "final": "pass",
                "mode": "suggest",
            },
        },
        "mode": "suggest",
        "executed": False,
        "provenance": {primary: "graph"},
    }


def _make_abstain_result(query, primary=None, facts=None, composed=None):
    """A serve()-shaped result that abstains (no or insufficient facts)."""
    pf = facts or []
    ce = composed or []
    suf = round(min(1.0, len(pf) / 3.0), 2)
    return {
        "query": query,
        "decision": "abstain",
        "primary": primary,
        "presentable_facts": pf,
        "composed_evidence": ce,
        "trace": {
            "isolation": {"clean": True, "leaked": []},
            "gate_abstain": {
                "sufficiency": suf,
                "self_confidence": 0.2,
                "confidence_basis": "graph_structural_exact",
                "score": None,  # will be derived by planner via selective_score
                "final": "abstain",
                "mode": "suggest",
            },
        },
        "mode": "suggest",
        "executed": False,
        "provenance": {},
    }


# ---------------------------------------------------------------------------
# P1: >=2 self-chosen retrievals, different modes, terminated_on=="confidence"
# ---------------------------------------------------------------------------
def p1_multi_step():
    """Multi-step question: planner must self-choose >=2 distinct retrieval modes
    and terminate on confidence (genuine pass), not max_steps or exhaustion.

    Stub: step 1 returns abstain-WITH-facts (planted neighbor 'issue:SPI-3' via a
    BLOCKS edge -> neighbor-hop is the correct choice). The stub passes ONLY when the
    planner's chosen step-2 query actually carries that neighbor key AND the mode is
    neighbor_hop; any other choice gets abstain, so a wrong/scripted choice FAILS the
    test (codex MED-5: the 2nd-call-passes-regardless stub proved only that a 2nd step
    happened).
    """
    NEIGHBOR = "issue:SPI-3"
    call_count = {"n": 0}

    def _stub(query, role, pattern=None, action=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Step 1: abstain WITH a fact whose 1-hop target is the planted neighbor
            return _make_abstain_result(
                query,
                primary="issue:SPI-6",
                facts=[f"issue:SPI-6: BLOCKS -> {NEIGHBOR}"],
            )
        # Step 2+: pass ONLY if the planner chose the neighbor-hop probe correctly
        if NEIGHBOR in (query or ""):
            return _make_pass_result(query, primary="issue:SPI-3")
        return _make_abstain_result(query, primary=None, facts=[], composed=[])

    r = plan("who does SPI-6 block and who owns the blocker", "engineering",
             max_steps=4, tau=0.5, _serve=_stub)
    p = r["planner"]

    assert p["distinct_retrievals"] >= 2, (
        f"P1: distinct_retrievals={p['distinct_retrievals']} < 2"
    )
    modes = [s["retrieval_mode"] for s in p["steps"]]
    assert len(set(modes)) >= 2, (
        f"P1: retrieval modes did not differ across steps: {modes}"
    )
    # step 2 must be the neighbor-hop the signal demanded (not any arbitrary 2nd probe)
    assert p["steps"][1]["retrieval_mode"] == "neighbor_hop", (
        f"P1: step 2 mode={p['steps'][1]['retrieval_mode']!r}, expected 'neighbor_hop'"
    )
    assert p["terminated_on"] == "confidence", (
        f"P1: terminated_on={p['terminated_on']!r}, expected 'confidence'"
    )
    final_decision = p["steps"][-1]["confidence_signal"]["decision"]
    assert final_decision == "pass", (
        f"P1: final decision={final_decision!r}, expected 'pass' (genuine answer)"
    )
    print(f"  P1 >=2-self-chosen: distinct_retrievals={p['distinct_retrievals']} "
          f"modes={modes} terminated_on={p['terminated_on']} final={final_decision}")


# ---------------------------------------------------------------------------
# P2: bounded — gibberish query stays abstain, steps_used<=max_steps
# ---------------------------------------------------------------------------
def p2_bounded():
    """Gibberish query: planner must never exceed max_steps and must terminate
    with decision abstain and terminated_on=='abstain'.
    """
    def _stub(query, role, pattern=None, action=None):
        return _make_abstain_result(query, primary=None, facts=[], composed=[])

    max_s = 3
    r = plan("xyzzy frobnitz quux zork", "engineering", max_steps=max_s, _serve=_stub)
    p = r["planner"]

    assert p["steps_used"] <= max_s, (
        f"P2: steps_used={p['steps_used']} > max_steps={max_s}"
    )
    assert p["terminated_on"] == "abstain", (
        f"P2: terminated_on={p['terminated_on']!r}, expected 'abstain'"
    )
    final_decision = p["steps"][-1]["confidence_signal"]["decision"] if p["steps"] else "abstain"
    assert final_decision == "abstain", (
        f"P2: final step decision={final_decision!r}, expected 'abstain'"
    )
    print(f"  P2 bounded: steps_used={p['steps_used']} max_steps={max_s} "
          f"terminated_on={p['terminated_on']} final_decision={final_decision}")


# ---------------------------------------------------------------------------
# P3: signal-driven — step 2 query_chosen CONTAINS the planted neighbor key
# ---------------------------------------------------------------------------
def p3_signal_driven():
    """Signal-driven choice proof:
    Step 1: abstain WITH a planted fact 'issue:SPI-6: BLOCKS -> issue:SPI-99' (neighbor=SPI-99).
    Step 2: stub receives the neighbor-expanded query and returns pass.
    Assert step 2's query_chosen contains 'issue:SPI-99' — proving the choice came from
    step 1's signal (the neighbor key), not a hardcoded script.
    """
    NEIGHBOR = "issue:SPI-99"
    call_count = {"n": 0}
    captured_queries = []

    def _stub(query, role, pattern=None, action=None):
        call_count["n"] += 1
        captured_queries.append(query)
        if call_count["n"] == 1:
            return _make_abstain_result(
                query,
                primary="issue:SPI-6",
                facts=[f"issue:SPI-6: BLOCKS -> {NEIGHBOR}"],
            )
        # Step 2: pass ONLY when the planner actually chose the neighbor-hop probe carrying
        # the planted key. Any other query -> abstain, so a wrong choice FAILS the test
        # (codex MED-5: the prior 'pass regardless' stub proved only that a 2nd step ran).
        if NEIGHBOR in (query or ""):
            return _make_pass_result(query, primary="issue:SPI-99")
        return _make_abstain_result(query, primary=None, facts=[], composed=[])

    r = plan("what does SPI-6 block", "engineering", max_steps=4, _serve=_stub)
    p = r["planner"]

    assert len(p["steps"]) >= 2, f"P3: expected >=2 steps, got {len(p['steps'])}"
    step2 = p["steps"][1]
    assert step2["retrieval_mode"] == "neighbor_hop", (
        f"P3: step 2 mode={step2['retrieval_mode']!r}, expected 'neighbor_hop' "
        f"(the signal-driven choice from step 1's BLOCKS edge)"
    )
    assert NEIGHBOR in step2["query_chosen"], (
        f"P3: step 2 query_chosen={step2['query_chosen']!r} does not contain "
        f"planted neighbor key {NEIGHBOR!r} — choice was NOT driven by step 1's signal"
    )
    # And the planted-key choice must be what actually resolved it (genuine pass).
    assert r.get("decision") == "pass", (
        f"P3: final decision={r.get('decision')!r}, expected 'pass' via the neighbor-hop probe"
    )
    print(f"  P3 signal-driven: step2.query_chosen={step2['query_chosen']!r} "
          f"contains planted neighbor {NEIGHBOR!r}; "
          f"retrieval_mode={step2['retrieval_mode']} -> decision={r.get('decision')}")


# ---------------------------------------------------------------------------
# P4: isolation-violation-caught — plan() raises AssertionError on unclean trace
# ---------------------------------------------------------------------------
def p4_isolation_caught():
    """Inject a _serve that returns trace.isolation.clean=False;
    assert plan() raises AssertionError (copies corrective's T4 guard pattern).
    """
    def _unclean_serve(query, role, pattern=None, action=None):
        return {
            "query": query,
            "decision": "abstain",
            "primary": "issue:LEAK",
            "presentable_facts": [],
            "composed_evidence": [],
            "trace": {"isolation": {"clean": False, "leaked": ["issue:LEAK"]}},
            "mode": "suggest",
            "executed": False,
        }

    guard_fired = False
    try:
        plan("anything", "engineering", _serve=_unclean_serve, max_steps=2)
    except AssertionError as e:
        guard_fired = True
        assert "isolation" in str(e).lower(), (
            f"P4: AssertionError does not mention 'isolation': {e}"
        )
    assert guard_fired, "P4: plan() did NOT raise AssertionError on unclean isolation trace"
    print("  P4 isolation-caught: plan() raised AssertionError with 'isolation' in message")


# ---------------------------------------------------------------------------
# P5: no-op guard — no (query, pattern) repeats across steps
# ---------------------------------------------------------------------------
def p5_no_op_guard():
    """Assert no (query, pattern) probe pair repeats across planner steps."""
    call_count = {"n": 0}

    def _stub(query, role, pattern=None, action=None):
        call_count["n"] += 1
        # Force several abstain steps with facts to drive multiple branches
        if call_count["n"] <= 3:
            return _make_abstain_result(
                query,
                primary="issue:SPI-6",
                facts=["issue:SPI-6: BLOCKS -> issue:SPI-3"],
            )
        return _make_pass_result(query)

    r = plan("what blocks SPI-3 and who owns it", "engineering",
             max_steps=4, _serve=_stub)
    p = r["planner"]

    seen = set()
    for s in p["steps"]:
        pat = s["pattern_chosen"]
        pt_key = None if pat is None else tuple(sorted(pat.items()))
        probe = (s["query_chosen"], pt_key)
        assert probe not in seen, (
            f"P5: duplicate probe found at step {s['step']}: {probe!r}"
        )
        seen.add(probe)

    print(f"  P5 no-op guard: {len(p['steps'])} steps, all (query, pattern) distinct")


# ---------------------------------------------------------------------------
# demo() — Neo4j-gated live run
# ---------------------------------------------------------------------------
def _check_neo4j():
    """Fail fast with clear message if live graph is unreachable (mirrors eval_corrective)."""
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(URI, auth=AUTH)
        drv.verify_connectivity()
        drv.close()
        return True
    except Exception as e:
        print(f"DEPENDENCY: Neo4j unreachable at bolt://localhost:7688 ({type(e).__name__}: {e}).")
        print("  demo() is a live integration test; bring up the ACME graph first.")
        return False


# bc7 self-owned transient fixture (oz4 pattern; mirrors gt2_draft.py): the demo SEEDS the exact
# 2-hop shape it asserts, namespaced to engineering, and DETACH DELETEs in finally — decoupling from
# the shared mutable demo_seed graph, which migrated SPI-* -> ACME-*. The live graph now has 0 SPI
# nodes (the edge model is RELATES_TO{name:...}, and the ASSIGNED_TO/BLOCKS edges that DO exist hang
# off ACME-* nodes), so the OLD question 'SPI-3 blocking SPI-6' retrieved nothing and abstained ->
# PLANNER_FAIL. The fixture re-establishes the named 2-hop independent of the demo_seed vocabulary.
# agent:cto is a stable role node (referenced, never seeded/deleted), matching gt2_draft's treatment
# of agent:cto / agent:cfo.
_FIXTURE_NOW = "2026-06-14T04:00:00Z"
_FIXTURE_KEYS = ["issue:SPI-3", "issue:SPI-6"]


def _cleanup_fixture(drv):
    with drv.session() as s:
        s.execute_write(lambda tx: tx.run(
            "MATCH (n:Entity) WHERE n.key IN $keys DETACH DELETE n", keys=_FIXTURE_KEYS))


def _seed_fixture(drv):
    """Seed the genuine 2-hop the demo asserts:
      issue:SPI-6  — engineering, NO outgoing edges  -> the UNSUPPORTED probe-1 primary (abstain).
      issue:SPI-3  — engineering, BLOCKS -> SPI-6 AND ASSIGNED_TO -> agent:cto -> the structural
                     re-aim target whose ASSIGNED_TO edge carries the answer (owner = agent:cto).
    The planner must (1) NOT confident-abstain on the no-facts SPI-6 (bc7 fix1: score_stop now also
    requires retrieved facts), then (2) reach SPI-3 via the Branch-1 graph_pattern structural probe
    (verb 'blocks' -> BLOCKS, obj issue:SPI-6 — bc7 fix2: the verb is taken from the ORIGINAL
    question, surviving the id_extract step). agent:cto must already exist (seeded by demo_seed)."""
    with drv.session() as s:
        s.execute_write(lambda tx: resolve_entity(
            tx, "Issue", "issue:SPI-6", _FIXTURE_NOW, "engineering",
            short="issue:SPI-6", long_="Issue SPI-6 — downstream consumer, blocked by SPI-3."))
        s.execute_write(lambda tx: resolve_entity(
            tx, "Issue", "issue:SPI-3", _FIXTURE_NOW, "engineering",
            short="issue:SPI-3", long_="Issue SPI-3 — the blocker; owned by the CTO."))
        s.execute_write(lambda tx: apply_edge(
            tx, "issue:SPI-3", "BLOCKS", "issue:SPI-6", _FIXTURE_NOW, "engineering"))
        s.execute_write(lambda tx: apply_edge(
            tx, "issue:SPI-3", "ASSIGNED_TO", "agent:cto", _FIXTURE_NOW, "engineering"))


def demo():
    """Live multi-step question on a SELF-OWNED transient fixture: print each step + assert
    GENUINE-ANSWER criteria.

    Returns True iff the planner self-chose >=2 distinct retrievals, every step's isolation was
    clean, AND the FINAL step is a genuine answer — decision in {pass, partial} WITH the RELEVANT
    evidence (the ASSIGNED_TO -> agent:cto fact). distinct_retrievals>=2 + isolation-clean ALONE is
    NOT sufficient (codex MED-4): the relevant-evidence gate forecloses a hollow abstain->abstain.

    VERIFIED-LIVE MECHANISM (bc7, re-derived 2026-06-24 — supersedes the stale 'SPI-3 SPI-6 id_extract
    re-rank' story, which broke when keyword_rung's deterministic sort + the ACME migration landed):
      probe 1 (initial)      -> primary=issue:SPI-6, NO outgoing edges -> UNSUPPORTED -> abstain.
                                self_conf=0.95 (exact-id keyword hit) -> score 0.599 >= tau, BUT
                                has_facts=False so confident_abstain does NOT stop (fix1) -> re-aim.
      probe 2 (id_extract)   -> re-query 'SPI-6' -> still SPI-6, still no facts -> re-aim again.
      probe 3 (graph_pattern)-> structural probe {rel:BLOCKS, obj:issue:SPI-6} (verb from the
                                ORIGINAL question, fix2) -> graph_rung returns issue:SPI-3, whose
                                ASSIGNED_TO -> agent:cto fact -> pass.
    Yields distinct_retrievals=3, terminated_on=confidence, final decision=pass with the owner fact.
    """
    from neo4j import GraphDatabase
    question = "what blocks SPI-6 and who is it assigned to"
    # The seeded answer is agent:cto via an ASSIGNED_TO edge on issue:SPI-3 (the blocker of SPI-6).
    # Assert THIS specific fact is present, not just that some non-empty text came back (codex MED-4).
    EXPECTED_ENTITY = "agent:cto"
    EXPECTED_REL = "ASSIGNED_TO"
    print(f"\n[demo] question: {question!r}")
    drv = GraphDatabase.driver(URI, auth=AUTH)
    try:
        _cleanup_fixture(drv)              # drop any stale prior fixture first
        _seed_fixture(drv)                 # oz4 self-owned transient 2-hop
        r = plan(question, "engineering", max_steps=4)
    finally:
        _cleanup_fixture(drv)              # always tear down, even on assertion error
        drv.close()
    p = r["planner"]

    all_iso_clean = all(s["isolation_clean"] for s in p["steps"])

    for s in p["steps"]:
        cs = s["confidence_signal"]
        print(f"  step={s['step']} mode={s['retrieval_mode']} "
              f"query={s['query_chosen']!r} pattern={s['pattern_chosen']} "
              f"why={s['why']!r}")
        print(f"         decision={cs['decision']} score={cs['score']} "
              f"suf={cs['sufficiency']} self_conf={cs['self_confidence']} "
              f"basis={cs['basis']} iso_clean={s['isolation_clean']}")

    # GENUINE-ANSWER gate: final step must actually answer with the RELEVANT evidence.
    final_step = p["steps"][-1] if p["steps"] else None
    final_decision = final_step["confidence_signal"]["decision"] if final_step else "abstain"
    evidence_blob = " ".join(
        (r.get("presentable_facts") or []) + (r.get("composed_evidence") or [])
    )
    # Relevant = the expected owner entity is present (and, when in presentable_facts, via
    # the expected relation edge). Accept the entity in either field; require the relation
    # edge to appear somewhere in the answer.
    relevant_evidence = (EXPECTED_ENTITY in evidence_blob) and (EXPECTED_REL in evidence_blob)
    answered = final_decision in ("pass", "partial") and relevant_evidence

    ok = (
        p["distinct_retrievals"] >= 2
        and all_iso_clean
        and answered
    )
    print(f"\n[demo] distinct_retrievals={p['distinct_retrievals']} "
          f"terminated_on={p['terminated_on']} steps_used={p['steps_used']} "
          f"all_iso_clean={all_iso_clean} final_decision={final_decision} "
          f"relevant_evidence={relevant_evidence} (expect {EXPECTED_REL}->{EXPECTED_ENTITY}) "
          f"answered={answered}")
    print("PLANNER_OK" if ok else "PLANNER_FAIL")
    return ok


# ---------------------------------------------------------------------------
# Main runner (mirrors eval_corrective.py table structure)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Gate at the top: the live demo() is the acceptance signal and needs the seeded
    # ACME graph. Mirror eval_corrective.py:361-364 — no graph, no run.
    if not _check_neo4j():
        print("\nPLANNER_FAIL: live-graph dependency missing (see above).")
        sys.exit(2)

    tests = [
        ("P1", ">=2-self-chosen: multi-step -> distinct_retrievals>=2 + modes differ + confidence terminal", p1_multi_step),
        ("P2", "bounded: gibberish -> steps_used<=max_steps, terminated_on==abstain", p2_bounded),
        ("P3", "signal-driven: step2.query_chosen contains planted neighbor key", p3_signal_driven),
        ("P4", "isolation-caught: unclean trace -> AssertionError", p4_isolation_caught),
        ("P5", "no-op guard: no (query,pattern) repeats", p5_no_op_guard),
    ]

    results = []
    for tid, desc, fn in tests:
        print(f"\n[{tid}] {desc}")
        ok, err = _run_test(tid, fn)
        results.append((tid, ok, err))
        if not ok:
            print(f"  FAIL: {err}")

    print("\n--- Summary ---")
    tests_pass = True
    for tid, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {tid}: {status}" + (f" — {err}" if err else ""))
        if not ok:
            tests_pass = False

    # P-suite marker is DISTINCT from the demo's: PLANNER_TESTS_OK is the injection
    # suite; PLANNER_OK comes solely from the live demo() below, so the acceptance
    # token is unambiguously the real-graph run.
    if tests_pass:
        print("\nPLANNER_TESTS_OK")
    else:
        print("\nPLANNER_TESTS_FAIL")

    # Live acceptance run (graph already verified above). Prints PLANNER_OK/PLANNER_FAIL.
    demo_ok = demo()

    # Process exits nonzero if EITHER the injection suite or the live demo failed.
    if not (tests_pass and demo_ok):
        sys.exit(1)
