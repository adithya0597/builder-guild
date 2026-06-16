"""test_g3.py — G3 calibration trust-track acceptance tests.

$0, ZERO neo4j in the required path — including NO real `neo4j` PACKAGE. A dummy module is
installed into sys.modules["neo4j"] at import time (below), so every transitive `import serve`
(serve.py does `from neo4j import GraphDatabase` at module top) resolves to a stub. The tests
never open a Bolt connection — graph-dependent results are constructed directly or via _serve
injection. The whole suite runs with neo4j DOWN and with the neo4j package absent.

(a) Import smoke:       cal3_fit + cal4_sweep import cleanly post-STEP-0 fixes (judge_adapter
                        rename, golden path, sys.path) — verified WITHOUT the real neo4j package.
(b) Coverage signal:    item 2 — drives the REAL serve._support_coverage helper (not a mirror):
                        prefixed-key found -> 0.5; over-retrieval doesn't inflate; UNSUPPORTED
                        primary (empty facts) -> 0.0; |Q|=0 -> 0.0 (NO count fallback).
(c) Abstain channel:    item 3 — abstain items never reach the judge; label_correct scores on
                        the decision channel only (judge stub is PURE — never hits the CLI).
(d) Per-namespace lease: item 5 — auto_revert("finance", 0.4, -3.0) revokes exactly finance,
                        leaves others untouched; mode reads suggest vs autonomous accordingly.
(e) Golden_v1 draft:    item 4 — >=30 items, balanced pass/abstain, 6 roles, all unvalidated.
(f) Founder-only paths:  cal3_fit and cal4_sweep accept explicit golden/result paths instead of
                        hardwiring example_golden.jsonl.

Prints G3_OK iff all pass. sys.exit(1) on any failure.
"""
import os
import sys
import types

# Make 01-context/src + this dir importable (mirrors eval_corrective.py convention)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

# Stub the neo4j PACKAGE before any (lazy) `import serve`/`import cal3_fit` inside a test runs.
# serve.py does `from neo4j import GraphDatabase` at module top; we never connect, so a dummy
# class is enough. This is what lets the import-smoke verify STEP-0's fixes WITHOUT the real
# driver, and lets (b) import the real _support_coverage helper at $0.
if "neo4j" not in sys.modules:
    _neo4j_stub = types.ModuleType("neo4j")
    _neo4j_stub.GraphDatabase = type("GraphDatabase", (), {"driver": staticmethod(lambda *a, **k: None)})
    sys.modules["neo4j"] = _neo4j_stub

import importlib


def _run_test(name, fn):
    try:
        fn()
        return True, None
    except AssertionError as e:
        return False, f"AssertionError: {e}"
    except Exception as e:
        import traceback
        return False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


# ---------------------------------------------------------------------------
# (a) Import smoke — cal3_fit and cal4_sweep import cleanly after STEP-0 fixes
# ---------------------------------------------------------------------------
def ta_import_smoke():
    # Lazy imports (codex MED-3): kept INSIDE the function so the b–e property tests don't drag
    # cal3_fit/serve in at module load. neo4j is stubbed at module top, so these verify STEP-0's
    # fixes (judge_adapter rename, golden path, sys.path insert) WITHOUT the real neo4j package.
    import cal3_fit
    import cal4_sweep
    # Confirm the public judge_adapter import is wired
    assert hasattr(cal3_fit, "score_match"), "cal3_fit must expose score_match from judge_adapter"
    assert hasattr(cal4_sweep, "score_match"), "cal4_sweep must expose score_match from judge_adapter"
    # Confirm sys.path insertion happened (01-context/src reachable) and the real helper is present
    import serve  # imported transitively through cal3_fit; would NameError if path not set
    assert hasattr(serve, "_support_coverage"), "serve must expose the _support_coverage helper"
    print(f"  (a) cal3_fit + cal4_sweep import OK (neo4j stubbed); judge_adapter wired; "
          f"serve._support_coverage present")


