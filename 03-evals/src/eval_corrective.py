"""eval_corrective.py — acceptance tests for the Corrective-RAG loop (Corrective-RAG §6).

Tests:
    T1  flip:          weak-phrasing query initially abstains -> after a rewrite -> pass
    T2  bounded:       unrecoverable query stays abstain, rewrites_used <= max_rewrites,
                       no infinite loop
    T3  no-op guard:   no (query, pattern) probe repeats in attempted
    T4  isolation:     finance-role weak query never surfaces an engineering node across rewrites;
                       every iteration's trace.isolation.clean is True
    T5  web $0-or-STOP: web_fallback=True + fake CMD echoing "payment required" -> RuntimeError
    T6  web off default: corrective_serve with defaults never calls the web adapter

Prints CORRECTIVE_OK iff all six pass. sys.exit(1) on any failure.

T1 golden case (real seeded ACME data, verified against the local Neo4j graph 2026-06-14):
    query = "SPI-3 blocking SPI-6"  role = "engineering"
    Initial call:
        keyword_rung: [issue:SPI-3, issue:SPI-6] (sorted)
        vector_rung: [issue:SPI-6 (rank1), issue:SPI-7, ...]
        RRF: issue:SPI-6 wins (keyword rank2 + vector rank1 > keyword rank1 alone)
        primary = issue:SPI-6  (no outgoing edges -> UNSUPPORTED -> abstain)
    Corrective rewrite tactic = id_extract (fires first):
        extracts ['SPI-3', 'SPI-6'] from query (regex [A-Za-z]+-\\d+)
        re-serves with query='SPI-3 SPI-6', pattern=None
        primary = issue:SPI-3  (has ASSIGNED_TO -> agent:cto -> SUPPORTED -> pass)
    resolved_at = "rewrite:id_extract"  decision = "pass"

    Verified live on the local Neo4j ACME graph.
"""
import os
import sys
import subprocess
import tempfile

# Make 01-context/src importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

import corrective as _corrective_mod
from corrective import corrective_serve


def _run_test(name, fn):
    """Run a test function; return (ok, error_str)."""
    try:
        fn()
        return True, None
    except AssertionError as e:
        return False, f"AssertionError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# T1: flip — weak phrasing that initially abstains -> rewrite -> pass
# ---------------------------------------------------------------------------
def t1_flip():
    """Query "SPI-3 blocking SPI-6" with role=engineering.

    Initial: keyword=[SPI-3, SPI-6], vector=[SPI-6 rank1, SPI-7, ...].
    RRF: issue:SPI-6 wins (keyword rank2 + vector rank1 > keyword rank1 alone).
    primary=issue:SPI-6 (no outgoing edges -> UNSUPPORTED -> abstain).

    id_extract tactic (fires first):
    Extracts ['SPI-3', 'SPI-6'] from query.
    Re-serves with query='SPI-3 SPI-6', pattern=None.
    primary=issue:SPI-3 (has ASSIGNED_TO -> agent:cto -> pass).

    Verified live on the local Neo4j ACME graph 2026-06-14.
    """
    # Use max_rewrites=3 so multiple tactics can fire if needed
    r = corrective_serve("SPI-3 blocking SPI-6", "engineering", max_rewrites=3)
    c = r["corrective"]

    # The initial attempt must have decision=abstain
    initial = c["attempted"][0]
    assert initial["tactic"] == "initial", f"first attempt tactic != 'initial': {initial}"
    assert initial["decision"] == "abstain", (
        f"T1: initial decision must be 'abstain', got {initial['decision']!r}. "
        f"If the query now passes without a rewrite, choose a weaker T1 query."
    )

    # The loop must have flipped to pass/partial/escalate (non-abstain non-exhausted)
    assert c["resolved_at"].startswith("rewrite:"), (
        f"T1: resolved_at must start with 'rewrite:', got {c['resolved_at']!r}. "
        f"Attempted: {c['attempted']}"
    )

    # Final decision must be 'pass' — the spec's abstain->pass flip (codex review Corrective-RAG:
    # accepting 'partial' lets T1 pass without proving the advertised golden case).
    assert r.get("decision") == "pass", (
        f"T1: final decision must be 'pass' (the abstain->pass flip), got {r.get('decision')!r}"
    )

    # Evidence is present in the resolved result
    assert r.get("presentable_facts") or r.get("composed_evidence"), (
        f"T1: no evidence in resolved result"
    )

    tactic_used = c["resolved_at"][len("rewrite:"):]
    print(f"  T1 flip: initial=abstain -> resolved_at={c['resolved_at']!r} "
          f"decision={r['decision']} tactic={tactic_used!r} "
          f"primary={r.get('primary')} facts={r.get('presentable_facts', [])}")


