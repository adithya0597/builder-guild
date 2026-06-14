"""Corrective-RAG recovery loop (beads cb-k97.1).

Wraps serve.serve(): grade -> if abstain, rewrite the query + re-retrieve (bounded)
-> optional web fallback. Pure-python deterministic rewrites, $0/local. No model calls.

Interface:
    corrective_serve(query_text, role, pattern=None, action=None, *,
                     max_rewrites=2, web_fallback=False, _serve=None) -> dict

The returned dict is serve()'s dict plus a 'corrective' key:
    corrective = {
        "attempted": [{"tactic": str, "query": str, "pattern": dict|None, "decision": str}],
        "resolved_at": "initial" | "rewrite:<tactic>" | "web" | "exhausted",
        "rewrites_used": int,
        "web_fallback": bool,
    }

Recovery triggers ONLY on decision == "abstain". pass/partial/escalate terminate immediately.
Loop is provably bounded: at most max_rewrites distinct probes; no-op guard (tried set).
Namespace isolation is preserved: every re-retrieve is role-scoped via serve(); isolation
self-check runs inside serve() on every call; we assert trace.isolation.clean each iteration.
"""
import re
import sys

# ONTOLOGY verb -> relation map (spec §4 / ONTOLOGY_SCHEMA §6)
_VERB_REL = {
    "block": "BLOCKS",
    "blocks": "BLOCKS",
    "blocking": "BLOCKS",
    "depend": "DEPENDS_ON",
    "depends": "DEPENDS_ON",
    "depending": "DEPENDS_ON",
    "own": "OWNS",
    "owns": "OWNS",
    "assign": "ASSIGNED_TO",
    "assigns": "ASSIGNED_TO",
    "assigned": "ASSIGNED_TO",
}

# Stopwords for decompose tactic
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "about", "into", "through", "during", "what", "which", "who", "when",
    "where", "how", "that", "this", "these", "those", "it", "its",
    "there", "then", "they", "their", "we", "our", "you", "your",
    "and", "or", "but", "if", "while", "as", "up", "out", "no", "not",
    "so", "yet", "both", "either", "neither", "than", "too", "very",
    "just", "here", "some", "such", "get", "all", "any",
})

# ID-like token patterns: [A-Za-z]+-\d+, issue:…, agent:…
_ID_RE = re.compile(
    r"(?:issue:|agent:)[A-Za-z0-9_-]+|[A-Za-z]+-\d+"
)


def _extract_ids(text):
    """Extract ID-like tokens from query text. Returns list, preserving order seen."""
    seen = set()
    out = []
    for tok in _ID_RE.findall(text):
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _extract_verb_rel(text):
    """Map first verb-match in text to an ONTOLOGY relation. Returns (rel, None) or (None, None)."""
    tokens = text.lower().split()
    for tok in tokens:
        tok_clean = tok.rstrip("s")
        if tok in _VERB_REL:
            return _VERB_REL[tok], tok
        if tok_clean in _VERB_REL:
            return _VERB_REL[tok_clean], tok
    return None, None


def _split_ids_by_verb(text, verb_tok, ids):
    """Partition extracted ids into (after_verb, before_verb) by the verb token's char position.
    graph_rung matches (subj)-[rel]->(obj {key}) and returns subjects, so the relation's OBJECT is
    conventionally the id AFTER the verb ("X blocks Y" -> obj=Y). Callers try after-verb ids first
    (codex review cb-k97.1: don't blindly try the subject as the object)."""
    if not verb_tok:
        return list(ids), []
    vpos = text.lower().find(verb_tok.lower())
    if vpos < 0:
        return list(ids), []
    after, before = [], []
    for tok in ids:
        (after if text.find(tok) > vpos else before).append(tok)
    return after, before