# ---------------------------------------------------------------------------
# (b) Coverage signal — item 2 — drives the REAL serve._support_coverage helper.
# A previous mirror copy drifted from prod and carried the SAME original bug, so the test
# passed while serve() was broken. Importing the real helper kills that whole failure mode.
# coverage = |asked-entities found in SUPPORT| / max(1, |asked-entities|), canonicalized to the
# id token after the last ":" ("issue:SPI-3" and bare "SPI-3" -> "SPI-3"; "agent:cto" -> "cto").
# Cases:
#   (i)  prefixed-key found (the planner step-2 repro): bare "SPI-3"/"SPI-6" in question,
#        prefixed "issue:SPI-3"/"agent:cto" in support -> 0.5 (1 of 2 asked ids found). The
#        original bare-vs-prefixed bug returned 0.0 here -> abstain -> PLANNER_FAIL.
#   (ii) over-retrieval: extra keys in R the question didn't ask for -> no inflation (cap 1.0).
#   (iii) UNSUPPORTED primary with EMPTY presentable_facts -> 0.0 (proves support-gated R: a
#        dead-end node named in the question contributes nothing, so the planner can keep hopping).
#   (iv) |Q|=0 (NL question, no extractable ids) -> 0.0 (proves NO count fallback — the old
#        len(facts)/3 proxy is gone; it must not silently reappear on regex-missed questions).
# ---------------------------------------------------------------------------
def tb_coverage_signal():
    from serve import _support_coverage as cov   # the REAL prod helper (neo4j stubbed at top)

    # (i) prefixed-key found — bare ids in question, prefixed keys in support -> 0.5
    c_i = cov("SPI-3 SPI-6", "issue:SPI-3", ["ASSIGNED_TO -> agent:cto"])
    assert c_i == 0.5, (
        f"(b.i) prefixed-key coverage should be 0.5 (1 of 2 asked ids {{SPI-3,SPI-6}} found via "
        f"canonicalized intersection); got {c_i} — 0.0 here is the PLANNER_FAIL bare-vs-prefixed bug")
    assert c_i > 0.0, "(b.i) coverage MUST be POSITIVE when the asked entity is in the support"
    print(f"  (b.i)  prefixed-key found coverage={c_i} (expect 0.5, POSITIVE) OK")

    # (ii) over-retrieval: Q={ACME-2}, R={ACME-2, cto, ACME-3, ACME-6, ACME-7} -> 1/1 capped 1.0
    c_ii = cov("What about issue:ACME-2", "issue:ACME-2",
               ["ASSIGNED_TO -> agent:cto", "BLOCKS -> issue:ACME-3",
                "RELATES_TO -> issue:ACME-6", "RELATES_TO -> issue:ACME-7"])
    assert c_ii == 1.0, f"(b.ii) over-retrieval coverage must cap at 1.0, got {c_ii}"
    assert c_ii <= 1.0, f"(b.ii) coverage MUST NOT exceed 1.0 (got {c_ii})"
    print(f"  (b.ii) over-retrieval coverage={c_ii} (capped at 1.0, no inflation) OK")

    # (iii) UNSUPPORTED primary, EMPTY presentable_facts -> 0.0 (support-gated R)
    c_iii = cov("SPI-3 SPI-6", "issue:SPI-6", [])
    assert c_iii == 0.0, (
        f"(b.iii) a node with NO presentable facts is UNSUPPORTED and must contribute 0.0 to "
        f"support coverage (its bare key must NOT count); got {c_iii}")
    print(f"  (b.iii) unsupported-primary (empty facts) coverage={c_iii} (expect 0.0) OK")

    # (iv) |Q|=0 (NL question, regex extracts nothing) -> 0.0, NOT a fact-count proxy
    c_iv = cov("what is the budget for next quarter", "issue:ACME-9", ["HAS_BUDGET -> finance:q3"])
    assert c_iv == 0.0, (
        f"(b.iv) |Q|=0 must return conservative 0.0 — NEVER score by raw fact count (the "
        f"anti-correlated proxy this signal removes); got {c_iv}. A count fallback would return "
        f"~0.33 here (1 fact / 3) on an NL question with NO identifiable asked-entity.")
    print(f"  (b.iv) |Q|=0 NL-question coverage={c_iv} (expect 0.0, no count fallback) OK")


