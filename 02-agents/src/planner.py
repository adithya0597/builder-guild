"""Agentic RAG planner loop (G1).

Interface:
    plan(question, role, *, max_steps=4, tau=0.5, _serve=None) -> dict

Bounded loop: each step reads the signal from the PRIOR step's serve() result and
CHOOSES the next retrieval mode based on that signal (agentic core). Reuses
corrective's extraction helpers and abstain.selective_score to derive confidence
when gate_abstain.score is absent (early-abstain path).

Pure python / $0 / local. NO env reads, NO model/external API calls; the default path opens
a LOCAL Neo4j connection via serve() (inject _serve to avoid it — tests need no Neo4j).

Return shape:
    {
        ...serve fields on the terminating step...,
        "planner": {
            "steps": [{
                "step": int,
                "query_chosen": str,
                "pattern_chosen": dict|None,
                "retrieval_mode": str,
                "why": str,
                "confidence_signal": {
                    "decision": str,
                    "score": float|None,
                    "sufficiency": float|None,
                    "self_confidence": float|None,
                    "basis": str|None,
                },
                "isolation_clean": bool,
            }, ...],
            "distinct_retrievals": int,
            "terminated_on": "confidence" | "escalate" | "confident_abstain" | "abstain" | "max_steps",
            # "confidence"        = genuine answer (decision in pass/partial)
            # "escalate"          = gate routed to a human (decision=escalate); NOT an answer
            # "confident_abstain" = score>=tau but still abstaining (NOT a real answer)
            # "abstain"           = no fresh probe left / final step still abstaining
            # "max_steps"         = hit max_steps on a non-abstain non-answer state
            "steps_used": int,
            "max_steps": int,
        }
    }
"""
import re
import sys

# Reuse corrective's extraction helpers. Import-time sys.path.insert follows the repo's
# cross-layer module convention (mirrors eval_corrective.py / cal3_fit.py / demo_agent.py).
sys.path.insert(0, __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    "..", "..", "01-context", "src"))

from corrective import _extract_ids, _extract_verb_rel, _split_ids_by_verb


def _probe_key(query, pattern):
    """Canonical no-op guard key matching corrective's convention."""
    pt_key = None if pattern is None else tuple(sorted(pattern.items()))
    return (query, pt_key)


def _read_confidence(r, tau):
    """Extract (decision, conf, sufficiency, self_confidence, basis) from a serve() result.

    Handles both the normal path (gate_abstain present) and the early-abstain path
    (no gate_abstain, no trace.isolation — serve returns early on no-retrieval).
    When score is absent, derives it via abstain.selective_score so the comparison
    against tau is always on the same scale.
    """
    from abstain import selective_score

    g = r.get("trace", {}).get("gate_abstain", {})
    decision = g.get("final", r.get("decision", "abstain"))
    score = g.get("score")
    suf = g.get("sufficiency")
    self_conf = g.get("self_confidence")
    basis = g.get("confidence_basis") or g.get("basis")

    if score is None and suf is not None and self_conf is not None:
        score = round(selective_score(suf, self_conf), 4)
        basis = basis or "derived:selective_score"

    return decision, score, suf, self_conf, basis


def _neighbor_keys(r):
    """Pull 1-hop neighbor keys from presentable_facts and composed_evidence (mirrors corrective)."""
    seen = set()
    keys = []
    for fact in r.get("presentable_facts", []):
        m = re.search(r"->\s*(\S+)", fact)
        if m:
            nk = m.group(1)
            if nk not in seen:
                seen.add(nk)
                keys.append(nk)
    for line in r.get("composed_evidence", []):
        for nk in re.findall(r"\b(?:issue|agent):[A-Za-z0-9_-]+", line):
            if nk not in seen:
                seen.add(nk)
                keys.append(nk)
    return keys


def _has_facts(r):
    """RETRIEVED SUPPORT signal only — presentable_facts are the SUPPORTED graph edges.
    composed_evidence is the composed answer NARRATIVE (content cards + facts widened for
    presentation), NOT a branch-selection signal. An UNSUPPORTED abstain (primary has no
    outgoing edges -> presentable_facts=[]) must route to Branch 1 (structural re-aim), even
    though serve() will have populated composed_evidence with content cards."""
    return bool(r.get("presentable_facts"))


