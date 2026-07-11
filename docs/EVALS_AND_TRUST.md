# Evaluation and Trust

The layer that decides whether a retrieved answer is *good enough to act on* — and refuses to grant autonomy until a human has seen the evidence. This is the navigable reference; the deep-dive design docs are cross-linked at the end.

**What you'll find here**

- The action gate (`abstain.py`) — sufficiency × confidence, the per-role lease, and why `execute()` blocks even a `pass` today.
- The calibration pipeline — golden sets → eRAG weights → logistic fit → debiased judge sweep → evidence packet.
- The judges — the `$0` subprocess judge and its auth/payment STOP contract.
- The eval harnesses — corrective / planner / OCR / G3 acceptance suites.
- The G1/G2/G3 roadmap track and the **calibration case study**: the real run whose sufficiency proxy fitted with a *negative* weight, so autonomy stayed OFF.

> **State it plainly up front: autonomy is NOT leased today.** `abstain.CALIBRATED` defaults every role to `False` (`01-context/src/abstain.py:26-34`). Every decision routes to a human. "Suggest-only" is the true current state — by design, not by omission.

---

## 1. Why this layer exists

Retrieval that is *relevant* is not the same as retrieval that is *sufficient to answer* — and answering correctly is not the same as being *safe to act on*. The evaluation layer scores downstream sufficiency and faithfulness, not retrieval relevance, and it gates the **action**, not just the answer. The research base (39 sources, results-table-walked) is [`03-evals/CONTEXT_EVALS.md`](../03-evals/CONTEXT_EVALS.md); the offline program that runs it is [`03-evals/README.md`](../03-evals/README.md).

Three findings drive the design (`CONTEXT_EVALS.md` §0):

1. **Relevance ≠ answer quality** — eRAG shows downstream-per-doc utility (τ 0.505) predicts answer quality far better than human relevance labels (0.179) or LLM query-doc relevance (0.049). So sources are weighted by downstream utility, never similarity.
2. **Never abstain on insufficiency alone** — SOTA LLMs answer correctly 35–62% of the time *even on insufficient context*, so a hard "abstain when insufficient" gate destroys accuracy. The validated mechanism combines a sufficiency label × self-confidence in a logistic and thresholds the output (+5–10% selective accuracy over confidence-alone).
3. **The faithfulness gate has a ~80% F1 ceiling**, worst on numbers/dates/names — so the abstain/escalate path is designed around a known ~20% error band, never treating the score as ground truth.

**Hard boundary (the seam this whole track hangs on):** offline calibration ≠ online enforcement. Heavy methods (eRAG per-unit scoring, ≥25-trial judge sweeps) *set* thresholds on a golden set, on a schedule. Nothing in `03-evals/` runs inside a live request; the online path uses only cheap deterministic-or-lightweight signals. The same action gate is described from two layers — offline eval calibrates it, `abstain.py` enforces it online.

---

## 2. The action gate — `01-context/src/abstain.py`

The runtime gate. Its shape is the validated sufficiency × confidence selective mechanism; its magnitudes are provisional until calibrated.

### 2.1 The selective score

```
selective_score(sufficiency, self_confidence)
  = sigmoid(W_SUFFICIENCY·sufficiency + W_CONFIDENCE·self_confidence + BIAS)
```

`abstain.py:52-54`. Weights are `W_SUFFICIENCY = W_CONFIDENCE = 2.0`, `BIAS = -1.5`, `TAU = 0.5` — **all flagged PROVISIONAL** (`abstain.py:36-41`), placeholders with the right shape whose magnitudes are guesses until the H2b logistic fit runs on a validated golden set. `abstain_gate()` thresholds the score at `TAU` → `{decision: act|abstain, mode: suggest|autonomous, score, calibrated}` (`abstain.py:57-68`).

The key case (proven in `demo()`, `abstain.py:155-162`): sufficiency `0.2`, confidence `0.9` → **act**. A naive sufficiency-only gate would wrongly abstain here; the combined logistic does not. That is finding #2 encoded as a test.

### 2.2 Composition with the faithfulness gate — `stage_a_decision()`

Faithfulness HARD violations gate *first and deterministically*; the sufficiency × confidence logistic is the selective gate only for clean claims (`abstain.py:71-89`):

