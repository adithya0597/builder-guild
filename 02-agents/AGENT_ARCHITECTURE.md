# Agent Architecture — agents as consumers of governed context

The agent layer's claim: **agents don't own knowledge; they consume governed context.** Every
design choice below follows from that inversion. A thin agent layer over a thick context layer is
the architecture, not an accident.

## 1. The read contract

An agent's ONLY read path into organizational truth is:

```python
serve(query_text, role, pattern=None, action=None)
  -> {primary, presentable_facts, composed_evidence, decision, mode, executed, provenance, trace}
```

- **`role` is a TRUST BOUNDARY.** It selects the namespace slice the agent may see (engineering →
  {engineering, shared}, etc.). It must be **authenticated upstream** — a self-asserted
  `role="oversight"` would read everything. Never expose `role` to an unauthenticated caller.
- The response is **role-scoped, validity-stamped, freshness-stamped, and gated**. The agent never
  queries the store directly; isolation is enforced before generation, not audited after.
- `trace` carries a **measured isolation self-check** (every node the answer touched, verified
  in-scope) — agents can assert on it.

## 2. Roles = namespace slices

Each functional seat (cto/engineering, cfo/finance, coo/operations, oversight/governance, …) maps
to a namespace. Two seats deserve special care:

- **Oversight reads all namespaces.** That read-all power makes it the most security-sensitive
  seat in the fleet — the overseer is the leak vector if unbounded. Bound it: audited reads,
  no write path, and a security seat that constrains it (mutual constraint, not hierarchy).
- **Naming:** keep keys functional (`agent:cto`), put display names in an alias property. Never
  couple graph keys (and therefore golden sets) to branding.
- **`role` is an authorization scope, not a performance knob.** Personas in system prompts do **not**
  reliably improve factual accuracy, and automatic persona-selection is "no better than random"
  ([Zheng et al., Findings of EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.888/)). So a
  seat governs *what an agent may read* (its namespace slice), never a hoped-for quality lift —
  output quality comes from the governed context + the gate, not from dressing the agent in a title.

## 3. Autonomy is leased, never granted

The action gate (`01-context/src/abstain.py`) runs sufficiency × confidence and is **suggest-only
until calibrated**:

```
CALIBRATED=False  ->  mode="suggest": even a "pass" decision routes to a human; execute() blocks.
CALIBRATED=True   ->  mode="autonomous": "pass" decisions may execute, for that namespace only.
```

The flip is **not a code event** — it is a governance decision taken on an evidence packet
(calibrated weights, judge-agreement κ with confidence intervals, selective-accuracy gain vs a
confidence-only baseline, isolation status). Design rules proven out by the first calibration run
(see `03-evals/CASE_STUDY_calibration.md`):

1. **Per-namespace lease, reversible.** Never a global boolean; any later sweep whose κ or gain
   drops below bar auto-reverts that namespace to suggest-only.
2. **The loss ratio is a values constant, set by a human.** "How many missed actions is one wrong
   autonomous action worth?" (the reference deployment chose 10:1 for routine actions). The
   threshold TAU* is derived from that ratio on the fitted selective-risk curve — never hand-picked.
3. **Irreversible/security action categories never lease autonomy** — they are categorically
   human-gated regardless of scores (`01-context/src/gate.py` CATEGORICAL_HUMAN).

## 4. The action-audit loop (proxy ≠ objective)

Faithfulness (the answer matched retrieved facts) does not imply decision quality (the action
helped). `src/fix_decision.py` records each gated action, attaches the realized outcome later, and
surfaces both proxy-gap directions: faithful-but-bad and unfaithful-but-good. This is the loop that
keeps the gate honest after calibration — outcomes, not vibes.

## 5. The demo

`src/demo_agent.py` is the smallest correct agent: ask through `serve()`, act only via the gate's
decision, log the audit record. ~60 lines, because the context layer is doing the work — which is
the point.

## Known limits (deliberate)

- Fleet orchestration (task routing, multi-agent coordination) is roadmap; see
  `COORDINATION_PATTERNS.md` for the patterns it will use.
- Temporal ("as of <date>") answers currently require evidence the store may not hold; the gate
  must abstain rather than answer from current state (Law: current truth ≠ historical truth). The
  first calibration run caught exactly this gap — by design.