def _choose_next(question, current_query, current_pattern, step_result, tried):
    """Signal-driven policy switch (the agentic core).

    Reads THIS step's signal from step_result and returns
    (next_query, next_pattern, retrieval_mode, why) for the next step,
    or (None, None, None, None) when no fresh probe remains.

    Policy (only reachable on a non-terminating step, i.e. decision=='abstain' —
    plan() terminates on pass/partial/escalate before _choose_next is ever called):
    1. abstain via UNSUPPORTED / no facts → structural re-aim: ids + verb→rel graph probe.
    2. abstain WITH facts → neighbor-hop: pull 1-hop targets, re-query.
    3. low sufficiency (<0.34) with some recall → decompose the question.
    Skips any probe already in `tried`.
    """
    g = step_result.get("trace", {}).get("gate_abstain", {})
    decision = g.get("final", step_result.get("decision", "abstain"))
    suf = g.get("sufficiency")
    has_facts = _has_facts(step_result)

    # Branch 1: no RETRIEVED facts (UNSUPPORTED abstain) — structural re-aim.
    # Tactic ORDER mirrors corrective's proven t1_flip: id_extract FIRST (a clean re-query
    # on just the id tokens, which lets RRF re-rank to a node WITH outgoing edges -> pass),
    # then the verb->relation graph_pattern probes as the structural fallback.
    if not has_facts:
        ids = _extract_ids(current_query or "")
        # Tactic 1: id_extract — re-query with only the extracted ids, pattern=None
        if ids:
            nq = " ".join(ids)
            pk = _probe_key(nq, None)
            if pk not in tried:
                return nq, None, "id_extract", f"no facts: re-query with extracted ids={ids}"
        # Tactic 2: graph_pattern — verb->relation + object-key structural probe
        rel, verb_tok = _extract_verb_rel(current_query or "")
        if rel and ids:
            after, before = _split_ids_by_verb(current_query or "", verb_tok, ids)
            for obj_id in (after + before):
                obj = obj_id if ":" in obj_id else f"issue:{obj_id}"
                pat = {"rel": rel, "obj": obj}
                pk = _probe_key("", pat)
                if pk not in tried:
                    return "", pat, "graph_pattern", f"no facts: structural re-aim rel={rel} obj={obj}"

    # Branch 2: has facts, still abstain — neighbor-hop. (partial is unreachable here:
    # plan() terminates on partial before _choose_next runs, so abstain-only is correct.)
    if has_facts and decision == "abstain":
        neighbors = _neighbor_keys(step_result)
        if neighbors:
            nq = (question + " " + " ".join(neighbors[:3])).strip()
            pk = _probe_key(nq, current_pattern)
            if pk not in tried:
                return nq, current_pattern, "neighbor_hop", (
                    f"has facts but {decision}: neighbor-hop on {neighbors[:3]}"
                )

    # Branch 3: low sufficiency with some recall — decompose
    if suf is not None and suf < 0.34 and has_facts:
        sub_queries = re.split(r"\band\b|,", question, flags=re.I)
        for sub in sub_queries:
            from corrective import _STOPWORDS
            tokens = [t for t in sub.lower().split() if t not in _STOPWORDS and len(t) > 2]
            if tokens:
                core = " ".join(tokens[:6])
                if core and core.lower() != (current_query or "").lower():
                    pk = _probe_key(core, None)
                    if pk not in tried:
                        return core, None, "decompose", f"low sufficiency ({suf}): decompose sub-query"

    return None, None, None, None