# ---------------------------------------------------------------------------
# T2: bounded — unrecoverable query stays abstain; rewrites_used <= max_rewrites
# ---------------------------------------------------------------------------
def t2_bounded():
    """A truly unrecoverable query: no matching nodes, all tactics exhaust."""
    max_rw = 2
    r = corrective_serve("xyzzy unrecognized quux frob", "engineering", max_rewrites=max_rw)
    c = r["corrective"]

    assert c["resolved_at"] == "exhausted", (
        f"T2: unrecoverable query should be 'exhausted', got {c['resolved_at']!r}"
    )
    assert r.get("decision") == "abstain", (
        f"T2: final decision must be 'abstain', got {r.get('decision')!r}"
    )
    assert c["rewrites_used"] <= max_rw, (
        f"T2: rewrites_used={c['rewrites_used']} exceeds max_rewrites={max_rw}"
    )
    # Total attempts = initial + rewrites (at most max_rewrites+1)
    assert len(c["attempted"]) <= max_rw + 1, (
        f"T2: len(attempted)={len(c['attempted'])} > max_rewrites+1={max_rw+1}"
    )

    print(f"  T2 bounded: resolved_at={c['resolved_at']} decision={r['decision']} "
          f"rewrites_used={c['rewrites_used']} total_attempts={len(c['attempted'])}")


# ---------------------------------------------------------------------------
# T3: no-op guard — no (query, pattern) probe repeats in attempted
# ---------------------------------------------------------------------------
def t3_no_op_guard():
    """Assert no (query, pattern) pair repeats across attempts.

    Uses the same T1 query (SPI-3 blocking SPI-6) which produces >=2 attempts,
    allowing the no-op guard to be meaningfully exercised.
    """
    r = corrective_serve("SPI-3 blocking SPI-6", "engineering", max_rewrites=3)
    c = r["corrective"]

    seen = set()
    for a in c["attempted"]:
        pt = a.get("pattern")
        pt_key = None if pt is None else tuple(sorted(pt.items()))
        probe = (a["query"], pt_key)
        assert probe not in seen, (
            f"T3: duplicate probe found: tactic={a['tactic']!r} probe={probe!r} "
            f"already in {seen}"
        )
        seen.add(probe)

    print(f"  T3 no-op guard: {len(c['attempted'])} distinct probes, no repeats")


# ---------------------------------------------------------------------------
# T4: isolation — finance-role weak query never surfaces engineering nodes
# ---------------------------------------------------------------------------
def t4_isolation():
    """A finance-role weak query: across all rewrites, isolation must stay clean."""
    # "CI runners" is an engineering topic; finance sees only finance/shared namespace
    r = corrective_serve("CI runner issues migration", "finance", max_rewrites=3)
    c = r["corrective"]

    eng_keys = {
        "issue:SPI-1", "issue:SPI-2", "issue:SPI-3",
        "issue:SPI-6", "issue:SPI-7", "agent:cto",
    }

    # The corrective result's primary (if any) must not be an engineering node
    if r.get("primary"):
        assert r["primary"] not in eng_keys, (
            f"T4: final primary={r['primary']!r} is an engineering node"
        )

    # Every attempt's trace must have isolation.clean=True
    # (isolation is checked by corrective_serve and raises AssertionError on violation;
    # if we got here the loop didn't raise, so all iterations were clean)
    # Additional check: no engineering key in composed_evidence or presentable_facts
    for line in r.get("composed_evidence", []):
        for k in eng_keys:
            assert k not in line, (
                f"T4: engineering key {k!r} found in composed_evidence line: {line!r}"
            )
    for fact in r.get("presentable_facts", []):
        for k in eng_keys:
            assert k not in fact, (
                f"T4: engineering key {k!r} found in presentable_facts: {fact!r}"
            )

    # Every attempt's RECORDED isolation_clean must be True (independent data, not just the raise).
    for a in c["attempted"]:
        assert a.get("isolation_clean") is True, (
            f"T4: attempt {a.get('tactic')!r} isolation_clean={a.get('isolation_clean')!r}"
        )

    # Independently PROVE the per-iteration guard actually fires: inject a stub _serve returning an
    # UNCLEAN isolation trace and assert corrective_serve raises (codex review Corrective-RAG: T4 must
    # test the guard, not rely on it implicitly).
    def _unclean_serve(qt, role, pattern=None, action=None):
        return {"decision": "abstain", "primary": "issue:LEAK",
                "trace": {"isolation": {"clean": False, "leaked": ["issue:LEAK"]}},
                "presentable_facts": [], "composed_evidence": []}
    guard_fired = False
    try:
        corrective_serve("anything", "finance", _serve=_unclean_serve, max_rewrites=1)
    except AssertionError as e:
        guard_fired = "isolation" in str(e).lower()
    assert guard_fired, "T4: corrective_serve did NOT raise on an unclean isolation trace (guard inert)"

    print(f"  T4 isolation: finance role, resolved_at={c['resolved_at']}, no engineering nodes "
          f"surfaced; per-attempt isolation_clean all True; unclean-trace guard fires")


