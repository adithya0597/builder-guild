"""GT-2 (beads cb-hjv.5.2): auto-DRAFT the V0 golden set from the live eng+fin graph slice.

The hybrid the literature mandates (CONTEXT_EVALS §0/§4; web-search 2026-06-05: synthetic-only
fails, public-trained-on Q&A is contamination-poisoned): an LLM drafts, a HUMAN validates. Here the
"LLM" is the Claude agent authoring the question phrasings at $0 (subscription, no external paid
call); the candidate answers + support-fact sets are pulled DETERMINISTICALLY from the live graph so
every draft is grounded and reproducible.

NO FABRICATION: a draft's `correct_answer` is left "" and `validated=False`. The graph-derived guess
goes in a SEPARATE `candidate_answer` field clearly marked CANDIDATE. The human (GT-5, cb-hjv.5.3)
confirms/corrects it into `correct_answer` and flips `validated`. The agent never asserts an
unvalidated answer as ground truth and never closes GT-5.

Output:
  example_golden.jsonl       — the drafts (machine format, golden.py schema)
  golden_v0_review.md   — the human review sheet for Adithya (question, candidate, support-facts)
"""
import os
import sys
from neo4j import GraphDatabase
from golden import normal_item, null_item, temporal_item, validate_item, write_golden, read_golden

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
HERE = os.path.dirname(os.path.abspath(__file__))


def _slice(s):
    """Pull the eng+fin slice as {key: {ns, ctx, status, assignee, blocks}} from live data."""
    rows = s.run(
        "MATCH (n:Entity) WHERE n.namespace IN ['engineering','finance'] "
        "RETURN n.key AS k, n.namespace AS ns, n.long_context AS ctx, "
        "  [(n)-[r:RELATES_TO]->(o) WHERE r.invalid_at IS NULL | [r.name, o.key]] AS edges").data()
    g = {}
    for r in rows:
        ctx = r["ctx"] or ""
        status = next((p.split("=", 1)[1] for p in ctx.replace(".", " ").replace(",", " ").split() if p.startswith("status=")), None)
        assignee = next((o for nm, o in r["edges"] if nm == "ASSIGNED_TO"), None)
        blocks = [o for nm, o in r["edges"] if nm == "BLOCKS"]
        g[r["k"]] = {"ns": r["ns"], "ctx": ctx, "status": status, "assignee": assignee, "blocks": blocks}
    return g


def draft(g):
    """Author the V0 drafts. Each candidate_answer is BUILT from `g` (live graph), not hand-typed."""
    items = []

    def add(it, candidate):
        it["candidate_answer"] = candidate     # extra field; human moves -> correct_answer at GT-5
        items.append(it)

    # ---- NORMAL: single-hop (RAGAS ~50%) ----
    add(normal_item("eng-s1", "engineering", "Who is issue SPI-2 (rate-limit backoff for Hermes "
                    "inference) assigned to?", "single",
                    ["issue:SPI-2", ["issue:SPI-2", "ASSIGNED_TO", g["issue:SPI-2"]["assignee"]]],
                    "GT-2 auto-draft"), f"CANDIDATE: {g['issue:SPI-2']['assignee']}")
    add(normal_item("eng-s2", "engineering", "What is the current status of SPI-2?", "single",
                    ["issue:SPI-2"], "GT-2 auto-draft"), f"CANDIDATE: status={g['issue:SPI-2']['status']}")
    add(normal_item("fin-s1", "finance", "Who owns the Q3 inference budget-cap issue (SPI-4)?",
                    "single", ["issue:SPI-4", ["issue:SPI-4", "ASSIGNED_TO", g["issue:SPI-4"]["assignee"]]],
                    "GT-2 auto-draft"), f"CANDIDATE: {g['issue:SPI-4']['assignee']}")
    add(normal_item("fin-s2", "finance", "What does SPI-5 forecast?", "single", ["issue:SPI-5"],
                    "GT-2 auto-draft"), f"CANDIDATE (from ctx): {g['issue:SPI-5']['ctx']}")

    # ---- NORMAL: multi_specific (RAGAS ~25%) — needs >1 fact ----
    sp2 = g["issue:SPI-2"]
    add(normal_item("eng-m1", "engineering", "What issue does SPI-2 block, and who is that blocked "
                    "issue assigned to?", "multi_specific",
                    [["issue:SPI-2", "BLOCKS", sp2["blocks"][0]],
                     [sp2["blocks"][0], "ASSIGNED_TO", g[sp2["blocks"][0]]["assignee"]]],
                    "GT-2 auto-draft"),
        f"CANDIDATE: blocks {sp2['blocks'][0]}, owned by {g[sp2['blocks'][0]]['assignee']}")

    # ---- NORMAL: multi_abstract (RAGAS ~25%) — aggregate over the slice ----
    blocked_eng = sorted(k for k, v in g.items() if v["ns"] == "engineering" and v["status"] == "blocked")
    add(normal_item("eng-a1", "engineering", "Which engineering issues are currently blocked?",
                    "multi_abstract", blocked_eng, "GT-2 auto-draft"),
        f"CANDIDATE: {', '.join(blocked_eng)}")
    fin_ip = sorted(k for k, v in g.items() if v["ns"] == "finance" and v["status"] == "in_progress")
    add(normal_item("fin-a1", "finance", "What in-progress finance work targets cost control?",
                    "multi_abstract", fin_ip, "GT-2 auto-draft"),
        f"CANDIDATE: {', '.join(fin_ip)} ({'; '.join(g[k]['ctx'][:60] for k in fin_ip)})")

    # ---- NULL: abstain probes (§4.4) ----
    # (a) cross-role leakage: an ENGINEERING role asks a FINANCE-only fact -> must abstain, never surface finance
    add(null_item("null-xrole", "engineering", "What is the exact Q3 inference budget cap dollar "
                  "amount?", ["finance"], "GT-2 auto-draft"),
        "CANDIDATE: abstain (budget cap is a finance fact; engineering role must NOT surface it)")
    # (b) answer-not-in-KB
    add(null_item("null-absent", "engineering", "Who is the VP of Sales?", [], "GT-2 auto-draft"),
        "CANDIDATE: abstain (no such entity in the KB)")

    # ---- TEMPORAL: as-of probe (§4.5) ----
    # NB: the live V0 slice has NO historical/superseded edges, so this is a PLACEHOLDER that needs a
    # seeded supersession episode to become a real as-of test. Flagged for the human, not asserted.
    add(temporal_item("tmp-1", "finance", "Who owned SPI-4 as of 2026-05-01?", "2026-05-01T00:00:00",
                      ["issue:SPI-4", ["issue:SPI-4", "ASSIGNED_TO", g["issue:SPI-4"]["assignee"]]],
                      "GT-2 auto-draft [PLACEHOLDER: needs seeded supersession episode — no historical "
                      "edge exists in V0 slice]"),
        f"CANDIDATE: {g['issue:SPI-4']['assignee']} (NO supersession in KB yet -> seed an episode to make this a real as-of test)")

    return items