```
stage_a_decision(claims, action, sufficiency, self_confidence, role)
  ├─ any claim UNSUPPORTED / conflict / stale  → gate() (faithfulness path)
  ├─ any claim PARTIAL                          → "partial"
  └─ otherwise                                  → abstain_gate() → pass | abstain
```

Everything here is advisory (`mode="suggest"`) until the role is calibrated. The four action-gate outcomes — **pass / partial / abstain / escalate** — are the seam bridging retrieval → agent-serve → the bi-temporal graph.

### 2.3 The CALIBRATED per-role lease (default False)

```python
CALIBRATED = {
    "engineering": False, "finance": False, "operations": False,
    "product": False, "market": False, "history": False, "governance": False,
}
```

`abstain.py:26-34`. A per-namespace dict, **default all False**, kept in exact key-parity with `scope.ROLE_NAMESPACES` (`01-context/src/scope.py:10-20`) — a drift guard in `demo()` asserts `set(CALIBRATED) == set(scope.ROLE_NAMESPACES)` (`abstain.py:150-153`). Read via `CALIBRATED.get(role, False)`. **No production/runtime code grants a lease;** only the G3 test suite (`test_g3.py`) transiently seeds `True` to verify revoke/mode behavior. Granting a real lease is a human-only edit.

### 2.4 `execute()` — suggest-only is enforced, not a label

```python
def execute(decision, action_fn):
    if decision["mode"] != "autonomous":          # uncalibrated → block even a pass
        return {"executed": False, "routed_to": "human", ...}
    if decision["final"] != "pass":
        return {"executed": False, "routed_to": "human", ...}
    return {"executed": True, "result": action_fn()}
```

`abstain.py:92-102`. This is the layer that makes "suggest-only" *functional*. An action auto-executes ONLY when `mode == "autonomous"` (i.e. the role is CALIBRATED) AND `final == "pass"`. **While uncalibrated, even a `pass` is blocked and routed to a human.** Without `execute()`, `mode="suggest"` would be just metadata; `demo()` proves a `pass` decision does not run its `action_fn` under suggest-only (`abstain.py:191-199`).

### 2.5 `auto_revert()` — REVOKE-ONLY

```python
def auto_revert(role, kappa, gain, kappa_bar=0.8, gain_bar=0.0):
    # sets CALIBRATED[role] = False when the sweep falls below either bar; NEVER sets True.
```

`abstain.py:105-132`. The asymmetry is the whole safety argument: **code can revoke autonomy, never grant it.** It revokes when measured judge-human κ < 0.8 or selective gain < 0.0, and is **fail-closed** — unmeasurable inputs (`None`/`NaN`/`inf`) are revoke-worthy by definition (`abstain.py:121-122`). Idempotent on an already-`False` namespace. The sweep wraps it in `cal4_sweep.sweep_autorevert()` / `apply_autorevert()` as process-local evidence — it never claims to revoke another running process (`03-evals/src/cal4_sweep.py:65-102`).

**The invariant, stated once:** the mechanism is public and testable; the trust grant is a manual human act (hand-edit `CALIBRATED[role] = True`). Code cannot cross that line.

---

## 3. The calibration pipeline — `03-evals/`

Each stage is a runnable module (`03-evals/README.md`). Nothing here mutates `abstain.py`; the outputs go to an evidence packet a human reads.

```
golden.py         golden-set CONTRACT: two-level labels (support_facts ⟂ correct_answer),
                  normal/null/temporal/temporal_null kinds, validated=False until signed off
gt2_draft.py      V0 draft-then-validate: an agent drafts Q + candidate + support-facts FROM
                  the live graph; a human confirms — no self-grading
golden_v1_draft.py  the 45-item graph-grounded V1 draft (validated=False, pending founder gate)
judge_adapter.py  the $0 subprocess judge (env JUDGE_CMD/JUDGE_MODEL) + auth/payment STOP contract
h2b3_judge.py     the DEBIASING harness: position-swap, length-confound FLAG, ≥25 trials, no-self-family
cal2_erag.py      eRAG source weights: each unit scored by what it ALONE answers vs gold
cal3_fit.py       the real fit: live serve() traces × human labels → sufficiency×confidence logistic
cal4_sweep.py     the full ≥25-trial debiased judge sweep (resumable, checkpointed batch)
h2b1_calib.py     fit machinery + synthetic fixture (the unit-test side of cal3)
h3_instr.py       Phase-A instrumentation: a wrapper that can score serve calls via Langfuse/
                  CaptureSink and change nothing — demoed, NOT wired into production serve()
```