def plan(question, role, *, max_steps=4, tau=0.5, _serve=None):
    """Agentic RAG planner loop.

    Bounded to max_steps iterations. Each step reads THIS step's signal and
    CHOOSES the next retrieval mode from it (not a fixed script). Injectable
    _serve for test isolation (no Neo4j needed in tests).
    """
    if _serve is None:
        from serve import serve as _serve_fn
        _serve = _serve_fn

    steps = []
    tried = set()
    current_query = question
    current_pattern = None
    retrieval_mode = "initial"
    why = "initial query"
    terminated_on = "max_steps"
    final_result = None

    for step in range(1, max_steps + 1):
        pk = _probe_key(current_query, current_pattern)
        tried.add(pk)

        r = _serve(current_query, role, pattern=current_pattern)
        final_result = r

        # Isolation assert EVERY step. A MISSING trace.isolation is acceptable ONLY for the
        # genuine early-abstain shape (serve() returns before the isolation self-check on
        # no-retrieval: no primary, no presentable_facts, no composed_evidence). If isolation
        # is missing but the result retrieved SOMETHING, the result is malformed/suspicious —
        # do NOT default it clean (a real leak would slip through). Raise instead.
        trace = r.get("trace", {})
        has_iso = "isolation" in trace
        retrieved_something = bool(
            r.get("primary") or r.get("presentable_facts") or r.get("composed_evidence")
        )
        if not has_iso:
            if retrieved_something:
                raise AssertionError(
                    f"isolation missing at planner step {step} but result retrieved "
                    f"(primary={r.get('primary')!r}, "
                    f"n_facts={len(r.get('presentable_facts') or [])}, "
                    f"n_evidence={len(r.get('composed_evidence') or [])}); "
                    f"refusing to default clean on a non-early-abstain result"
                )
            iso_clean = True  # genuine early-abstain: nothing retrieved, nothing to leak
        else:
            iso = trace["isolation"]
            iso_clean = iso.get("clean", False)
            if not iso_clean:
                leaked = iso.get("leaked", [])
                raise AssertionError(
                    f"isolation violated at planner step {step}: leaked={leaked}"
                )

        decision, score, suf, self_conf, basis = _read_confidence(r, tau)

        step_record = {
            "step": step,
            "query_chosen": current_query,
            "pattern_chosen": current_pattern,
            "retrieval_mode": retrieval_mode,
            "why": why,
            "confidence_signal": {
                "decision": decision,
                "score": score,
                "sufficiency": suf,
                "self_confidence": self_conf,
                "basis": basis,
            },
            "isolation_clean": iso_clean,
        }
        steps.append(step_record)

        # Termination, honestly labeled:
        #   - a GENUINE answer (pass/partial)         -> "confidence"
        #   - escalate (gate routed to a human)       -> "escalate"  (NOT an answer)
        #   - score>=tau while still abstaining       -> "confident_abstain" (NOT an answer)
        # escalate terminates the loop (no point re-probing a human-routed decision) but is
        # never dishonestly counted as a confident answer.
        answered = decision in ("pass", "partial")
        score_stop = score is not None and score >= tau
        if answered:
            terminated_on = "confidence"
            break
        if decision == "escalate":
            terminated_on = "escalate"
            break
        if score_stop:
            terminated_on = "confident_abstain"
            break

        if step == max_steps:
            terminated_on = "abstain" if decision == "abstain" else "max_steps"
            break

        # Choose next retrieval FROM THIS STEP'S SIGNAL (agentic core)
        nq, npat, nmode, nwhy = _choose_next(
            question, current_query, current_pattern, r, tried
        )
        if nq is None and npat is None:
            # No fresh probe available — bounded exit
            terminated_on = "abstain"
            break

        current_query = nq
        current_pattern = npat
        retrieval_mode = nmode
        why = nwhy

    # distinct_retrievals: count unique (retrieval_mode, normalized probe) pairs. Uses the
    # SAME canonical _probe_key as the no-op guard so trivial formatting variants of a
    # pattern dict (key order, str() spacing) cannot inflate the count.
    distinct_retrievals = len({
        (s["retrieval_mode"], _probe_key(s["query_chosen"], s["pattern_chosen"]))
        for s in steps
    })

    result = dict(final_result) if final_result else {}
    result["planner"] = {
        "steps": steps,
        "distinct_retrievals": distinct_retrievals,
        "terminated_on": terminated_on,
        "steps_used": len(steps),
        "max_steps": max_steps,
    }
    return result