def write_review(items, path):
    lines = ["# golden_v0_review.md — V0 golden set awaiting human validation (GT-5 / cb-hjv.5.3)",
             "",
             "> Auto-drafted by GT-2 (cb-hjv.5.2) from the live engineering+finance graph slice. Each",
             "> item's `candidate_answer` is GRAPH-DERIVED but UNVALIDATED. **Adithya:** for each item,",
             "> confirm or correct the candidate, then set `correct_answer` + `validated=true` in",
             "> `example_golden.jsonl`. Do not trust a candidate until you've checked it against the graph.",
             "", f"**{len(items)} drafts** | "
             f"normal={sum(1 for i in items if i['kind']=='normal')} "
             f"null={sum(1 for i in items if i['kind']=='null')} "
             f"temporal={sum(1 for i in items if i['kind']=='temporal')}", ""]
    for i in items:
        lines += [f"## {i['id']}  ·  role={i['role']}  ·  kind={i['kind']}  ·  hop={i['hop_type']}",
                  f"- **Q:** {i['question']}",
                  f"- **candidate (unvalidated):** {i['candidate_answer']}",
                  f"- **support_facts:** `{i['support_facts']}`",
                  f"- **expected_decision:** {i['expected_decision']}" +
                  (f"  ·  **forbidden_namespaces:** {i['forbidden_namespaces']}" if i['kind'] == 'null' else ""),
                  "- **[ ] validated** → set `correct_answer` + `validated=true`", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def main():
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        g = _slice(s)
    items = draft(g)

    # 1) every draft is schema-valid
    for it in items:
        ok, errs = validate_item(it)
        if not ok:
            fail.append(f"{it['id']} invalid: {errs}")
    print(f"[valid]   {len(items)} drafts, all schema-valid: {not fail}")

    # 2) NO FABRICATION: every draft has correct_answer=='' and validated==False
    unval = all(it["correct_answer"] == "" and it["validated"] is False for it in items)
    print(f"[no-fab]  all correct_answer=='' and validated=False: {unval}")
    fail += [] if unval else ["a draft has a pre-filled/validated answer (fabrication)"]

    # 3) coverage: RAGAS hop mix + null + temporal probes present
    kinds = {k: sum(1 for i in items if i["kind"] == k) for k in ("normal", "null", "temporal")}
    hops = {h: sum(1 for i in items if i["kind"] == "normal" and i["hop_type"] == h)
            for h in ("single", "multi_abstract", "multi_specific")}
    print(f"[cover]   kinds={kinds} normal-hop-mix={hops}")
    fail += [] if (kinds["normal"] >= 5 and kinds["null"] >= 2 and kinds["temporal"] >= 1
                   and all(hops.values())) else ["coverage gap (need >=5 normal w/ all hop types, >=2 null, >=1 temporal)"]

    # 4) every support_fact references a REAL slice node (grounded, no hallucinated keys)
    real = set(g)
    def fact_keys(f):
        return [f] if isinstance(f, str) else [f[0], f[2]]
    bad_refs = [(it["id"], k) for it in items if it["kind"] != "null"
                for f in it["support_facts"] for k in fact_keys(f) if k not in real]
    print(f"[ground]  support_facts referencing non-slice nodes: {bad_refs if bad_refs else 'NONE'}")
    fail += [] if not bad_refs else [f"ungrounded support_facts: {bad_refs}"]

    # write artifacts
    jpath = write_golden(items, os.path.join(HERE, "example_golden.jsonl"))
    rpath = write_review(items, os.path.join(HERE, "golden_v0_review.md"))
    back = read_golden(jpath)
    print(f"[write]   {os.path.basename(jpath)} ({len(back)} items) + {os.path.basename(rpath)}")
    fail += [] if len(back) == len(items) else ["jsonl write/read count mismatch"]

    if fail:
        print("GT2_FAIL:", fail); sys.exit(1)
    print("GT2_OK")


if __name__ == "__main__":
    main()