# ---------------------------------------------------------------------------
# (c) Abstain channel — item 3
# label_correct: abstain-expected items must be scored on decision channel,
# NEVER sent to the judge (score_match must never be called for them).
# ---------------------------------------------------------------------------
def tc_abstain_channel():
    import cal3_fit

    # PURE judge stub (codex MED-4): records the call and returns a dummy verdict. It NEVER
    # delegates to the real score_match — delegating could spawn the JUDGE_CMD subprocess
    # (judge_adapter._call runs `subprocess.run([JUDGE_CMD, ...])`) if label_correct ever
    # regressed to route an abstain item to the judge. The whole point of (c) is that abstain
    # items hit ZERO judge calls; the stub must make a stray call observable, not executable.
    judge_calls = []
    original_score_match = cal3_fit.score_match

    def _pure_judge_stub(question, candidate, gold, key=None, ckpt=None):
        judge_calls.append((question, candidate, gold))
        return {"match": True, "confidence": 1.0}, 0.0   # dummy verdict, never the real CLI

    cal3_fit.score_match = _pure_judge_stub

    try:
        # Abstain-expected item: serve abstained -> correct=1
        item_abstain = {
            "id": "null-xrole",
            "role": "engineering",
            "question": "What is the finance budget?",
            "expected_decision": "abstain",
            "correct_answer": "abstain",
            "support_facts": [],
            "kind": "null",
        }
        r_abstained = {"decision": "abstain", "primary": None,
                       "presentable_facts": [], "composed_evidence": []}
        r_passed    = {"decision": "pass", "primary": "issue:ACME-2",
                       "presentable_facts": ["ASSIGNED_TO -> agent:cto"], "composed_evidence": []}

        # Case 1: serve abstained on an abstain-expected item -> correct=1, no judge call
        judge_calls.clear()
        correct, how = cal3_fit.label_correct(item_abstain, r_abstained, "/tmp/nonexistent.jsonl")
        assert correct == 1, f"(c.i) abstain item, serve abstained: correct should be 1, got {correct}"
        assert how == "deterministic:abstain", f"(c.i) how should be deterministic:abstain, got {how!r}"
        assert len(judge_calls) == 0, f"(c.i) judge was called {len(judge_calls)} times for abstain item (must be 0)"
        print(f"  (c.i)  abstain+abstained: correct={correct} via={how!r} judge_calls={len(judge_calls)} OK")

        # Case 2: serve passed on an abstain-expected item -> correct=0, no judge call
        judge_calls.clear()
        correct2, how2 = cal3_fit.label_correct(item_abstain, r_passed, "/tmp/nonexistent.jsonl")
        assert correct2 == 0, f"(c.ii) abstain item, serve passed: correct should be 0, got {correct2}"
        assert how2 == "deterministic:abstain", f"(c.ii) how should be deterministic:abstain, got {how2!r}"
        assert len(judge_calls) == 0, f"(c.ii) judge was called {len(judge_calls)} times (must be 0)"
        print(f"  (c.ii) abstain+passed:   correct={correct2} via={how2!r} judge_calls={len(judge_calls)} OK")

    finally:
        cal3_fit.score_match = original_score_match