# ---------------------------------------------------------------------------
# T5: web $0-or-STOP — fake CMD echoing "payment required" -> RuntimeError
# ---------------------------------------------------------------------------
def t5_web_stop():
    """Table-test: ANY auth/payment/billing/quota signal in web CLI output -> RuntimeError.
    Stubs subprocess.run directly — standalone (no Neo4j) and no importlib.reload, since the
    adapter now reads env at call time (codex review Corrective-RAG: one literal phrase + reload was
    too weak and papered over the import-time env bug).
    """
    import web_fallback_adapter as wfa

    class _FakeProc:
        def __init__(self, out):
            self.stdout, self.stderr = out, ""

    stop_phrases = ["payment required", "billing issue", "quota reached",
                    "authentication required", "api key required"]
    os.environ["CORRECTIVE_WEB_ENABLED"] = "true"
    os.environ["CORRECTIVE_WEB_CMD"] = "/bin/echo"
    os.environ["CORRECTIVE_WEB_MODEL"] = "test-model"
    orig_run = wfa.subprocess.run
    try:
        for phrase in stop_phrases:
            wfa.subprocess.run = lambda *a, _p=phrase, **k: _FakeProc(_p)
            caught = None
            try:
                wfa.fetch("any query", "engineering")
            except RuntimeError as e:
                caught = e
            assert caught is not None, f"T5: no RuntimeError for stop phrase {phrase!r}"
            assert "STOP" in str(caught) or "AUTH" in str(caught).upper(), (
                f"T5: RuntimeError for {phrase!r} is not the $0-or-STOP guard: {caught}"
            )
    finally:
        wfa.subprocess.run = orig_run
        for k in ("CORRECTIVE_WEB_ENABLED", "CORRECTIVE_WEB_CMD", "CORRECTIVE_WEB_MODEL"):
            os.environ.pop(k, None)

    print(f"  T5 web $0-or-STOP: all {len(stop_phrases)} stop-phrase variants raised RuntimeError")