### 3.1 Golden sets

**Schema — `golden.py`.** Every item carries two-level labels: a `support_facts` set (retrieval correctness — node keys and/or edge triples) stored *separately* from `correct_answer` (generation correctness). Kinds are `normal / null / temporal / temporal_null`; `null` and `temporal_null` must expect `abstain`; `validated=False` on every item until a human signs off (`golden.py:26-70`). `validate_item()` is structural-only.

**V0 draft — `gt2_draft.py`.** An agent authors question phrasings at `$0`; candidate answers + support facts are pulled deterministically from a self-owned transient graph slice. No fabrication: `correct_answer` stays `""`, `validated=False`, and the graph-derived guess goes in a separate `candidate_answer` field marked CANDIDATE (`gt2_draft.py:89-147, 193-196`).

**V1 draft — `golden_v1_draft.py`.** The 45-item graph-grounded draft (`golden_v1_review.md` stats: normal=20, null=18, temporal=7; expected_pass=27, expected_abstain=18). Drafted from 9 founder personas mapped onto the 3 role namespaces that have live entities — engineering (21), finance (5), governance (19). It adds the gate `validate_item()` cannot provide: a **live graph-existence check** that every non-abstain `support_fact` resolves against the graph, matching edges on the `name` property (every real edge is Cypher-typed `RELATES_TO`) — catching fabricated-edge and dead-node bugs (`golden_v1_draft.py:54-92`). For structural items `correct_answer` is machine-derived, but **`validated` stays `False` regardless** — a human still signs off at the founder gate (`golden_v1_draft.py:408-414`).

> **Honest scope boundary** (`golden_v1_review.md` lines 10-18): a *positive* sufficiency refit is **not demonstrable on the public 10-item example set** — its pass items have near-zero variance in the coverage signal. The public deliverable proves the signal is deterministic and no longer anti-correlated *by construction*; it does **not** claim the selective-accuracy gain was achieved.

### 3.2 The judges — `judge_adapter.py` + `h2b3_judge.py`

**The `$0` subprocess judge** (`judge_adapter.py`). Wraps any one-shot CLI judge (`$JUDGE_CMD -z <prompt> -m $JUDGE_MODEL`) as a non-self-family judge on the Codex OAuth subscription. Strict-JSON verdicts, exponential backoff, and **verdicts checkpointed to disk when callers pass `ckpt`+`key`** (cal3/cal4 do this for resumable sweeps — resume = skip already-judged keys), so a ≥25-trial sweep is reproducible. A self-family guard fires at import — a `claude`-family judge for a `claude`-family generator is rejected (`judge_adapter.py:17-22`, `h2b3_judge.py:28-33`).

**The auth/payment STOP contract** (`judge_adapter.py:29-32, 66-91`). If the judge CLI ever emits an `auth | api key | payment | billing | quota` signal, `_call()` raises immediately — the caller must STOP, never fall back to a paid key. Two holes are closed and self-tested (`judge_adapter.py:201-222`): (a) the STOP takes precedence over the returncode, and (b) a present-but-broken judge (returncode ≠ 0) with parseable stdout is **not** trusted as a verdict. When the judge CLI is simply *absent*, scoring degrades to an unscored sentinel (`judge_available()` false) — recorded, never silently counted.

**The debiasing harness** (`h2b3_judge.py`). A naive LLM judge is corrupted by position bias (>30% win-rate swing on order swap), length bias (a ~25-token gap swings win-rate >50%), and trial bias. So every judge-based metric MUST: (a) average both answer orders, (b) flag length-confounded comparisons (`length_confounded()`) so callers length-control before trusting the verdict — the harness flags, it does not itself equalize length, (c) run ≥25 trials with median + percentiles, (d) never judge with the generator's own family (`h2b3_judge.py:5-62`). Why ≥25 and not folklore: without batch-invariant kernels, 1000 identical prompts produce 80 unique completions; the trial floor absorbs judge nondeterminism the eval layer does not control (`README.md` §"Why ≥25 trials").

