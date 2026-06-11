"""CAL-2 (beads cb-hjv.3.3.2): REAL eRAG source weights over the validated golden set.

eRAG protocol (CONTEXT_EVALS §0/§2): each retrieved unit's value = how well that unit ALONE answers
the query vs ground truth — downstream utility, not relevance. Per the locked deterministic-first
rubric, utility here is computed DETERMINISTICALLY: a unit's answer-from-unit is its fact set
(node card = its long_context + current edges), and utility = the fraction of the item's
human-validated support_facts that the unit's card covers. No LLM in the scoring path -> $0,
reproducible, and immune to judge bias for this pass (the judge enters at CAL-3/CAL-4 where prose
matching genuinely needs discretion).

Sources scored separately (graph rung vs vector rung, both role-scoped), aggregated to per-source
mean utility -> normalized source weights. Null/abstain items are excluded from weights (nothing
should support them) but their retrieved units are reported as DISTRACTOR EXPOSURE (UDCG-flavored:
units that retrieval surfaced for an unanswerable question).
"""
import json
import os
import sys
from neo4j import GraphDatabase
from golden import read_golden
from scope import allowed_namespaces
import ladder

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
HERE = os.path.dirname(os.path.abspath(__file__))


def unit_card(s, key):
    """The unit's answer-from-unit material: its context + current outgoing edges."""
    rec = s.run(
        "MATCH (n:Entity {key:$k}) "
        "RETURN n.long_context AS ctx, "
        "  [(n)-[r:RELATES_TO]->(o) WHERE r.invalid_at IS NULL | [r.name, o.key]] AS edges",
        k=key).single()
    return {"ctx": rec["ctx"] or "", "edges": [tuple(e) for e in rec["edges"]]} if rec else None


def coverage(unit_key, card, support_facts):
    """Deterministic eRAG utility: fraction of the item's support facts this unit alone covers.
    A str fact (node key) is covered if the unit IS that node or links to it; an edge fact
    [s, rel, o] is covered if the unit is s and carries (rel, o)."""
    if not support_facts:
        return 0.0
    hit = 0
    targets = {o for _, o in card["edges"]}
    for f in support_facts:
        if isinstance(f, str):
            hit += 1 if (unit_key == f or f in targets) else 0
        else:
            s_, rel, o = f
            hit += 1 if (unit_key == s_ and (rel, o) in card["edges"]) else 0
    return round(hit / len(support_facts), 3)


def retrieve_units(s, item):
    """Role-scoped graph + vector units for the item's question. Graph patterns are derived from
    the item's support EDGES (rel+obj -> subjects), mirroring how serve() would pattern-match."""
    allowed = allowed_namespaces(item["role"])
    units = {}
    for f in item["support_facts"]:
        if isinstance(f, list):
            _, rel, obj = f
            for hit in ladder.graph_rung(s, allowed, {"rel": rel, "obj": obj}):
                units.setdefault(hit, set()).add("graph")
    for h in ladder.vector_rung(s, allowed, item["question"], k=3):
        units.setdefault(h["key"], set()).add("vector")
    return units


def main():
    fail = []
    items = read_golden(os.path.join(HERE, "example_golden.jsonl"))
    answerable = [i for i in items if i["expected_decision"] == "pass"]
    nulls = [i for i in items if i["expected_decision"] == "abstain"]

    per_source = {"graph": [], "vector": []}
    rows, distractors = [], []
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        for it in answerable:
            units = retrieve_units(s, it)
            for key, sources in sorted(units.items()):
                card = unit_card(s, key)
                u = coverage(key, card, it["support_facts"])
                for src in sources:
                    per_source[src].append(u)
                rows.append((it["id"], key, "+".join(sorted(sources)), u))
        for it in nulls:                                  # distractor exposure on abstain probes
            units = retrieve_units(s, it)
            distractors.append((it["id"], sorted(units)))

    print("[units]   per-unit deterministic eRAG utility (item, unit, source, coverage):")
    for r in rows:
        print(f"            {r[0]:8} {r[1]:14} {r[2]:12} {r[3]}")
    means = {src: round(sum(v) / len(v), 4) for src, v in per_source.items() if v}
    tot = sum(means.values()) or 1.0
    weights = {src: round(m / tot, 4) for src, m in means.items()}
    print(f"[eRAG]    per-source mean utility={means} -> normalized SOURCE WEIGHTS={weights}")
    print(f"[noise]   distractor exposure on null probes: "
          f"{[(d[0], len(d[1])) for d in distractors]} (units surfaced for unanswerable questions)")

    fail += [] if (per_source["graph"] and per_source["vector"]) else ["a source produced no units"]
    fail += [] if weights.get("graph", 0) > weights.get("vector", 0) else \
        ["graph (fact-authority) should outweigh vector (recall) on a fact-lookup golden set"]

    out = {"per_unit": rows, "source_means": means, "source_weights": weights,
           "distractor_exposure": {d[0]: d[1] for d in distractors},
           "method": "deterministic coverage eRAG (no LLM in scoring path)", "n_items": len(answerable)}
    with open(os.path.join(HERE, "cal2_erag_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"[write]   cal2_erag_results.json ({len(rows)} unit scores, {len(answerable)} items)")

    if fail:
        print("CAL2_FAIL:", fail); sys.exit(1)
    print("CAL2_OK")


if __name__ == "__main__":
    main()