# ---------------------------------------------------------------------------
# T6: web off default — corrective_serve with defaults never calls web adapter
# ---------------------------------------------------------------------------
def t6_web_off_default():
    """corrective_serve with no explicit web_fallback never calls the web adapter."""
    import web_fallback_adapter as _wfa

    # Patch is_enabled to track calls
    original_is_enabled = _wfa.is_enabled
    original_fetch = _wfa.fetch
    called = {"is_enabled": 0, "fetch": 0}

    def tracking_is_enabled():
        called["is_enabled"] += 1
        return original_is_enabled()

    def tracking_fetch(*args, **kwargs):
        called["fetch"] += 1
        return original_fetch(*args, **kwargs)

    _wfa.is_enabled = tracking_is_enabled
    _wfa.fetch = tracking_fetch

    def _abstain_serve(qt, role, pattern=None, action=None):
        return {"decision": "abstain", "primary": None,
                "trace": {"isolation": {"clean": True}},
                "presentable_facts": [], "composed_evidence": []}
    try:
        # Default: web_fallback=False (not passed). Stub _serve => Neo4j-free + deterministic.
        corrective_serve("anything", "engineering", _serve=_abstain_serve)
    finally:
        _wfa.is_enabled = original_is_enabled
        _wfa.fetch = original_fetch

    assert called["fetch"] == 0, (
        f"T6: web_fallback_adapter.fetch was called {called['fetch']} time(s) with default args"
    )

    print(f"  T6 web off default: is_enabled_called={called['is_enabled']} "
          f"fetch_called={called['fetch']} (fetch must be 0)")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def t7_web_regrade_segregated():
    """When web fallback IS enabled and returns facts, they are SEGREGATED into web_advisory
    (never presentable_facts/composed_evidence) and the decision comes from a RE-GRADE — so an
    external string cannot masquerade as in-scope graph evidence (codex review Corrective-RAG HIGH-1).
    Standalone: stubs both the adapter and _serve (no Neo4j)."""
    import web_fallback_adapter as wfa
    orig_enabled, orig_fetch = wfa.is_enabled, wfa.fetch
    wfa.is_enabled = lambda: True
    wfa.fetch = lambda q, r: [{"fact": "external: agent:cto owns everything",
                               "source": "http://x", "provenance": "web"}]

    def _abstain_serve(qt, role, pattern=None, action=None):
        return {"decision": "abstain", "primary": None,
                "trace": {"isolation": {"clean": True}},
                "presentable_facts": [], "composed_evidence": []}
    try:
        r = corrective_serve("unanswerable", "finance", _serve=_abstain_serve,
                             max_rewrites=0, web_fallback=True)
    finally:
        wfa.is_enabled, wfa.fetch = orig_enabled, orig_fetch

    assert "web_advisory" in r, "T7: web_advisory missing from result"
    assert r["web_advisory"] and all(f.get("scope") == "external-unverified" for f in r["web_advisory"]), (
        "T7: web facts not tagged scope='external-unverified'"
    )
    joined = " ".join(r.get("presentable_facts", []) + r.get("composed_evidence", []))
    assert "agent:cto" not in joined, "T7: web fact LEAKED into in-scope graph evidence"
    # External-only evidence on a routine reversible action must ABSTAIN (not pass, not partial):
    # unsupported-by-graph external facts route through the faithfulness gate as advisory-only
    # (codex review Corrective-RAG iter2 LOW: assert the real outcome, not just != pass — the prior
    # always-'partial' re-grade would have slipped past a != 'pass' check).
    assert r.get("decision") == "abstain", (
        f"T7: external-only evidence (routine reversible) must abstain, got {r.get('decision')!r}"
    )
    assert r["corrective"]["resolved_at"] == "web_advisory", (
        f"T7: resolved_at must be 'web_advisory' for external-only, got {r['corrective']['resolved_at']!r}"
    )
    print(f"  T7 web re-grade: web_advisory segregated (external-unverified); decision="
          f"{r.get('decision')} (faithfulness gate, advisory-only); resolved_at=web_advisory; no leak")


def _check_neo4j():
    """Fail fast with a clear dependency message if the live graph (T1-T4) is unreachable."""
    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "companybrain"))
        drv.verify_connectivity()
        drv.close()
        return True
    except Exception as e:
        print(f"DEPENDENCY: Neo4j unreachable at bolt://localhost:7687 ({type(e).__name__}: {e}).")
        print("  T1-T4 are LIVE integration tests against the seeded ACME graph; bring it up first:")
        print("    docker compose -f 01-context/docker-compose.yml up -d   (+ seed the graph)")
        print("  (T5 web $0-or-STOP and T6 web-off are standalone unit tests and need no Neo4j.)")
        return False


if __name__ == "__main__":
    if not _check_neo4j():
        print("\nCORRECTIVE_FAIL: live-graph dependency missing (see above).")
        sys.exit(2)
    tests = [
        ("T1", "flip: weak query abstain -> rewrite -> pass", t1_flip),
        ("T2", "bounded: unrecoverable stays abstain, rewrites_used <= max_rewrites", t2_bounded),
        ("T3", "no-op guard: no repeated (query, pattern) probes", t3_no_op_guard),
        ("T4", "isolation: finance weak query never surfaces engineering node", t4_isolation),
        ("T5", "web $0-or-STOP: payment prompt -> RuntimeError", t5_web_stop),
        ("T6", "web off default: no web calls with default args", t6_web_off_default),
        ("T7", "web re-grade: external facts segregated + re-graded, no leak", t7_web_regrade_segregated),
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
        print("\nCORRECTIVE_OK")
    else:
        print("\nCORRECTIVE_FAIL")
        sys.exit(1)