def _build_rewrites(query_text, pattern, prior_result):
    """Yield (tactic_name, new_query_text, new_pattern) in order per spec §4.
    Does NOT apply the no-op guard; caller does that.
    """
    # Tactic 1: id_extract — regex ID-like tokens; re-serve with just the IDs
    ids = _extract_ids(query_text or "")
    if ids:
        new_q = " ".join(ids)
        yield "id_extract", new_q, None

    # Tactic 2: pattern_synth — verb->relation + extracted object key.
    # Pass query_text='' so serve() skips keyword/vector and uses ONLY graph_rung with the
    # structural pattern. This avoids keyword noise from the original query overwhelming
    # the graph hit in RRF (the lexical-trap the keyword rung is designed to fix, but in
    # reverse: having SPI-X in the original query text re-introduces the trap).
    rel, verb_tok = _extract_verb_rel(query_text or "")
    if rel:
        # Positional subject/object inference (codex review cb-k97.1): the relation's OBJECT is the
        # id AFTER the verb. Try after-verb ids first, before-verb as fallback. Skip if no ids (an
        # empty-obj pattern never matches and would just waste a probe against max_rewrites).
        ids = _extract_ids(query_text or "")
        after, before = _split_ids_by_verb(query_text or "", verb_tok, ids)
        for obj_id in (after + before):
            obj = obj_id if ":" in obj_id else f"issue:{obj_id}"
            # Empty query_text => only graph_rung fires => clean structural match
            yield "pattern_synth", "", {"rel": rel, "obj": obj}

    # Tactic 3: neighbor_expand — pull 1-hop neighbor keys from prior result's presentable_facts
    if prior_result:
        neighbor_keys = []
        seen_nb = set()
        for fact in prior_result.get("presentable_facts", []):
            m = re.search(r"->\s*(\S+)", fact)
            if m:
                nk = m.group(1)
                if nk not in seen_nb:
                    seen_nb.add(nk)
                    neighbor_keys.append(nk)
        # Also check composed_evidence for neighbor keys
        for line in prior_result.get("composed_evidence", []):
            for nk in re.findall(r"\b(?:issue|agent):[A-Za-z0-9_-]+", line):
                if nk not in seen_nb:
                    seen_nb.add(nk)
                    neighbor_keys.append(nk)
        if neighbor_keys:
            expanded = (query_text or "") + " " + " ".join(neighbor_keys[:3])
            yield "neighbor_expand", expanded.strip(), pattern

    # Tactic 4: decompose — strip stopwords / split on "and" / ","
    if query_text:
        sub_queries = re.split(r"\band\b|,", query_text, flags=re.I)
        for sub in sub_queries:
            tokens = [t for t in sub.lower().split() if t not in _STOPWORDS and len(t) > 2]
            if tokens:
                core = " ".join(tokens[:6])
                if core and core.lower() != (query_text or "").lower():
                    yield "decompose", core, pattern


