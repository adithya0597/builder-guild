"""GT-V1-DRAFT (G3): machine-draft of the V1 golden set — 6-role expansion.

Mirrors gt2_draft.py structure. Generates >=30 draft items across all 6 role namespaces
(engineering, finance, operations, product, market, governance), balanced pass/abstain
prevalence, all UNVALIDATED. The founder fills in correct_answer + validated=True at the
human gate before any autonomy flip.

NO FABRICATION: every correct_answer is "" and validated=False. candidate_answer carries
a graph-derived or schema-derived placeholder, clearly marked CANDIDATE. The agent never
asserts an unvalidated answer as ground truth.

Output:
  03-evals/src/golden_v1_draft.jsonl  — the drafts (golden.py schema)
  03-evals/golden_v1_review.md        — the human review sheet (founder fills in)
"""
import json
import os
import sys

# 01-context/src must be on path to import golden
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

from golden import (normal_item, null_item, temporal_item, validate_item,
                    write_golden, read_golden, ROLES)

HERE = os.path.dirname(os.path.abspath(__file__))
# Output paths relative to repo layout
DRAFT_JSONL = os.path.join(HERE, "golden_v1_draft.jsonl")
REVIEW_MD   = os.path.join(HERE, "..", "golden_v1_review.md")

# G3 target: >=30 items, balanced pass/abstain, all 6 namespaces + governance.
# Items are drafted against the ACME public example graph topology (same nodes as
# example_golden.jsonl). Answers left "" + validated=False; candidate_answer is the
# schema-derived guess for the founder to confirm or correct.