# ---------------------------------------------------------------------------
# (d) Per-namespace lease — item 5
# auto_revert("finance", 0.4, -3.0) revokes exactly finance.
# If "engineering" was seeded True, it remains True. Others stay False.
# Mode reads: suggest for revoked/unset, autonomous for True.
# ---------------------------------------------------------------------------
def td_per_namespace_lease():
    import abstain
    importlib.reload(abstain)   # clean slate for this test

    # Seed engineering=True to prove auto_revert doesn't touch it
    abstain.CALIBRATED["engineering"] = True

    # Confirm finance is currently False (default)
    assert abstain.CALIBRATED["finance"] is False, "finance should start False"

    # auto_revert finance with bad kappa+gain -> should revoke (finance was False, so no-op but idempotent)
    result_false = abstain.auto_revert("finance", 0.4, -3.0)
    assert result_false["revoked"] is False, (
        f"(d.i) auto_revert on already-False finance should not mark revoked=True: {result_false}")
    assert abstain.CALIBRATED["finance"] is False, "finance must stay False"
    print(f"  (d.i)  auto_revert(finance, 0.4, -3.0) on already-False: revoked={result_false['revoked']} OK")

    # Now seed finance=True and call auto_revert with bad metrics -> should revoke
    abstain.CALIBRATED["finance"] = True
    result_revoke = abstain.auto_revert("finance", 0.4, -3.0)
    assert result_revoke["revoked"] is True, (
        f"(d.ii) auto_revert should revoke finance when kappa=0.4<0.8: {result_revoke}")
    assert abstain.CALIBRATED["finance"] is False, "finance must be revoked to False"
    print(f"  (d.ii) auto_revert(finance, 0.4, -3.0) revoked finance: {result_revoke['reason']!r} OK")

    # engineering was seeded True -> must still be True (auto_revert is role-specific)
    assert abstain.CALIBRATED["engineering"] is True, (
        f"(d.iii) engineering should still be True after finance revoke, got {abstain.CALIBRATED['engineering']}")
    print(f"  (d.iii) engineering untouched: CALIBRATED[engineering]={abstain.CALIBRATED['engineering']} OK")

    # Mode reads correctly
    g_eng = abstain.abstain_gate(0.9, 0.9, role="engineering")
    g_fin = abstain.abstain_gate(0.9, 0.9, role="finance")
    assert g_eng["mode"] == "autonomous", f"(d.iv) engineering should be autonomous, got {g_eng['mode']}"
    assert g_fin["mode"] == "suggest",    f"(d.iv) finance should be suggest, got {g_fin['mode']}"
    print(f"  (d.iv) mode: engineering={g_eng['mode']} finance={g_fin['mode']} OK")

    # Others (operations, product, market, governance, shared) must all be False
    others = [r for r in abstain.CALIBRATED if r not in ("engineering", "finance")]
    for r in others:
        assert abstain.CALIBRATED[r] is False, f"(d.v) {r} should be False, got {abstain.CALIBRATED[r]}"
    print(f"  (d.v)  other namespaces all False: {others} OK")

    # Reset so module state doesn't bleed into other tests
    abstain.CALIBRATED["engineering"] = False


# ---------------------------------------------------------------------------
# (e) Golden_v1 draft — item 4
# >=30 items, balanced pass/abstain, 6 roles, all unvalidated
# ---------------------------------------------------------------------------
def te_golden_v1_draft():
    # Import the draft generator and validate its output without re-running file I/O
    import golden_v1_draft as gv1
    from golden import validate_item

    items = gv1.draft_items()

    # >=30 items
    assert len(items) >= 30, f"(e.i) need >=30 items, got {len(items)}"
    print(f"  (e.i)  item count={len(items)} (>=30) OK")

    # all 6 required roles present
    required_roles = {"engineering", "finance", "operations", "product", "market", "governance"}
    present = {i["role"] for i in items}
    missing = required_roles - present
    assert not missing, f"(e.ii) missing roles: {missing}"
    print(f"  (e.ii) all 6 roles present: {sorted(present)} OK")

    # all unvalidated
    unvalidated = all(i["correct_answer"] == "" and i["validated"] is False for i in items)
    assert unvalidated, "(e.iii) all items must have correct_answer=='' and validated=False"
    print(f"  (e.iii) all {len(items)} items unvalidated OK")

    # balanced: neither pass nor abstain below 25%
    abstain_count = sum(1 for i in items if i.get("expected_decision") == "abstain")
    pass_count = len(items) - abstain_count
    min_count = len(items) * 0.25
    assert abstain_count >= min_count, f"(e.iv) abstain_count={abstain_count} < min {min_count:.1f}"
    assert pass_count    >= min_count, f"(e.iv) pass_count={pass_count} < min {min_count:.1f}"
    print(f"  (e.iv) balance: pass={pass_count} abstain={abstain_count} (min={min_count:.1f}) OK")

    # schema validity
    bad = [(i["id"], errs2) for i in items for ok2, errs2 in [validate_item(i)] if not ok2]
    assert not bad, f"(e.v) schema errors: {bad}"
    print(f"  (e.v)  all items schema-valid OK")


