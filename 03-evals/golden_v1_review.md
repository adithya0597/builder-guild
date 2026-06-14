# golden_v1_review.md — V1 golden set: FOUNDER REVIEW REQUIRED

> **G3 deliverable**. Auto-drafted structure only.
> Every `correct_answer` is `""` and `validated=False`.
> **Founder gate:** for each item, confirm or correct the candidate answer,
> set `correct_answer`, flip `validated=true`, and add `reason` in `golden_v1_draft.jsonl`.
> Do NOT trust any candidate answer until verified against the live graph.

## HONEST NOTE (G3 scope boundary)

> A **positive sufficiency refit is NOT demonstrable on the public 10-item example set**
> (its pass items have near-zero variance in the new coverage signal → unstable weight).
> The public deliverable proves the signal is deterministic and no longer anti-correlated
> BY CONSTRUCTION — it does NOT claim the selective-accuracy gain was achieved.
> The +gain requires the **private 6-role golden** (this file, validated) + **the local Neo4j graph** +
> **real judge sweep** (cal3 → cal4 → evidence packet) → founder gate.
> Do NOT write any code or doc that claims the gain was achieved in this G3 commit.

## Founder gate — remaining steps before any autonomy flip

1. **Validate golden_v1**: fill in `correct_answer` + `validated=true` for every item below.
2. **Run cal3** on this validated set + the local Neo4j graph + judge CLI: confirm positive W_SUFFICIENCY refit.
3. **Run cal4 sweep** (~22 min, 3 workers): κ≥0.8, 95% CI excluding 0.6.
4. **Read the evidence packet** (cal3_fit_results.json + cal4_results.json).
5. **Manual lease grant** for each namespace that passes: edit `abstain.CALIBRATED[role] = True`.
   This is a HUMAN-ONLY action. `auto_revert()` can revoke but never grants.
6. **Wire auto_revert** into the sweep post-run hook so bad sweeps auto-revoke.

NO autonomy flip should happen before steps 1–5 are complete for that namespace.

## Draft stats: 35 items | normal=25 null=9 temporal=1 | expected_pass=26 expected_abstain=9

## Role balance

- **engineering**: 8 items
- **finance**: 7 items
- **governance**: 5 items
- **market**: 4 items
- **operations**: 6 items
- **product**: 5 items

---