### 3.3 eRAG source weights — `cal2_erag.py`

The eRAG protocol scored **deterministically** for this pass: a unit's utility = the fraction of the item's human-validated `support_facts` its card (context + current edges) covers — no LLM in the scoring path, so `$0` and immune to judge bias (`cal2_erag.py:31-55`). Graph and vector rungs are scored separately, aggregated to per-source mean utility → normalized source weights; null/abstain probes are reported as **distractor exposure** (UDCG-flavored — units surfaced for an unanswerable question) (`cal2_erag.py:90-102`).

> **Known gap:** `cal2_erag.py` resolves its default golden set at `os.path.join(HERE, "example_golden.jsonl")` (i.e. `03-evals/src/`), but the file ships at `03-evals/example_golden.jsonl` — so `cal2` is **not runnable with defaults as-is**; pass an explicit path or move the file. (Source follow-up, tracked separately.)

### 3.4 The logistic fit — `cal3_fit.py`

The real fit: for each validated golden item, run live `serve(question, role)`, pull the gate's own `(sufficiency, self_confidence)` from its trace, and label whether the answer was correct vs the human gold — **deterministic-first** (ID/enum/set/abstain matchers), LLM judge (3-trial majority) only for prose items (`cal3_fit.py:101-125`). It fits the logistic, reports selective accuracy vs a confidence-only baseline, and derives `TAU*` under the **founder-locked loss ratio C(wrong act) : C(missed act) = 10:1** (`cal3_fit.py:41, 133-135`).

The fit target is the **decision channel** — `should_act = (expected == "pass") AND serve_correct`, not correctness alone; optimizing against `correct` alone wrongly rewarded acting on correctly-abstained items and collapsed `TAU*` (`cal3_fit.py:204-211`). Critically: `cal3_fit` **does not flip `CALIBRATED`** — a guard on the imported module asserts every `CALIBRATED` namespace stays `False` and `W_SUFFICIENCY` stays `2.0`, and fails the run otherwise (`cal3_fit.py:237-243`). It is an in-memory invariant check, not a file-hash/mutation guard. Fitted weights go to the evidence packet, not `abstain.py`.

### 3.5 The debiased sweep — `cal4_sweep.py`

The full ≥25-trial sweep as a resumable, checkpointed batch: pointwise match dispersion, pairwise position-bias (both orders), and easy-case agreement on deterministic items (inflated by design, labelled as such) (`cal4_sweep.py:1-24, 209-246`). It computes the discretionary judge-vs-human κ **with its N** — and on the example set N=2 → **UNMEASURABLE**, reported as such (`cal4_sweep.py:248-251`). It "does not grant leases": any `auto_revert` action is process-local evidence for founder review, fail-closed on unmeasurable κ/gain (`cal4_sweep.py:83-102, 253-260`).

### 3.6 Instrumentation — `h3_instr.py`

Phase-A: `instrument()` wraps a `serve_fn`, scores the result, emits a trace + scores to Langfuse (the **intended** production online seam per `tracing.md`), and returns the **byte-identical** output. Read-only — it observes and emits, it never gates (`h3_instr.py:67-78`). It is demoed on a local `serve` stub — **not yet wired around the real production `serve()`**. `CaptureSink` verifies the schema offline; `LangfuseSink` binds the real SDK (against a dummy-cred local host, so events are accepted then dropped at flush). Gating is Stage B; Phase A only records.

---

## 4. The eval harnesses

Acceptance suites, each a runnable `__main__`:

