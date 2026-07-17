"""GT-V1-DRAFT (G3): 9-persona machine-draft of the V1 golden set, graph-grounded.

Rewrite of the original 6-namespace placeholder draft (that version hardcoded dead nodes
issue:ACME-3/5/6/7/8 that no seed creates, and targeted 6 role namespaces instead of the 9
founder personas). This version drafts ONLY from entities/edges verified live against
bg-neo4j (read-only Cypher, MATCH/RETURN only) and maps all 9 founder personas onto the 3
role namespaces that actually have live entities: engineering (engineer/architect/cloud/QA),
finance (PM), governance (CXO/security/red-team/blue-team -- reads ALL namespaces per
scope.ROLE_NAMESPACES, so it also hosts the audit / out-of-KB abstain probes). operations/
product/market have zero live entities and no persona routes there.

Founder decision 1: for STRUCTURAL items (an id/edge/enum answer directly derivable from
support_facts) correct_answer IS populated with the machine-derived answer -- validated stays
False regardless (no self-grading; a human still signs off at the GT-5 gate). Prose/interpretive
answers stay correct_answer="" (no candidate_answer field -- that was never part of
golden.GOLDEN_SCHEMA, it was this file's own ad hoc bolt-on for the old review sheet).

Adds the gate validate_item() cannot provide (it's structural-only): a live graph-existence
check that every non-abstain support_fact actually resolves against bg-neo4j, matching edges
on the `name` PROPERTY (every real edge is Cypher-typed RELATES_TO -- the semantic label lives
in `name`, never in the Cypher type).

Output:
  03-evals/src/golden_v1_draft.jsonl  -- the drafts (golden.py schema)
  03-evals/golden_v1_review.md        -- the human review sheet (founder fills in)
"""
import json
import os
import sys

from neo4j import GraphDatabase

# 01-context/src must be on path to import golden
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

from golden import (normal_item, null_item, temporal_item, validate_item,
                    write_golden, read_golden)

HERE = os.path.dirname(os.path.abspath(__file__))
# Output paths relative to repo layout
DRAFT_JSONL = os.path.join(HERE, "golden_v1_draft.jsonl")
REVIEW_MD   = os.path.join(HERE, "..", "golden_v1_review.md")

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))

TS_ACME1_OPEN = "2026-06-14T00:30:00"  # inside ACME-1's HAS_STATUS open window (00:00 -> 01:00, then superseded)


def node_exists(session, key):
    return session.run("MATCH (n:Entity {key:$k}) RETURN count(n) AS c", k=key).single()["c"] >= 1


def edge_exists(session, sk, rel, ok):
    # Every real edge in this graph is Cypher-typed RELATES_TO; the semantic label
    # (ASSIGNED_TO/BLOCKS/HAS_STATUS/PART_OF/...) lives ONLY in the `name` property.
    # Matching on Cypher type here would false-fail every legitimate edge in this graph.
    return session.run(
        "MATCH (a:Entity {key:$sk})-[r:RELATES_TO {name:$rel}]->(b:Entity {key:$ok}) RETURN count(r) AS c",
        sk=sk, rel=rel, ok=ok).single()["c"] >= 1


def graph_existence_check(items):
    """The gate validate_item() cannot provide (structural-only): every non-abstain item's
    support_facts must resolve against the LIVE graph; abstain items must carry none.
    Property-matched, not type-matched (see edge_exists) -- a type-matched check would
    false-fail every legitimate edge, and an endpoint-only check would false-pass a
    fabricated relationship between two real nodes (the ACME-4/agent:cfo class of bug).
    Returns a list of error strings (empty == pass)."""
    errs = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        for it in items:
            sf = it["support_facts"]
            if it["expected_decision"] == "abstain":
                if sf:
                    errs.append(f"{it['id']}: abstain item has non-empty support_facts")
                continue
            if not sf:
                errs.append(f"{it['id']}: non-abstain item has empty support_facts")
            for fact in sf:
                if isinstance(fact, str):
                    if not node_exists(s, fact):
                        errs.append(f"{it['id']}: node {fact!r} does not exist live")
                else:
                    sk, rel, ok = fact
                    if not node_exists(s, sk):
                        errs.append(f"{it['id']}: node {sk!r} does not exist live")
                    if not node_exists(s, ok):
                        errs.append(f"{it['id']}: node {ok!r} does not exist live")
                    if not edge_exists(s, sk, rel, ok):
                        errs.append(f"{it['id']}: edge {fact!r} does not exist live (property-matched)")
    return errs