def draft_items():
    items = []

    def add(it, candidate):
        it["candidate_answer"] = candidate
        items.append(it)

    # ---- ENGINEERING (target: 6 pass + 2 abstain) ----
    add(normal_item("eng-v1-s1", "engineering",
                    "Who is issue ACME-2 (rate-limit backoff for the inference client) assigned to?",
                    "single", ["issue:ACME-2", ["issue:ACME-2", "ASSIGNED_TO", "agent:cto"]],
                    "GT-V1 draft"),
        "CANDIDATE: agent:cto")

    add(normal_item("eng-v1-s2", "engineering",
                    "What is the current status of ACME-2?",
                    "single", ["issue:ACME-2"], "GT-V1 draft"),
        "CANDIDATE: in_progress")

    add(normal_item("eng-v1-m1", "engineering",
                    "What issue does ACME-2 block, and who is assigned to that blocked issue?",
                    "multi_specific",
                    [["issue:ACME-2", "BLOCKS", "issue:ACME-3"],
                     ["issue:ACME-3", "ASSIGNED_TO", "agent:cto"]],
                    "GT-V1 draft"),
        "CANDIDATE: ACME-2 blocks issue:ACME-3, assigned to agent:cto")

    add(normal_item("eng-v1-m2", "engineering",
                    "Which engineering issues are currently blocked?",
                    "multi_abstract", ["issue:ACME-6", "issue:ACME-7"], "GT-V1 draft"),
        "CANDIDATE: issue:ACME-6, issue:ACME-7")

    add(normal_item("eng-v1-s3", "engineering",
                    "What is the priority of ACME-3?",
                    "single", ["issue:ACME-3"], "GT-V1 draft"),
        "CANDIDATE: [verify against graph — priority field in long_context]")

    add(normal_item("eng-v1-s4", "engineering",
                    "How many engineering issues are assigned to agent:cto?",
                    "multi_abstract", ["issue:ACME-2", "issue:ACME-3"], "GT-V1 draft"),
        "CANDIDATE: [count from graph — verify live]")

    add(null_item("eng-v1-null1", "engineering",
                  "What is the exact Q3 inference budget cap dollar amount?",
                  ["finance"], "GT-V1 draft"),
        "CANDIDATE: abstain (finance fact; engineering role must not surface it)")

    add(null_item("eng-v1-null2", "engineering",
                  "Who is the VP of Sales?",
                  [], "GT-V1 draft"),
        "CANDIDATE: abstain (no such entity in the KB)")

    # ---- FINANCE (target: 5 pass + 2 abstain) ----
    add(normal_item("fin-v1-s1", "finance",
                    "Who owns the Q3 inference budget-cap issue (ACME-4)?",
                    "single", ["issue:ACME-4", ["issue:ACME-4", "ASSIGNED_TO", "agent:cfo"]],
                    "GT-V1 draft"),
        "CANDIDATE: agent:cfo")

    add(normal_item("fin-v1-s2", "finance",
                    "What does ACME-5 forecast?",
                    "single", ["issue:ACME-5"], "GT-V1 draft"),
        "CANDIDATE: embedding-model GPU cost for the next 90 days")

    add(normal_item("fin-v1-a1", "finance",
                    "What in-progress finance work targets cost control?",
                    "multi_abstract", ["issue:ACME-4", "issue:ACME-5"], "GT-V1 draft"),
        "CANDIDATE: issue:ACME-4 (budget cap), issue:ACME-5 (embedding cost forecast)")

    add(normal_item("fin-v1-s3", "finance",
                    "What is the current status of ACME-5?",
                    "single", ["issue:ACME-5"], "GT-V1 draft"),
        "CANDIDATE: in_progress")

    add(normal_item("fin-v1-s4", "finance",
                    "What priority is assigned to ACME-4?",
                    "single", ["issue:ACME-4"], "GT-V1 draft"),
        "CANDIDATE: [verify against graph — priority field in long_context]")

    add(null_item("fin-v1-null1", "finance",
                  "Which CI runner is failing on the engineering pipeline?",
                  ["engineering"], "GT-V1 draft"),
        "CANDIDATE: abstain (engineering fact; finance role must not surface it)")

    add(temporal_item("fin-v1-tmp1", "finance",
                      "Who owned ACME-4 as of 2026-05-01?",
                      "2026-05-01T00:00:00",
                      ["issue:ACME-4"], "GT-V1 draft [PLACEHOLDER: seed supersession episode]"),
        "CANDIDATE: abstain (no historical assignment edge in KB yet — seed valid_from/valid_to)")

    # ---- OPERATIONS (target: 4 pass + 2 abstain) ----
    add(normal_item("ops-v1-s1", "operations",
                    "What shared operational status values are defined in the KB?",
                    "single", ["shared"], "GT-V1 draft"),
        "CANDIDATE: [list status enum values from shared namespace — verify live]")

    add(normal_item("ops-v1-s2", "operations",
                    "Are there any operations-namespace entities currently marked stale?",
                    "single", ["operations"], "GT-V1 draft"),
        "CANDIDATE: [verify against graph — dirty flag on operations nodes]")

    add(normal_item("ops-v1-m1", "operations",
                    "Which operations issues have the highest priority?",
                    "multi_abstract", ["operations"], "GT-V1 draft"),
        "CANDIDATE: [pull top-priority ops issues from graph — verify live]")

    add(normal_item("ops-v1-s3", "operations",
                    "What is the token budget for the operations role?",
                    "single", ["shared"], "GT-V1 draft"),
        "CANDIDATE: 2000 tokens (from scope.py TOKEN_BUDGET)")

    add(null_item("ops-v1-null1", "operations",
                  "What is the CFO's Q3 budget cap for inference?",
                  ["finance"], "GT-V1 draft"),
        "CANDIDATE: abstain (finance fact; operations role must not surface it)")

    add(null_item("ops-v1-null2", "operations",
                  "Who is assigned to the blocked engineering issue ACME-6?",
                  ["engineering"], "GT-V1 draft"),
        "CANDIDATE: abstain (engineering fact; operations role must not surface it)")

    # ---- PRODUCT (target: 4 pass + 1 abstain) ----
    add(normal_item("prod-v1-s1", "product",
                    "What product issues are currently in_progress?",
                    "multi_abstract", ["product"], "GT-V1 draft"),
        "CANDIDATE: [pull in_progress product nodes from graph — verify live]")

    add(normal_item("prod-v1-s2", "product",
                    "Which product entity has the highest priority in the KB?",
                    "single", ["product"], "GT-V1 draft"),
        "CANDIDATE: [verify against graph — priority field]")

    add(normal_item("prod-v1-m1", "product",
                    "What shared context is relevant to product planning?",
                    "multi_abstract", ["shared"], "GT-V1 draft"),
        "CANDIDATE: [shared namespace facts relevant to product — verify live]")

    add(normal_item("prod-v1-s3", "product",
                    "Are any product issues blocked?",
                    "single", ["product"], "GT-V1 draft"),
        "CANDIDATE: [verify blocked status on product nodes — verify live]")

    add(null_item("prod-v1-null1", "product",
                  "What is the exact dollar amount approved for the engineering CI runners budget?",
                  ["finance", "engineering"], "GT-V1 draft"),
        "CANDIDATE: abstain (cross-role fact outside product scope)")

    # ---- MARKET (target: 3 pass + 1 abstain) ----
    add(normal_item("mkt-v1-s1", "market",
                    "What market-namespace entities are present in the KB?",
                    "multi_abstract", ["market"], "GT-V1 draft"),
        "CANDIDATE: [list market namespace nodes — verify live]")

    add(normal_item("mkt-v1-s2", "market",
                    "What is the status of the highest-priority market issue?",
                    "single", ["market"], "GT-V1 draft"),
        "CANDIDATE: [verify against graph — priority + status on market nodes]")

    add(normal_item("mkt-v1-s3", "market",
                    "What shared facts are accessible to the market role?",
                    "single", ["shared"], "GT-V1 draft"),
        "CANDIDATE: [shared namespace facts — verify live]")

    add(null_item("mkt-v1-null1", "market",
                  "Who is the CTO and what engineering issues are they currently handling?",
                  ["engineering"], "GT-V1 draft"),
        "CANDIDATE: abstain (engineering fact; market role must not surface engineering issues)")

    # ---- GOVERNANCE (target: 3 pass + 2 abstain) ----
    # Governance is the cross-cutting auditor — may read ALL namespaces
    add(normal_item("gov-v1-m1", "governance",
                    "Which issues across all namespaces are currently blocked?",
                    "multi_abstract",
                    ["issue:ACME-6", "issue:ACME-7"],  # known blocked; may include ops/product/market
                    "GT-V1 draft"),
        "CANDIDATE: issue:ACME-6, issue:ACME-7 (engineering); [verify ops/product/market blocked — live]")

    add(normal_item("gov-v1-m2", "governance",
                    "Who are the owners of the highest-priority issues across all namespaces?",
                    "multi_abstract",
                    ["issue:ACME-2", "issue:ACME-4"],  # cto + cfo ownership
                    "GT-V1 draft"),
        "CANDIDATE: agent:cto (engineering), agent:cfo (finance); [verify other namespaces — live]")

    add(normal_item("gov-v1-s1", "governance",
                    "Is there any stale data (dirty nodes) currently in the KB?",
                    "single", ["engineering", "finance", "operations", "product", "market"],
                    "GT-V1 draft"),
        "CANDIDATE: [check dirty flag across all namespace nodes — verify live]")

    add(null_item("gov-v1-null1", "governance",
                  "What was the CFO's salary in 2025?",
                  [], "GT-V1 draft"),
        "CANDIDATE: abstain (no compensation data in the KB — out of KB scope)")

    add(null_item("gov-v1-null2", "governance",
                  "Who is the VP of Legal?",
                  [], "GT-V1 draft"),
        "CANDIDATE: abstain (no such entity in the KB)")

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
        "> **G3 deliverable**. Auto-drafted structure only.",
        "> Every `correct_answer` is `\"\"` and `validated=False`.",
        "> **Founder gate:** for each item, confirm or correct the candidate answer,",
        "> set `correct_answer`, flip `validated=true`, and add `reason` in `golden_v1_draft.jsonl`.",
        "> Do NOT trust any candidate answer until verified against the live graph.",
        "",
        "## HONEST NOTE (G3 scope boundary)",
        "",
        "> A **positive sufficiency refit is NOT demonstrable on the public 10-item example set**",
        "> (its pass items have near-zero variance in the new coverage signal → unstable weight).",
        "> The public deliverable proves the signal is deterministic and no longer anti-correlated",
        "> BY CONSTRUCTION — it does NOT claim the selective-accuracy gain was achieved.",
        "> The +gain requires the **private 6-role golden** (this file, validated) + **the local Neo4j graph** +",
        "> **real judge sweep** (cal3 → cal4 → evidence packet) → founder gate.",
        "> Do NOT write any code or doc that claims the gain was achieved in this G3 commit.",
        "",
        "## Founder gate — remaining steps before any autonomy flip",
        "",
        "1. **Validate golden_v1**: fill in `correct_answer` + `validated=true` for every item below.",
        "2. **Run cal3** on this validated set + the local Neo4j graph + judge CLI: confirm positive W_SUFFICIENCY refit.",
        "3. **Run cal4 sweep** (~22 min, 3 workers): κ≥0.8, 95% CI excluding 0.6.",
        "4. **Read the evidence packet** (cal3_fit_results.json + cal4_results.json).",
        "5. **Manual lease grant** for each namespace that passes: edit `abstain.CALIBRATED[role] = True`.",
        "   This is a HUMAN-ONLY action. `auto_revert()` can revoke but never grants.",
        "6. **Wire auto_revert** into the sweep post-run hook so bad sweeps auto-revoke.",
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
        lines += [
            f"## {i['id']}  ·  role={i['role']}  ·  kind={i['kind']}  ·  hop={i['hop_type']}",
            f"- **Q:** {i['question']}",
            f"- **candidate (UNVALIDATED):** {i.get('candidate_answer', '[no candidate]')}",
            f"- **support_facts:** `{i['support_facts']}`",
            f"- **expected_decision:** {i['expected_decision']}" +
            (f"  ·  **forbidden_namespaces:** {i['forbidden_namespaces']}" if i['kind'] == 'null' else "") +
            (f"  ·  **as_of:** {i.get('as_of')}" if i.get('as_of') else ""),
            "- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`",
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

    # 2) no fabrication: all correct_answer=="" and validated=False
    unval = all(it["correct_answer"] == "" and it["validated"] is False for it in items)
    print(f"[no-fab]  all correct_answer=='' and validated=False: {unval}")
    fail += [] if unval else ["a draft has a pre-filled/validated answer (fabrication)"]

    # 3) >=30 items
    fail += [] if len(items) >= 30 else [f"need >=30 items, got {len(items)}"]
    print(f"[count]   {len(items)} items (need >=30): {len(items) >= 30}")

    # 4) all 6 role namespaces covered (shared is optional in draft)
    roles_present = {i["role"] for i in items}
    required_roles = {"engineering", "finance", "operations", "product", "market", "governance"}
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