# ---------------------------------------------------------------------------
# (f) Founder-only paths — cal3_fit/cal4_sweep must accept explicit golden/result
# paths so the founder gate can run on private validated golds instead of the
# public example_golden.jsonl.
# ---------------------------------------------------------------------------
def tf_founder_only_paths():
    import cal3_fit
    import cal4_sweep

    dflt3 = cal3_fit.parse_args([])
    assert dflt3.golden.endswith("example_golden.jsonl"), (
        f"(f.i) cal3 default golden should remain the public example set, got {dflt3.golden!r}")
    custom3 = cal3_fit.parse_args(["--golden", "/tmp/founder_gold.jsonl"])
    assert custom3.golden == "/tmp/founder_gold.jsonl", (
        f"(f.ii) cal3 must accept --golden override, got {custom3.golden!r}")
    print(f"  (f.i/ii) cal3 default={dflt3.golden!r} custom={custom3.golden!r} OK")

    dflt4 = cal4_sweep.parse_args([])
    assert dflt4.golden.endswith("example_golden.jsonl"), (
        f"(f.iii) cal4 default golden should remain the public example set, got {dflt4.golden!r}")
    assert dflt4.cal3_results.endswith("cal3_fit_results.json"), (
        f"(f.iv) cal4 default cal3_results should point at cal3_fit_results.json, got {dflt4.cal3_results!r}")
    custom4 = cal4_sweep.parse_args([
        "--golden", "/tmp/founder_gold.jsonl",
        "--cal3-results", "/tmp/founder_cal3.json",
    ])
    assert custom4.golden == "/tmp/founder_gold.jsonl", (
        f"(f.v) cal4 must accept --golden override, got {custom4.golden!r}")
    assert custom4.cal3_results == "/tmp/founder_cal3.json", (
        f"(f.vi) cal4 must accept --cal3-results override, got {custom4.cal3_results!r}")
    print(f"  (f.iii-vi) cal4 default={dflt4.golden!r} custom_golden={custom4.golden!r} custom_cal3={custom4.cal3_results!r} OK")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        ("a", "import smoke (cal3_fit + cal4_sweep post-STEP-0, neo4j stubbed)", ta_import_smoke),
        ("b", "coverage signal: REAL _support_coverage helper (found/over-retrieval/unsupported/|Q|=0)", tb_coverage_signal),
        ("c", "abstain channel: abstain items never reach judge", tc_abstain_channel),
        ("d", "per-namespace lease: auto_revert revokes finance, leaves engineering", td_per_namespace_lease),
        ("e", "golden_v1 draft: >=30, balanced, 6 roles, all unvalidated", te_golden_v1_draft),
        ("f", "founder-only paths: cal3/cal4 accept explicit golden/result overrides", tf_founder_only_paths),
    ]

    results = []
    for tid, desc, fn in tests:
        print(f"\n[{tid}] {desc}")
        ok, err = _run_test(tid, fn)
        results.append((tid, ok, err))
        if not ok:
            print(f"  FAIL: {err}")

    print("\n--- Summary ---")
    all_pass = True
    for tid, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {tid}: {status}" + (f" — {err}" if err else ""))
        if not ok:
            all_pass = False

    if all_pass:
        print("\nG3_OK")
    else:
        print("\nG3_FAIL")
        sys.exit(1)