- **`test_g3.py`** — the G3 trust-track acceptance suite (a–h), `$0` with **zero Neo4j** (the `neo4j` package is stubbed into `sys.modules` at import). Proves: cal3/cal4 import cleanly; the real `serve._support_coverage` signal (found → 0.5, over-retrieval capped, unsupported → 0.0, `|Q|=0` → 0.0 with **no count fallback** — the anti-correlated proxy is gone); abstain items never reach the judge; per-namespace `auto_revert` revokes exactly `finance` and leaves `engineering`; the V1 draft is ≥30 items / balanced / 3 roles / all unvalidated; fail-closed sweep wiring never grants; and the G1 planner P1–P5 fold-in. Prints `G3_OK` (`test_g3.py`).
- **`eval_corrective.py`** — the Corrective-RAG loop (T1–T7): abstain→rewrite→pass flip, bounded rewrites, no-op guard, cross-role isolation across rewrites, the web-fallback `$0-or-STOP` guard, web-off-by-default, and web facts **segregated** into `web_advisory` (external-unverified, never in-scope evidence). T1–T4 are live against the seeded graph. Prints `CORRECTIVE_OK`.
- **`eval_planner.py`** — the Agentic-RAG planner (P1–P7 injection tests, `$0` via `_serve` injection; plus a Neo4j-gated `demo()`): ≥2 self-chosen distinct retrievals, bounded termination, signal-driven neighbor-hop, isolation caught, no-op guard, decompose branch, and `as_of` forwarded to every internal `serve()` call. Prints `PLANNER_TESTS_OK` / `PLANNER_OK`.
- **`eval_ocr.py`** — G2 multimodal (T1–T4): real tesseract recovery, `$0-or-STOP`, env-at-call-time, and the live end-to-end `ingest_ocr_doc → embed → serve()` retrieval + cross-role isolation demo. Prints `OCR_OK`, or `OCR_PARTIAL` when the live demo is skipped on a missing dependency (never a silent full pass).

---

## 5. The calibration case study — why the gate refused to certify

Full write-up: [`03-evals/CASE_STUDY_calibration.md`](../03-evals/CASE_STUDY_calibration.md). A complete real run of the pipeline against a live 15-node / 6-namespace demo graph, a 10-item human-validated golden set, and the `$0` cross-family judge. Every number below is a measurement from that run.

**Run 1 — the system as it stood:**

| Measure | Result |
|---|---|
| Golden accuracy | 0.40 (4/10) |
| Fitted gate | **W_SUFFICIENCY = −3.167 (negative!)**, W_CONFIDENCE = +1.304 |
| Selective accuracy | combined 0.90 vs confidence-only 0.80 → +10.0pp |
| Judge-human κ | **unmeasurable** — only 2 items needed judge discretion |