## eng-v1-s1  ·  role=engineering  ·  kind=normal  ·  hop=single
- **Q:** Who is issue ACME-2 (rate-limit backoff for the inference client) assigned to?
- **candidate (UNVALIDATED):** CANDIDATE: agent:cto
- **support_facts:** `['issue:ACME-2', ['issue:ACME-2', 'ASSIGNED_TO', 'agent:cto']]`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-s2  ·  role=engineering  ·  kind=normal  ·  hop=single
- **Q:** What is the current status of ACME-2?
- **candidate (UNVALIDATED):** CANDIDATE: in_progress
- **support_facts:** `['issue:ACME-2']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-m1  ·  role=engineering  ·  kind=normal  ·  hop=multi_specific
- **Q:** What issue does ACME-2 block, and who is assigned to that blocked issue?
- **candidate (UNVALIDATED):** CANDIDATE: ACME-2 blocks issue:ACME-3, assigned to agent:cto
- **support_facts:** `[['issue:ACME-2', 'BLOCKS', 'issue:ACME-3'], ['issue:ACME-3', 'ASSIGNED_TO', 'agent:cto']]`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-m2  ·  role=engineering  ·  kind=normal  ·  hop=multi_abstract
- **Q:** Which engineering issues are currently blocked?
- **candidate (UNVALIDATED):** CANDIDATE: issue:ACME-6, issue:ACME-7
- **support_facts:** `['issue:ACME-6', 'issue:ACME-7']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-s3  ·  role=engineering  ·  kind=normal  ·  hop=single
- **Q:** What is the priority of ACME-3?
- **candidate (UNVALIDATED):** CANDIDATE: [verify against graph — priority field in long_context]
- **support_facts:** `['issue:ACME-3']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-s4  ·  role=engineering  ·  kind=normal  ·  hop=multi_abstract
- **Q:** How many engineering issues are assigned to agent:cto?
- **candidate (UNVALIDATED):** CANDIDATE: [count from graph — verify live]
- **support_facts:** `['issue:ACME-2', 'issue:ACME-3']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-null1  ·  role=engineering  ·  kind=null  ·  hop=single
- **Q:** What is the exact Q3 inference budget cap dollar amount?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (finance fact; engineering role must not surface it)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['finance']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## eng-v1-null2  ·  role=engineering  ·  kind=null  ·  hop=single
- **Q:** Who is the VP of Sales?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (no such entity in the KB)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** []
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-s1  ·  role=finance  ·  kind=normal  ·  hop=single
- **Q:** Who owns the Q3 inference budget-cap issue (ACME-4)?
- **candidate (UNVALIDATED):** CANDIDATE: agent:cfo
- **support_facts:** `['issue:ACME-4', ['issue:ACME-4', 'ASSIGNED_TO', 'agent:cfo']]`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-s2  ·  role=finance  ·  kind=normal  ·  hop=single
- **Q:** What does ACME-5 forecast?
- **candidate (UNVALIDATED):** CANDIDATE: embedding-model GPU cost for the next 90 days
- **support_facts:** `['issue:ACME-5']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-a1  ·  role=finance  ·  kind=normal  ·  hop=multi_abstract
- **Q:** What in-progress finance work targets cost control?
- **candidate (UNVALIDATED):** CANDIDATE: issue:ACME-4 (budget cap), issue:ACME-5 (embedding cost forecast)
- **support_facts:** `['issue:ACME-4', 'issue:ACME-5']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-s3  ·  role=finance  ·  kind=normal  ·  hop=single
- **Q:** What is the current status of ACME-5?
- **candidate (UNVALIDATED):** CANDIDATE: in_progress
- **support_facts:** `['issue:ACME-5']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-s4  ·  role=finance  ·  kind=normal  ·  hop=single
- **Q:** What priority is assigned to ACME-4?
- **candidate (UNVALIDATED):** CANDIDATE: [verify against graph — priority field in long_context]
- **support_facts:** `['issue:ACME-4']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-null1  ·  role=finance  ·  kind=null  ·  hop=single
- **Q:** Which CI runner is failing on the engineering pipeline?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (engineering fact; finance role must not surface it)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['engineering']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## fin-v1-tmp1  ·  role=finance  ·  kind=temporal  ·  hop=multi_specific
- **Q:** Who owned ACME-4 as of 2026-05-01?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (no historical assignment edge in KB yet — seed valid_from/valid_to)
- **support_facts:** `['issue:ACME-4']`
- **expected_decision:** pass  ·  **as_of:** 2026-05-01T00:00:00
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-s1  ·  role=operations  ·  kind=normal  ·  hop=single
- **Q:** What shared operational status values are defined in the KB?
- **candidate (UNVALIDATED):** CANDIDATE: [list status enum values from shared namespace — verify live]
- **support_facts:** `['shared']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-s2  ·  role=operations  ·  kind=normal  ·  hop=single
- **Q:** Are there any operations-namespace entities currently marked stale?
- **candidate (UNVALIDATED):** CANDIDATE: [verify against graph — dirty flag on operations nodes]
- **support_facts:** `['operations']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-m1  ·  role=operations  ·  kind=normal  ·  hop=multi_abstract
- **Q:** Which operations issues have the highest priority?
- **candidate (UNVALIDATED):** CANDIDATE: [pull top-priority ops issues from graph — verify live]
- **support_facts:** `['operations']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-s3  ·  role=operations  ·  kind=normal  ·  hop=single
- **Q:** What is the token budget for the operations role?
- **candidate (UNVALIDATED):** CANDIDATE: 2000 tokens (from scope.py TOKEN_BUDGET)
- **support_facts:** `['shared']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-null1  ·  role=operations  ·  kind=null  ·  hop=single
- **Q:** What is the CFO's Q3 budget cap for inference?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (finance fact; operations role must not surface it)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['finance']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## ops-v1-null2  ·  role=operations  ·  kind=null  ·  hop=single
- **Q:** Who is assigned to the blocked engineering issue ACME-6?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (engineering fact; operations role must not surface it)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['engineering']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## prod-v1-s1  ·  role=product  ·  kind=normal  ·  hop=multi_abstract
- **Q:** What product issues are currently in_progress?
- **candidate (UNVALIDATED):** CANDIDATE: [pull in_progress product nodes from graph — verify live]
- **support_facts:** `['product']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## prod-v1-s2  ·  role=product  ·  kind=normal  ·  hop=single
- **Q:** Which product entity has the highest priority in the KB?
- **candidate (UNVALIDATED):** CANDIDATE: [verify against graph — priority field]
- **support_facts:** `['product']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## prod-v1-m1  ·  role=product  ·  kind=normal  ·  hop=multi_abstract
- **Q:** What shared context is relevant to product planning?
- **candidate (UNVALIDATED):** CANDIDATE: [shared namespace facts relevant to product — verify live]
- **support_facts:** `['shared']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## prod-v1-s3  ·  role=product  ·  kind=normal  ·  hop=single
- **Q:** Are any product issues blocked?
- **candidate (UNVALIDATED):** CANDIDATE: [verify blocked status on product nodes — verify live]
- **support_facts:** `['product']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## prod-v1-null1  ·  role=product  ·  kind=null  ·  hop=single
- **Q:** What is the exact dollar amount approved for the engineering CI runners budget?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (cross-role fact outside product scope)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['finance', 'engineering']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## mkt-v1-s1  ·  role=market  ·  kind=normal  ·  hop=multi_abstract
- **Q:** What market-namespace entities are present in the KB?
- **candidate (UNVALIDATED):** CANDIDATE: [list market namespace nodes — verify live]
- **support_facts:** `['market']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## mkt-v1-s2  ·  role=market  ·  kind=normal  ·  hop=single
- **Q:** What is the status of the highest-priority market issue?
- **candidate (UNVALIDATED):** CANDIDATE: [verify against graph — priority + status on market nodes]
- **support_facts:** `['market']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## mkt-v1-s3  ·  role=market  ·  kind=normal  ·  hop=single
- **Q:** What shared facts are accessible to the market role?
- **candidate (UNVALIDATED):** CANDIDATE: [shared namespace facts — verify live]
- **support_facts:** `['shared']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## mkt-v1-null1  ·  role=market  ·  kind=null  ·  hop=single
- **Q:** Who is the CTO and what engineering issues are they currently handling?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (engineering fact; market role must not surface engineering issues)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** ['engineering']
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## gov-v1-m1  ·  role=governance  ·  kind=normal  ·  hop=multi_abstract
- **Q:** Which issues across all namespaces are currently blocked?
- **candidate (UNVALIDATED):** CANDIDATE: issue:ACME-6, issue:ACME-7 (engineering); [verify ops/product/market blocked — live]
- **support_facts:** `['issue:ACME-6', 'issue:ACME-7']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## gov-v1-m2  ·  role=governance  ·  kind=normal  ·  hop=multi_abstract
- **Q:** Who are the owners of the highest-priority issues across all namespaces?
- **candidate (UNVALIDATED):** CANDIDATE: agent:cto (engineering), agent:cfo (finance); [verify other namespaces — live]
- **support_facts:** `['issue:ACME-2', 'issue:ACME-4']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## gov-v1-s1  ·  role=governance  ·  kind=normal  ·  hop=single
- **Q:** Is there any stale data (dirty nodes) currently in the KB?
- **candidate (UNVALIDATED):** CANDIDATE: [check dirty flag across all namespace nodes — verify live]
- **support_facts:** `['engineering', 'finance', 'operations', 'product', 'market']`
- **expected_decision:** pass
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## gov-v1-null1  ·  role=governance  ·  kind=null  ·  hop=single
- **Q:** What was the CFO's salary in 2025?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (no compensation data in the KB — out of KB scope)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** []
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`

## gov-v1-null2  ·  role=governance  ·  kind=null  ·  hop=single
- **Q:** Who is the VP of Legal?
- **candidate (UNVALIDATED):** CANDIDATE: abstain (no such entity in the KB)
- **support_facts:** `[]`
- **expected_decision:** abstain  ·  **forbidden_namespaces:** []
- **[ ] validated** → set `correct_answer` + `validated=true` + `reason`