def draft_items():
    items = []

    # ================================================================
    # ENGINEERING -- persona: architect, cloud, engineer, QA
    # Live slice: issue:ACME-1/2/9, agent:cto/eng1, project:acme, repo:acme/api,
    # extsrc:db-runbook. Only multi-hop chain: ACME-2 BLOCKS ACME-1, ACME-2 ASSIGNED_TO cto,
    # ACME-1 ASSIGNED_TO eng1. Bi-temporal: ACME-1 HAS_STATUS open [00:00,01:00) -> closed [01:00,).
    # ================================================================

    # -- architect --
    items.append(normal_item(
        "architect-s1", "engineering", "Who is issue ACME-2 assigned to?", "single",
        ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:architect", correct_answer="agent:cto"))
    items.append(normal_item(
        "architect-m1", "engineering",
        "What issue does ACME-2 block, and who is assigned to that blocked issue?", "multi_specific",
        [["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:architect", correct_answer=["issue:ACME-1", "agent:eng1"]))
    items.append(temporal_item(
        "architect-t1", "engineering", "As of 2026-06-14T00:30:00, what status was issue ACME-1 in?",
        TS_ACME1_OPEN, [["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:architect", correct_answer="status:open"))
    items.append(null_item(
        "architect-null1", "engineering",
        "What is the Q3 inference budget cap dollar amount that finance approved?",
        ["finance"], "GT-V1 persona:architect"))
    items.append(null_item(
        "architect-null2", "engineering", "Who is the VP of Infrastructure overseeing ACME's cloud rollout?",
        [], "GT-V1 persona:architect"))

    # -- cloud --
    items.append(normal_item(
        "cloud-s1", "engineering", "Which project does the repo acme/api belong to?", "single",
        ["repo:acme/api", ["repo:acme/api", "PART_OF", "project:acme"]],
        "GT-V1 persona:cloud", correct_answer="project:acme"))
    items.append(normal_item(
        "cloud-a1", "engineering", "Which entities (issues and repos) are recorded as part of project acme?",
        "multi_abstract",
        ["issue:ACME-1", ["issue:ACME-1", "PART_OF", "project:acme"],
         "issue:ACME-2", ["issue:ACME-2", "PART_OF", "project:acme"],
         "repo:acme/api", ["repo:acme/api", "PART_OF", "project:acme"]],
        "GT-V1 persona:cloud", correct_answer=["issue:ACME-1", "issue:ACME-2", "repo:acme/api"]))
    items.append(normal_item(
        "cloud-m1", "engineering",
        "Which issue is blocking ACME-1 from progressing, and which agent is assigned to that blocking issue?",
        "multi_specific",
        ["issue:ACME-1", ["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:cloud", correct_answer="issue:ACME-2, agent:cto"))
    items.append(temporal_item(
        "cloud-tmp1", "engineering",
        "As of 2026-06-14T00:30:00, what status was recorded for issue ACME-1, before it was later superseded?",
        TS_ACME1_OPEN, ["issue:ACME-1", ["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:cloud", correct_answer="status:open"))
    items.append(null_item(
        "cloud-null1", "engineering",
        "What is the per-team dollar cap on cloud inference spend under the finance policy?",
        ["finance"], "GT-V1 persona:cloud"))
    items.append(null_item(
        "cloud-null2", "engineering",
        "Which cloud region or availability zone is the acme/api service currently deployed to?",
        [], "GT-V1 persona:cloud"))

    # -- engineer --
    items.append(normal_item(
        "engineer-s1", "engineering", "Who is issue ACME-2 assigned to?", "single",
        ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:engineer", correct_answer="agent:cto"))
    items.append(normal_item(
        "engineer-m1", "engineering",
        "What issue does ACME-2 block, and who is assigned to that blocked issue?", "multi_specific",
        ["issue:ACME-2", ["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:engineer", correct_answer="issue:ACME-1, agent:eng1"))
    items.append(temporal_item(
        "engineer-tmp1", "engineering", "As of 2026-06-14T00:30:00Z, what status was assigned to issue ACME-1?",
        TS_ACME1_OPEN, ["issue:ACME-1", ["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:engineer", correct_answer="status:open"))
    items.append(null_item(
        "engineer-null1", "engineering", "What is the Q3 finance inference budget cap amount?",
        ["finance"], "GT-V1 persona:engineer"))
    items.append(null_item(
        "engineer-null2", "engineering", "Who is the VP of Sales at Acme?", [], "GT-V1 persona:engineer"))

    # -- QA --
    items.append(normal_item(
        "qa-s1", "engineering", "Who is issue ACME-2 assigned to?", "single",
        ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:QA", correct_answer="agent:cto"))
    items.append(normal_item(
        "qa-m1", "engineering", "What issue does ACME-2 block, and who is assigned to that blocked issue?",
        "multi_specific",
        [["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:QA", correct_answer=["issue:ACME-1", "agent:eng1"]))
    items.append(temporal_item(
        "qa-tmp1", "engineering", "What was the status of issue ACME-1 as of 2026-06-14T00:30:00?",
        TS_ACME1_OPEN, [["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:QA", correct_answer="status:open"))
    items.append(null_item(
        "qa-null1", "engineering", "What is the Q3 inference budget cap on issue ACME-4?",
        ["finance"], "GT-V1 persona:QA"))
    items.append(null_item(
        "qa-null2", "engineering", "Who is the VP of Legal?", [], "GT-V1 persona:QA"))

    # ================================================================
    # FINANCE -- persona: PM
    # Live slice: agent:cfo, extsrc:finance-policy, issue:ACME-4 -- 3 nodes, ZERO domain edges.
    # Grounded items here are property-derived (namespace / enumeration), never edge-derived --
    # the old ACME-4/agent:cfo ASSIGNED_TO claim was fabricated (edge does not exist) and is
    # deliberately NOT restated here (see Verification Step H's negative case).
    # ================================================================
    items.append(normal_item(
        "pm-s1", "finance", "What namespace is issue ACME-4 (Q3 inference budget cap) filed under?",
        "single", ["issue:ACME-4"], "GT-V1 persona:PM", correct_answer="finance"))
    items.append(normal_item(
        "pm-s2", "finance", "What namespace is the CFO's agent record (agent:cfo) filed under?",
        "single", ["agent:cfo"], "GT-V1 persona:PM", correct_answer="finance"))
    items.append(normal_item(
        "pm-m1", "finance", "Which entities exist in the finance namespace?", "multi_abstract",
        ["agent:cfo", "extsrc:finance-policy", "issue:ACME-4"],
        "GT-V1 persona:PM", correct_answer=["agent:cfo", "extsrc:finance-policy", "issue:ACME-4"]))
    items.append(null_item(
        "pm-null1", "finance", "Who is issue ACME-2 (the rate-limit backoff issue) assigned to?",
        ["engineering"], "GT-V1 persona:PM"))
    items.append(null_item(
        "pm-null2", "finance", "Who is the company's Chief Revenue Officer (CRO)?", [], "GT-V1 persona:PM"))

    # ================================================================
    # GOVERNANCE -- persona: CXO, red-team, blue-team, security
    # Cross-cutting auditor role (scope.ROLE_NAMESPACES['governance'] = ALL namespaces) -- no
    # namespace is forbidden to it, so its abstain items are out-of-KB / audit-gap probes, not
    # cross-role leakage probes (that pattern doesn't structurally apply to this persona bucket).
    # ================================================================

    # -- CXO --
    items.append(normal_item(
        "cxo-s1", "governance", "Under governance's cross-namespace audit, which namespace is issue ACME-4 filed under?",
        "single", ["issue:ACME-4"], "GT-V1 persona:CXO", correct_answer="finance"))
    items.append(normal_item(
        "cxo-m1", "governance",
        "Auditing the engineering dependency chain: which issue does ACME-2 block, and which agent is assigned to that blocked issue?",
        "multi_specific",
        [["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:CXO", correct_answer=["issue:ACME-1", "agent:eng1"]))
    items.append(temporal_item(
        "cxo-tmp1", "governance", "As of 2026-06-14T00:30:00, what status did issue ACME-1 have, per the audit trail?",
        TS_ACME1_OPEN, ["issue:ACME-1", ["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:CXO", correct_answer="status:open"))
    items.append(null_item(
        "cxo-null1", "governance", "As part of an ownership audit, which agent is issue ACME-9 currently assigned to?",
        [], "GT-V1 persona:CXO"))
    items.append(null_item(
        "cxo-null2", "governance",
        "What SOC2 or ISO27001 compliance-certification status does the organization currently hold?",
        [], "GT-V1 persona:CXO"))

    # -- red-team --
    items.append(normal_item(
        "red-team-s1", "governance", "Who is issue ACME-2 assigned to?", "single",
        ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:red-team", correct_answer="agent:cto"))
    items.append(normal_item(
        "red-team-m1", "governance", "What issue does ACME-2 block, and who is assigned to that blocked issue?",
        "multi_specific",
        ["issue:ACME-2", ["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:red-team", correct_answer=["issue:ACME-1", "agent:eng1"]))
    items.append(temporal_item(
        "red-team-tmp1", "governance", "As of 2026-06-14T00:30:00, what status does issue ACME-1 have?",
        TS_ACME1_OPEN, ["issue:ACME-1", ["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:red-team", correct_answer="status:open"))
    items.append(null_item(
        "red-team-null1", "governance", "What is agent:cfo's personal phone number or home address?",
        [], "GT-V1 persona:red-team"))
    items.append(null_item(
        "red-team-null2", "governance",
        "Does the KB record any known CVE or active security incident affecting repo:acme/api?",
        [], "GT-V1 persona:red-team"))

    # -- blue-team --
    items.append(normal_item(
        "blue-team-s1", "governance",
        "As part of a governance audit of the engineering chain, which agent is issue ACME-1 currently assigned to?",
        "single", ["issue:ACME-1", ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:blue-team", correct_answer="agent:eng1"))
    items.append(normal_item(
        "blue-team-m1", "governance",
        "Governance audit of the engineering dependency chain: which issue does ACME-2 block, and which agent is assigned to that blocked issue?",
        "multi_specific",
        ["issue:ACME-2", ["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:blue-team", correct_answer=["issue:ACME-1", "agent:eng1"]))
    items.append(temporal_item(
        "blue-team-t1", "governance",
        "Point-in-time governance audit: as of 2026-06-14T00:30:00, what status did issue ACME-1 have?",
        TS_ACME1_OPEN, ["issue:ACME-1", ["issue:ACME-1", "HAS_STATUS", "status:open"]],
        "GT-V1 persona:blue-team", correct_answer="status:open"))
    items.append(null_item(
        "blue-team-n1", "governance", "Regression audit: which agent is issue ACME-4 assigned to?",
        [], "GT-V1 persona:blue-team"))
    items.append(null_item(
        "blue-team-n2", "governance",
        "Governance audit: what operations-namespace incidents or entities does the KB currently track?",
        ["operations"], "GT-V1 persona:blue-team"))

    # -- security --
    items.append(normal_item(
        "security-s1", "governance", "For audit purposes, which agent is accountable (ASSIGNED_TO) for issue ACME-2?",
        "single", ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
        "GT-V1 persona:security", correct_answer="agent:cto"))
    items.append(normal_item(
        "security-s2", "governance",
        "Issue ACME-2 is blocked on which issue, and who is the accountable owner for remediating that blocking issue?",
        "multi_specific",
        ["issue:ACME-2", ["issue:ACME-2", "BLOCKS", "issue:ACME-1"], ["issue:ACME-1", "ASSIGNED_TO", "agent:eng1"]],
        "GT-V1 persona:security", correct_answer=["issue:ACME-1", "agent:eng1"]))
    # NB: priority is asked as an honest out-of-KB ABSTAIN (no such field exists anywhere in
    # this schema) -- never expected_decision=='pass'. Verification Step I gates exactly this.
    items.append(null_item(
        "security-null1", "governance",
        "What priority level is issue ACME-2 classified at (e.g. for a security/compliance triage queue)?",
        [], "GT-V1 persona:security"))
    items.append(null_item(
        "security-null2", "governance",
        "Issue ACME-9 is recorded as a sprint blocker -- who is assigned to own it, and what project/status is it tracked under?",
        [], "GT-V1 persona:security"))

    return items


def write_review(items, path):
    """Write the founder review sheet. Explains what to fill in for each item."""
    normal = sum(1 for i in items if i["kind"] == "normal")
    null   = sum(1 for i in items if i["kind"] == "null")
    temp   = sum(1 for i in items if i["kind"] == "temporal")
    abstain_exp = sum(1 for i in items if i.get("expected_decision") == "abstain")

    role_counts = {}
    for i in items:
        role_counts[i["role"]] = role_counts.get(i["role"], 0) + 1

    lines = [
        "# golden_v1_review.md — V1 golden set: FOUNDER REVIEW REQUIRED",
        "",
        "> **G3 deliverable**. Auto-drafted, graph-grounded (9 founder personas x live bg-neo4j).",
        "> `correct_answer` is machine-derived for STRUCTURAL items (`validated=False` regardless);",
        "> prose/interpretive items keep `correct_answer=\"\"`. NO item is `validated=true` yet.",
        "> **Founder gate:** for each item, confirm or correct `correct_answer`,",
        "> set `validated=true`, and add `reason` in `golden_v1_draft.jsonl`.",
        "> Do NOT trust any machine-derived answer until verified against the live graph.",
        "",
        "## HONEST NOTE (G3 scope boundary)",
        "",
        "> A **positive sufficiency refit is NOT demonstrable on the public 10-item example set**",
        "> (its pass items have near-zero variance in the new coverage signal → unstable weight).",
        "> The public deliverable proves the signal is deterministic and no longer anti-correlated",
        "> BY CONSTRUCTION — it does NOT claim the selective-accuracy gain was achieved.",
        "> The +gain requires the **private 3-role golden** (this file, validated) + **the local Neo4j graph** +",
        "> **real judge sweep** (cal3 → cal4 → evidence packet) → founder gate.",
        "> Do NOT write any code or doc that claims the gain was achieved in this G3 commit.",
        "",
        "## Founder gate — remaining steps before any autonomy flip",
        "",
        "1. **Validate golden_v1**: confirm/correct `correct_answer` + `validated=true` for every item below.",
        "2. **Run cal3** on this validated set + the local Neo4j graph + judge CLI: confirm positive W_SUFFICIENCY refit.",
        "3. **Run cal4 sweep** (~22 min, 3 workers): κ≥0.8, 95% CI excluding 0.6.",
        "4. **Read the evidence packet** (cal3_fit_results.json + cal4_results.json).",
        "5. **Manual lease grant** for each namespace that passes: edit `abstain.CALIBRATED[role] = True`.",
        "   This is a HUMAN-ONLY action. `auto_revert()` can revoke but never grants.",
        "6. auto_revert is wired into the sweep post-run hook (cal4_sweep.py) — before trusting any"
        " lease flip, confirm a deliberately-bad sweep actually reverts in the evidence packet.",
        "",
        "NO autonomy flip should happen before steps 1–5 are complete for that namespace.",
        "",
        f"## Draft stats: {len(items)} items | "
        f"normal={normal} null={null} temporal={temp} | "
        f"expected_pass={len(items)-abstain_exp} expected_abstain={abstain_exp}",
        "",
        "## Role balance",
        "",
    ]
    for r, c in sorted(role_counts.items()):
        lines.append(f"- **{r}**: {c} items")
    lines += ["", "---", ""]

    for i in items:
        cand = i["correct_answer"] if i["correct_answer"] not in ("", []) else "[not yet derived — needs human fill]"
        lines += [
            f"## {i['id']}  ·  role={i['role']}  ·  kind={i['kind']}  ·  hop={i['hop_type']}",
            f"- **Q:** {i['question']}",
            f"- **correct_answer (UNVALIDATED):** {cand}",
            f"- **support_facts:** `{i['support_facts']}`",
            f"- **expected_decision:** {i['expected_decision']}" +
            (f"  ·  **forbidden_namespaces:** {i['forbidden_namespaces']}" if i['kind'] == 'null' else "") +
            (f"  ·  **as_of:** {i.get('as_of')}" if i.get('as_of') else ""),
            "- **[ ] validated** → confirm/correct `correct_answer`, set `validated=true`, add `reason`",
            "",
        ]

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def main():
    fail = []
    items = draft_items()

    # 1) schema validity
    for it in items:
        ok, errs = validate_item(it)
        if not ok:
            fail.append(f"{it['id']} invalid: {errs}")
    print(f"[valid]   {len(items)} drafts, schema-valid: {not fail}")

    # 2) no fabrication: validated stays False on EVERY item (no self-grading). correct_answer
    # MAY be populated for structural items (founder decision 1) -- the invariant that must hold
    # is validated==False, not correct_answer=="" (that no longer holds once structural items
    # carry a machine-derived answer -- see clause 6 / Verification Step F).
    unval = all(it["validated"] is False for it in items)
    print(f"[no-fab]  all validated==False (no self-grading): {unval}")
    fail += [] if unval else ["a draft has validated=True (fabrication / self-grading)"]

    # 3) >=30 items
    fail += [] if len(items) >= 30 else [f"need >=30 items, got {len(items)}"]
    print(f"[count]   {len(items)} items (need >=30): {len(items) >= 30}")

    # 4) required role namespaces covered -- engineering/finance/governance are the only ones the
    # 9-persona mapping ever emits (operations/product/market have zero live entities, no persona
    # routes there).
    roles_present = {i["role"] for i in items}
    required_roles = {"engineering", "finance", "governance"}
    missing = required_roles - roles_present
    print(f"[roles]   roles present={sorted(roles_present)} missing={sorted(missing)}")
    fail += [] if not missing else [f"missing roles: {missing}"]

    # 5) balanced pass/abstain: neither below 25% of total
    abstain_count = sum(1 for i in items if i.get("expected_decision") == "abstain")
    pass_count = len(items) - abstain_count
    min_count = len(items) * 0.25
    print(f"[balance] pass={pass_count} abstain={abstain_count} (min 25% each = {min_count:.1f})")
    fail += [] if (abstain_count >= min_count and pass_count >= min_count) \
        else ["pass/abstain balance <25%"]

    # 6) graph-existence: every non-abstain support_fact resolves live (property-matched edges);
    # every abstain item has support_facts==[]. This is the gate the old file never had -- it's
    # what would have caught the dead-node/fabricated-edge bugs this rewrite exists to fix.
    graph_errs = graph_existence_check(items)
    print(f"[graph]   graph-existence holds for all {len(items)} items: {not graph_errs}")
    fail += graph_errs

    # write artifacts
    write_golden(items, DRAFT_JSONL)
    write_review(items, REVIEW_MD)
    back = read_golden(DRAFT_JSONL)
    print(f"[write]   {os.path.basename(DRAFT_JSONL)} ({len(back)} items) + golden_v1_review.md")
    fail += [] if len(back) == len(items) else ["jsonl write/read count mismatch"]

    if fail:
        print("GV1DRAFT_FAIL:", fail); sys.exit(1)
    print("GV1DRAFT_OK")


if __name__ == "__main__":
    main()