def corrective_serve(query_text, role, pattern=None, action=None, *,
                     max_rewrites=2, web_fallback=False, _serve=None):
    """Corrective-RAG loop wrapping serve.serve().

    _serve is injectable for tests (defaults to serve.serve).
    Returns serve()'s dict plus a 'corrective' key (see module docstring).
    Recovery triggers ONLY on decision == 'abstain'.
    pass / partial / escalate terminate immediately.
    Loop is bounded: at most max_rewrites distinct probes; no-op guard via tried set.
    """
    if _serve is None:
        import serve as _serve_mod
        _serve = _serve_mod.serve

    attempted = []
    tried = set()  # no-op guard: (query_text, pattern_key)

    def _probe_key(qt, pt):
        pt_key = None if pt is None else tuple(sorted(pt.items()))
        return (qt, pt_key)

    # Initial attempt
    key0 = _probe_key(query_text, pattern)
    tried.add(key0)
    result = _serve(query_text, role, pattern=pattern, action=action)

    # Assert isolation clean
    if not result.get("trace", {}).get("isolation", {}).get("clean", True):
        leaked = result["trace"]["isolation"].get("leaked", [])
        raise AssertionError(f"isolation violated on initial probe: leaked={leaked}")

    decision = result.get("decision", "abstain")
    attempted.append({
        "tactic": "initial",
        "query": query_text,
        "pattern": pattern,
        "decision": decision,
        "isolation_clean": bool(result.get("trace", {}).get("isolation", {}).get("clean", True)),
    })

    # Union evidence across all probes — same role on every probe, so the union stays in-scope.
    # Lets answers that need evidence combined across decompose sub-queries surface even when no
    # single probe passes (codex review cb-k97.1: decompose must union, not first-hit-wins).
    union_facts = list(result.get("presentable_facts") or [])
    union_evidence = list(result.get("composed_evidence") or [])

    def _merge_evidence(res):
        for f in (res.get("presentable_facts") or []):
            if f not in union_facts:
                union_facts.append(f)
        for e in (res.get("composed_evidence") or []):
            if e not in union_evidence:
                union_evidence.append(e)

    # Early exit for non-abstain
    if decision != "abstain":
        result = dict(result)
        result["corrective"] = {
            "attempted": attempted,
            "resolved_at": "initial",
            "rewrites_used": 0,
            "web_fallback": False,
            "union_evidence": union_evidence,
        }
        return result

    # Recovery loop
    rewrites_used = 0
    resolved_at = "exhausted"
    final_result = result
    prior_result = result

    for tactic, new_query, new_pattern in _build_rewrites(query_text, pattern, prior_result):
        if rewrites_used >= max_rewrites:
            break

        pk = _probe_key(new_query, new_pattern)
        if pk in tried:
            # No-op guard: skip identical probes
            continue
        tried.add(pk)

        candidate = _serve(new_query, role, pattern=new_pattern, action=action)

        # Assert isolation clean on every iteration (spec: assert trace.isolation.clean)
        if not candidate.get("trace", {}).get("isolation", {}).get("clean", True):
            leaked = candidate["trace"]["isolation"].get("leaked", [])
            raise AssertionError(f"isolation violated on rewrite tactic={tactic}: leaked={leaked}")

        cand_decision = candidate.get("decision", "abstain")
        attempted.append({
            "tactic": tactic,
            "query": new_query,
            "pattern": new_pattern,
            "decision": cand_decision,
            "isolation_clean": bool(candidate.get("trace", {}).get("isolation", {}).get("clean", True)),
        })
        _merge_evidence(candidate)
        rewrites_used += 1

        if cand_decision != "abstain":
            # Resolved
            resolved_at = f"rewrite:{tactic}"
            final_result = candidate
            break

        # Update prior_result for neighbor_expand on next iteration
        prior_result = candidate

    # Web fallback (spec §5): only when web_fallback=True AND env CORRECTIVE_WEB_ENABLED=true.
    # CRITICAL (codex review cb-k97.1 HIGH-1): external web facts have NO namespace, so they are
    # NEVER merged into the role-scoped graph answer (presentable_facts/composed_evidence stay
    # graph-only). They are segregated into web_advisory (tagged external) and RE-GRADED through the
    # same gate, so the decision is honest and an out-of-namespace string can never masquerade as
    # in-scope graph evidence.
    if resolved_at == "exhausted" and web_fallback:
        import web_fallback_adapter as _wfa
        if _wfa.is_enabled():
            web_facts = _wfa.fetch(query_text, role)        # raises on $0-or-STOP; never swallow
            if web_facts:
                import abstain as _abstain
                act = action or {"category": "routine", "reversible": True}
                # External web facts have NO in-graph support -> UNSUPPORTED under the faithfulness
                # contract. Re-grade through the SAME gate: routine reversible -> abstain, risky ->
                # escalate. External evidence is advisory; it NEVER autonomously resolves an in-scope
                # query. (codex review cb-k97.1 iter2: a PARTIAL re-grade was hollow — stage_a_decision
                # short-circuits PARTIAL to 'partial' BEFORE the sufficiency x confidence logistic, so
                # supplied suf/conf were dead. UNSUPPORTED routes through the faithfulness gate, which
                # decides by reversibility — suf/conf are correctly irrelevant on this path.)
                web_claims = [{"id": f.get("fact", ""), "support_status": "UNSUPPORTED",
                               "stale": False, "conflict": False} for f in web_facts]
                regrade = _abstain.stage_a_decision(web_claims, act, sufficiency=0.0, self_confidence=0.0)
                final_result = dict(final_result)
                final_result["web_advisory"] = [{**f, "scope": "external-unverified"} for f in web_facts]
                final_result["web_advisory_note"] = ("EXTERNAL web facts: NOT namespace-scoped, "
                                                     "advisory only — never in-scope graph evidence")
                final_result["decision"] = regrade["final"]    # abstain (routine) / escalate (risky)
                resolved_at = "web_advisory"                   # external advisory present, not an authoritative resolution

    final_result = dict(final_result)
    final_result["corrective"] = {
        "attempted": attempted,
        "resolved_at": resolved_at,
        "rewrites_used": rewrites_used,
        "web_fallback": resolved_at == "web_advisory",
        "union_evidence": union_evidence,
    }
    return final_result


if __name__ == "__main__":
    import json
    query = "what is blocking the sprint"
    role = "engineering"
    print(f"[corrective] query={query!r} role={role}")
    r = corrective_serve(query, role)
    c = r["corrective"]
    print(f"  resolved_at={c['resolved_at']}  decision={r.get('decision')}  rewrites_used={c['rewrites_used']}")
    for a in c["attempted"]:
        print(f"  tactic={a['tactic']}  query={a['query']!r}  decision={a['decision']}")
    if r.get("primary"):
        print(f"  primary={r['primary']}  facts={r.get('presentable_facts', [])}")