**Verdict: do not certify.** The decisive failure: **the sufficiency proxy was anti-correlated with correctness.** The proxy ("number of retrieved facts / 3") measured *how much came back*, not *whether it answers* — a cross-role probe retrieved 2 facts (high "sufficiency") and was wrong; the correct abstentions scored 0. Calibrating that proxy into an autonomous gate would have *armed a harmful one*. This is the core lesson: a negative fitted weight on a "sufficiency" signal is the eval layer telling you the proxy is broken — **refusing to certify is a success mode** (`README.md` scoring rule #4).

**Run 2 — after fixing answer-shape / composition / a keyword-ID rung:** golden accuracy rose to 0.80, but **W_SUFFICIENCY stayed negative (−4.089)** — the proxy needs *replacing*, not more data. And better retrieval *unmasked* a temporal-truth violation (an as-of probe that had been "passing" only because retrieval was too weak to find the node), which moved the temporal-evidence layer up the roadmap.

**What the run claims — and refuses to claim:** the machinery runs end-to-end on live data at `$0` judge cost; a sufficiency × confidence gate beats confidence-alone selectively (+10pp, consistent with the published effect). But **N=10 is a smoke test** — no research-grade claim, κ unmeasured, the autonomy flag off. The calibration's most valuable outputs were its refusals.

**A second refusal — the autonomy boundary.** Even once a namespace is calibrated, autonomy is bounded to answers the system can *structurally validate* — an answer backed by a presentable graph edge whose relation matches the query's intent. A correctly-answered-but-text-only fact (status is the canonical case) stays suggest-only, because disambiguating intent by lexical rule is too fragile to gate an action. **Correctness is necessary for action; it is not sufficient.**

---

## 6. The founder gate — the manual trust grant

`abstain.CALIBRATED` defaults every role to `False`, so the public deliverable demonstrates *refusal mechanics and lease prerequisites*, not a production autonomy policy. Before any namespace flips (`golden_v1_review.md` lines 20-30):

1. Validate golden_v1 — confirm/correct `correct_answer` + set `validated=true` per item.
2. Run `cal3_fit` on the validated set + local graph + judge CLI → confirm a **positive** W_SUFFICIENCY refit.
3. Run the `cal4_sweep` (~22 min) → κ ≥ 0.8 with a 95% CI excluding 0.6.
4. Read the evidence packet (`cal3_fit_results.json` + `cal4_results.json`).
5. **Manual lease grant** — hand-edit `abstain.CALIBRATED[role] = True`. **This is a human-only action; `auto_revert()` can revoke but never grants.**
6. Confirm a deliberately-bad sweep actually reverts before trusting any flip.

No autonomy flip happens before steps 1–5 complete for that namespace.

---

## 7. The G1 / G2 / G3 roadmap track

Full roadmap with acceptance tests: [`docs/ROADMAP.md`](ROADMAP.md).

| Track | State | Notes |
|---|---|---|
| **G1 — Agentic RAG** | ✅ **CLOSED** | `planner.py` self-chooses ≥2 distinct retrievals, bounded, isolation-clean; agent-callable via the stage-scoped MCP `plan_context` tool. Output stays **suggest-only** — G1 is orthogonal to the G3 lease. |
| **G2 — Multimodal RAG** | ✅ **CLOSED** (OCR-first) | `etl.ingest_ocr_doc` embeds OCR text via `embed.embed_node` at ingest, retrieved through the live `serve()` vector rung. OCR/hybrid by design, **not** vision-default (OCR beat ColPali in all evaluated settings in the cited study). Verify remaining scope in `ROADMAP.md`. |
| **G3 — Calibration / autonomy** | 🔲 **OPEN + FOUNDER-GATED** | Blocks the autonomy lease. The latest measured run refit `W_SUFFICIENCY` **positive** but **failed the selective-gain bar (−3.0pp)** (`ROADMAP.md:18-22`), so `CALIBRATED` stays `False` **by design**. (The earlier public case study, §5, is the run whose weight fitted *negative* — a distinct, older refusal.) Items 2→3→4→5: a real sufficiency signal → decision-channel scoring (✅ shipped) → golden-set v1 for measurable κ → the reversible per-namespace lease. |

**G3 acceptance:** sufficiency refits **positive** with a selective gain over confidence-only; κ ≥ 0.8 with a CI excluding 0.6 on golden v1; then exactly one namespace flips to autonomous via the reversible lease and the regression stays green.

Non-goals (by design): prompt-time conflict resolution (conflicts resolve structurally in the store), relevance-tuned retrieval (weight by downstream utility, not similarity), and any autonomy flip without a human reading the evidence packet.

---

## Source of truth

Files this doc documents (read these for the exact behavior):

- `01-context/src/abstain.py` — the action gate, per-role lease, `execute()`, `auto_revert()`
- `01-context/src/scope.py` — `ROLE_NAMESPACES` (the lease keyspace)
- `03-evals/src/golden.py`, `gt2_draft.py`, `golden_v1_draft.py` — golden-set contract + drafts
- `03-evals/src/judge_adapter.py`, `h2b3_judge.py` — the `$0` judge + debiasing harness
- `03-evals/src/cal2_erag.py`, `cal3_fit.py`, `cal4_sweep.py`, `h2b1_calib.py`, `h3_instr.py` — the calibration pipeline
- `03-evals/src/test_g3.py`, `eval_corrective.py`, `eval_planner.py`, `eval_ocr.py` — acceptance suites
- `03-evals/golden_v1_review.md` — the founder review sheet

## See also (the design deep-dives)

- [`03-evals/CONTEXT_EVALS.md`](../03-evals/CONTEXT_EVALS.md) — the eval-layer research base (11-dimension matrix, 39 sources, the offline-vs-online split).
- [`03-evals/CASE_STUDY_calibration.md`](../03-evals/CASE_STUDY_calibration.md) — the real calibration run, the negative-weight refusal, the autonomy boundary.
- [`03-evals/README.md`](../03-evals/README.md) — the pipeline overview + scoring rules that survived contact with reality.
- [`docs/ROADMAP.md`](ROADMAP.md) — G1/G2/G3 in capability terms, with acceptance tests.
