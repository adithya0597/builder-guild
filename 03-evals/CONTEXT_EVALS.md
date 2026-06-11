# CONTEXT_EVALS.md — the eval layer: validating that retrieved context is the *right* context

Date: 2026-06-02. **This is the missing layer** of the context engineering + management architecture (it was scoped 🔲 in `CONTEXT_LAYER_INDEX.md`; this fills it). It defines how we validate that what the KB serves is the right context — not merely relevant, but **sufficient to answer** and **faithfully used** — and how every provisional parameter in `HYBRID_RETRIEVAL_ARCHITECTURE.md` gets calibrated instead of asserted.

Grounded by three parallel research streams (2026-06-02): academic paper-walk (17 papers, 11 table-walked), eval-tooling deep-dive (RAGAS/TruLens/ARES/DeepEval/Phoenix/Langfuse/RAGChecker), and graph/hybrid/temporal benchmarks (GraphRAG/HippoRAG/LOCOMO/conflict). Every number tagged `[paper-walked]` (results table read), `[verified-from-docs]` (official doc read), `[abstract-only]` / `[claimed]` (secondary), or `[design-synthesis]` (ours). Numbers are VERIFIED / COMPUTED / LABELED-ESTIMATE per the no-handwaving rule.

---

## §0 — The thesis (why this layer exists, and why it is NOT a relevance gate)

Three load-bearing findings reframe the whole layer. If you read nothing else, read these.

1. **Relevance ≠ answer quality.** `eRAG` (arxiv 2404.13781, SIGIR'24) [paper-walked] measures how well each retrieval-quality signal predicts downstream answer quality (Kendall τ on NQ): **downstream-per-doc utility τ=0.505**, "contains the answer" 0.357, **human relevance labels (KILT provenance) 0.179**, **LLM-judged query-doc relevance 0.049**. HotpotQA: 0.612. → Optimizing graph/vector/PageIndex on relevance (nDCG, cosine) does **not** reliably improve answers. **Our eval layer must score downstream sufficiency + faithfulness, not retrieval relevance.** Corroborated by `UDCG` (arxiv 2510.21440) [paper-walked]: a utility metric that penalizes confident distractors with *negative* score correlates **+36% better** with answer accuracy than nDCG (Llama-8B/NQ ρ 0.611 vs 0.515); hard distractors drop accuracy up to **9.11pp** on contexts that score *identically* under nDCG/MAP/MRR.

2. **Sufficiency must pair with confidence — never abstain on insufficiency alone.** `Sufficient Context` (arxiv 2411.06037, Google, ICLR'25) [paper-walked]: SOTA LLMs answer correctly **35–62% of the time even when context is insufficient**, so a hard "abstain when insufficient" gate *destroys* accuracy. The validated mechanism: combine a **sufficiency label × self-confidence** in a logistic regression, threshold its output → **+5–10% selective accuracy** over confidence alone. Below ~18% baseline accuracy the sufficiency signal adds nothing.

3. **The faithfulness gate has a hard ceiling (~80% F1), worst exactly on numbers/dates/names.** `AttributionBench` (arxiv 2402.15089, ACL'24-Findings) [paper-walked]: the best automatic attribution evaluator caps at **77.7% (ID) / 81.9% (OOD) macro-F1**; **66% of its errors are fine-grained** (numbers, dates, names, logical connectors). → Design the abstain/escalate threshold and the human-escalation path around a known ~20% error band; never treat the faithfulness score as ground truth.

**Cross-cutting mandate — LLM-as-judge debiasing (governs every gate below).** `An Unbiased Evaluation Framework for GraphRAG` (arxiv 2506.06331, 2025) [paper-walked] proves naive LLM-judge eval is corrupted by: **position bias** (>30% win-rate swing on identical inputs after order swap), **length bias** (a 25-token gap on ~200-token answers swings win-rate >50% — judges reward verbose), **trial bias** (5 trials give contradictory verdicts). Debiased, **LightRAG vs NaiveRAG flips 66.70% → 39.06% — NaiveRAG wins.** Confirmed by `Judging LLM-as-a-Judge` (2306.05685) [paper-walked]: GPT-4 flips its verdict **35%** of the time on order swap; verbosity-attack failure rate GPT-4 8.7% / GPT-3.5 & Claude 91.3%; and `G-Eval` (2303.16634) [paper-walked]: a judge **always over-scores its own model family** even when humans prefer the other. **Every judge-based gate in this doc MUST: (a) average over both answer orders (position-swap), (b) length-control candidates, (c) run ≥25 trials reporting median + percentiles, (d) never judge with the generator's own model family ungrounded.** Single-judge ceiling is ~85% pairwise agreement / ρ≈0.51 pointwise — that is the realistic best case (`Judge's Verdict` 2510.09738 [paper-walked]: best LLM judge Cohen's κ=0.813 vs human-human κ=0.801).

> Graph subgraphs are systematically **longer** than vector chunks → a naive judge prefers them regardless of quality. Our source-weight calibration is the exact scenario 2506.06331 warns about. Length-control is non-optional here.

**Hard principle — offline calibration ≠ online enforcement.** Most heavy methods here (eRAG per-unit scoring, ≥25-trial debiased judge sweeps, RAGChecker, ARES PPI) are **offline calibration** — they *set* thresholds/weights on a golden set, on a schedule. They are **not** runtime gates: you cannot run a 25-trial judge study or per-unit eRAG inside a live request. The **online** path uses only cheap, deterministic-or-lightweight signals (namespace/ACL filters, a small sufficiency classifier + confidence, token/context-perplexity, citation-required generation). §1's per-gate table makes the split explicit; **never wire an offline metric as a live decision signal.**

---

## §1 — The eval dimension matrix

Each row = one validation dimension → the gate it feeds in `HYBRID_RETRIEVAL_ARCHITECTURE.md`. Method + dataset + grounded anchor + depth tag. Dimensions 1–11 cover the full engineering + management surface.

### 1. Retrieval correctness, per source
*Validates:* did each source surface the right units? Scored **separately per source** (graph / vector / PageIndex) because their epistemic roles differ, and **separately from generation** (two-level scoring: support-fact F1 distinct from answer F1 — the multi-hop-QA field standard).
- **Graph:** triple/edge precision & recall, path-consistency, **minimal-sufficient-subgraph** (arxiv 2603.07179 [abstract-only] — smallest subgraph that still answers; a *direction* for our blast-radius metric, **not an established standard** — penalize over-retrieval). We did not find an off-the-shelf standard for edge-granularity P/R in this review — **we define it** (loose anchors: Path-Consistency, GraphRAG-Bench AR-score). Multi-hop bridge correctness via 2WikiMultiHopQA evidence-triple F1, MuSiQue (shortcut-resistant).
- **Vector:** precision@k, recall@k, nDCG@k, MRR — but per §0, treat as **recall instrumentation, not an authority signal**. BEIR (arxiv 2104.08663) [paper-walked]: dense retrievers generalize *worse* than BM25 zero-shot (DPR −47.7%, ColBERT +2.5% vs BM25; BM25+CE rerank **+11%**, wins 16/18 datasets) → vector = recall-only, confirmed empirically.
- **PageIndex:** section/page-selection correctness on long docs (did the ToC-navigation pick the right sections). Eval per `PAGEINDEX_PILOT.md` (hit-rate vs vector baseline on multi-section queries).
*Anchor:* eRAG per-source downstream protocol (§2). *Gate:* per-source admission + the source-weight calibration.

### 2. Hybrid fusion correctness
*Validates:* did fusion pick the right source per query, and does adding a source **help or hurt**?
- **RRF** (Cormack 2009 [abstract-only], k=60) is *unconditional* — it fuses by rank, can't decide *whether* a source should contribute. That gap is the real eval target.
- **Complementarity / when-to-fuse:** `GraphRAG-Bench` (arxiv 2506.02404) [paper-walked] proves graph retrieval **underperforms vanilla on whole task classes** (MC, **math — all GraphRAG methods degrade**, fill-in-blank); it beats vanilla by only **1–2 points overall** (RAPTOR 73.58 / HippoRAG 72.64 / GraphRAG 72.50 vs GPT-4o-mini 70.68). → the fusion gate must be able to **down-weight or suppress a source per query class**, not fuse blindly.
- **Source attribution:** persist a per-query `score_breakdown` (which source contributed each surfaced unit) — matches the hybrid-RRF pattern seen in the wild (last30days GitHub finding) and is required to evaluate complementarity.
*Gate:* when-to-fuse gating + RRF; rerank stage (BEIR shows rerank > naive fusion).

### 3. Context sufficiency
*Validates:* is the retrieved context **enough to answer** (the distinction relevance misses)?
- **Mechanism:** the `Sufficient Context` autorater [paper-walked] — a no-ground-truth-answer LLM classifier labeling (query, context) sufficient/insufficient. **Gemini-1.5-Pro 1-shot: 93.0% acc / 0.935 F1** (vs entailment-based TRUE-NLI 82.6%, which needs the answer). Cheap production variant: fine-tuned FLAMe 87.8%.
- **Caveat (load-bearing):** do **not** gate on this alone (§0 finding 2). Feeds the abstain gate only in combination with confidence.
*Gate:* the abstain/escalate decision (dim 10).

### 4. Faithfulness / groundedness / attribution
*Validates:* is every answer claim grounded in (attributable to) a retrieved unit?
- **Faithfulness** = |supported statements| / |total statements| (RAGAS formal def, arxiv 2309.15217 [paper-walked], validates **0.95** vs human — the most reliable RAGAS metric; its Context-Relevance validates only 0.70). Reference-free.
- **Attribution** = NLI-entailment of the cited unit(s) (ALCE, arxiv 2305.14627 [paper-walked]: Citation Recall + Precision track humans within ~1–4 pts; ChatGPT w/rerank 84.8/81.6 on ASQA; **~50% of even best-model generations lack full citation support** on ELI5). This is also our **isolation** instrument (dim 8) — every sentence must trace to a unit.
- **Ceiling:** ~80% F1, worst on numeric/date/name claims (AttributionBench, §0 finding 3). Atomic-fact decomposition (FActScore, arxiv 2305.14251 [abstract-only]: estimator <2% error) for per-claim granularity; RAGTruth (arxiv 2401.00396 [abstract-only]: 18k span-level, FT small LLM matches GPT-4) as training data for a cheap inline detector.
*Gate:* §4 faithfulness gate (`HYBRID` §4); part of the action gate.

### 5. Temporal validity
*Validates:* do "as-of" / point-in-time queries return the fact that was valid *then*, and is supersession applied?
- **As-of template:** `TempLAMA` (arxiv 2106.15110 [abstract-only]) — cloze-by-year, same fact different valid answer per time-slice. This is the cleanest model for our bi-temporal `valid_at`/`invalid_at` correctness test.
- **Empirical hardness:** `LOCOMO` (arxiv 2402.17753, Snap) [paper-walked] — **temporal is the worst category: 20.3 F1** (vs human 87.9 overall, best model 37.8 overall). Use **graded temporal distance, not binary EM** (arxiv 2509.16720: EM can't tell a 1-year miss from a 50-year miss).
- **We did not identify a public per-fact bi-temporal validity benchmark in this review** → **we build one** (synthetic supersession episodes; assert as-of correctness via Cypher point-in-time queries, see `HYBRID` PART 3-A).
*Gate:* validity-stamping at retrieval; supersession correctness.

### 6. Freshness / staleness / surgical blast-radius
*Validates:* is stale context detected, and is the surgical re-embed/refresh bounded correctly (no over- or under-refresh)?
- **Staleness detection:** consider LongMemEval's **knowledge-update** category (arxiv 2410.10813, ICLR'25 [abstract-only] — it *reports* commercial assistants dropping ~30% accuracy over sustained interaction; abstract-level, not table-walked).
- **Blast-radius correctness:** **minimal-sufficient-subgraph** (2603.07179 [abstract-only]) + GraphRAG-Bench **AR-score** (answer correct *with* correct reasoning) are the **closest analogs found** to "refreshed exactly what changed, nothing more" — directional, not established metrics.
*Gate:* freshness lifecycle + surgical refresh (`HYBRID` PART 3-B/C).

### 7. Conflict-correctness
*Validates:* are contradictory facts detected and resolved correctly (update vs stale, source-vs-source)?
- **Current literature signal (pending deeper verification — the sources below are abstract-only):** LLMs appear **weak at both detecting contradictions and overwriting stale beliefs.** `WikiContradict` (arxiv 2406.13805, NeurIPS'24, 253 human-annotated real contradictions [abstract-only]): subpar detection, worst on perspective conflicts. `DynamicQA` (in arxiv 2403.08319 [abstract-only]): **LLMs fail to overwrite parametric knowledge under conflict.** `ConflictBank` (arxiv 2408.12076 [abstract-only]): systematic context-memory + inter-context conflict suite.
- **⟹ resolve conflict STRUCTURALLY in the store (bi-temporal edge-invalidation + recency), NOT at the prompt at answer time.** This is the empirical validation of the MATCH-driven supersession in `HYBRID` PART 3-D. The eval scores store-level resolution correctness, not LLM judgment.
*Gate:* the conflict ladder (`HYBRID` PART 4).

### 8. Isolation (no cross-CXO-role leakage)
*Validates:* a query scoped to one CXO role never surfaces another role's private context.
- **Primary mechanism = deterministic, not judged:** a **namespace/ACL filter on retrieved units, applied before generation** — any unauthorized unit entering context is a **hard fail**. Leakage=0 is enforced structurally; a noisy post-hoc judge never guards a hard security property.
- **Attribution (dim 4) is the *audit*, not the gate:** sample answers, verify every surfaced unit's namespace matches the query's role — catches filter bugs, never substitutes for the filter.
- **Offline eval:** per-role suite with planted cross-role facts (scaffold: MultiHop-RAG **null-query**, arxiv 2401.15391 [abstract-only] — answer-not-present → must not fabricate); **no public benchmark identified in this review**; leakage-rate target = 0 (hard gate, not baseline-relative).
*Gate:* isolation gate (`HYBRID` §4); APC action gate.

### 9. Routing / iteration (retrieve-or-not, T-cap, re-query)
*Validates:* the retrieve-or-not decision and the retrieval-iteration cap.
- **Inline gate map:** `Self-RAG` (arxiv 2310.11511, ICLR'24) [paper-walked] — reflection tokens `Retrieve`→`IsRel`→`IsSup`→`IsUse` (relevance→groundedness→utility); `CRAG` (arxiv 2401.15884) [paper-walked] — a lightweight T5-large (0.77B) retrieval evaluator with **two thresholds → {correct: refine / incorrect: web-search / ambiguous: both}** (CRAG over RAG: **+19.0 PopQA, +14.9 Bio, +36.6 PubHealth, +8.1 ARC**).
- **T-cap:** `Adaptive-RAG` (arxiv 2403.14403, NAACL'24) [paper-walked] — adaptive routing gets ~95% of multi-step quality at **~half the steps (2.17 avg vs 4.69)**; but the complexity-classifier is only **0.31–0.66 accurate per class** → keep **T≈3 as a hard ceiling**, don't trust a per-query router to set it.
*Gate:* RCR routing + retrieve-or-not + T-cap (`HYBRID` PART 2).

### 10. Decision / action gate (abstain / escalate calibration)
*Validates:* when to answer, abstain, or escalate.
- **Mechanism:** sufficiency-label × self-confidence → logistic → threshold (Sufficient Context [paper-walked], +5–10% selective accuracy). Escalation template = CRAG's 2-threshold correct/incorrect/ambiguous buckets.
- **Cheap pre-filters** (before a full autorater call): token-probability drop (`FLARE` arxiv 2305.06983 [paper-walked]: trigger re-retrieval at **θ=0.8**, mask query tokens at **β=0.4**) and context-perplexity (`Predicting Utility` arxiv 2601.14546 [paper-walked]: PerpC adds ~0.04 Kendall over QPP — a pre-filter, not a standalone gate).
- **Abstention proxies for the eval set:** LOCOMO adversarial category (2.1 F1 — the stress test), MultiHop-RAG null query, LongMemEval abstention.
*Gate:* APC-ported VoteCalculator + DecisionRouter (`HYBRID` §4); the abstain blocks the **action**, not just the answer.

### 11. Methodology spine (applies to all 10)
- **Golden-set construction:** `RAGAS TestsetGen` [verified-from-docs] — KG-based synthetic Q&A, distribution 50% single-hop / 25% multi-hop-abstract / 25% multi-hop-specific; **per-CXO-role** sets. Plus a committed **golden retrieval set** scored with `hitRate@k` + `ndcg@k` (the deterministic-baseline pattern). Two-level scoring throughout (support-fact F1 ⟂ answer F1).
- **Downstream-utility labeling:** eRAG protocol — feed each retrieved unit alone, score its answer vs GT, that *is* the unit's relevance label (τ 0.505 vs 0.179 for human labels; **50× less GPU memory** than end-to-end).
- **Nugget recall** (answer completeness): AutoNuggetizer / TREC-RAG (arxiv 2504.15068, SIGIR'25 [paper-walked]) — run-level τ **0.887** (trustworthy for aggregate gate calibration) but per-topic τ **~0.49** (noisy for single-query decisions — use aggregate only).
- **Judge calibration:** the §0 debiasing mandate (position-swap, length-control, ≥25 trials, no self-family). Optionally ARES-style PPI confidence intervals (arxiv 2311.09476 [verified-from-docs]: DeBERTa judges + 150 human labels → 95% CIs; **+59.9pp context-relevance accuracy vs RAGAS**).
- **Significance:** every gate threshold reported with n + confidence interval; no single-point claims.

### Failure taxonomy (so one miss isn't labelled three different ways)
Every eval failure gets exactly ONE primary bucket — this stops the same miss being counted under sufficiency *and* faithfulness *and* fusion:
1. **retrieval-miss** — the right unit was never retrieved (recall failure).
2. **distractor-contamination** — an irrelevant/confident-wrong unit entered context (negative-utility, UDCG).
3. **insufficient-context** — units retrieved but not *enough* to answer.
4. **unsupported-synthesis** — answer asserts what the (sufficient) context doesn't support.
5. **temporal-mis-scope** — returned a fact valid at the wrong time (as-of / supersession).
6. **unresolved-conflict** — contradictory facts surfaced without store-level resolution.
7. **isolation-leak** — a unit outside the query's role/namespace entered context.
8. **wrong-abstain/escalate** — answered when it should have abstained, or vice-versa.

One primary label per case (+ optional secondary); gate metrics computed per-bucket. This is what keeps dims 1–10 actually separable instead of collapsing into one fuzzy "miss."

### Offline calibration vs online enforcement (per gate)
What *sets* each gate (offline, scheduled, expensive) vs what *runs* in a live request (cheap, deterministic-or-lightweight). **Never wire the left column as a runtime signal.**

| Gate | OFFLINE calibration (golden set, scheduled) | ONLINE runtime signal (per request) |
|---|---|---|
| Sufficiency | sufficiency-autorater benchmark; selective-accuracy curves | lightweight sufficiency classifier + self-confidence + retrieval-coverage features |
| Faithfulness | sampled citation/attribution audit (ALCE / RAGAS / RAGChecker) | citation-required answer path + escalation on numeric/date/name claims |
| Isolation | planted-leakage eval suite | **deterministic namespace/ACL filter, hard-fail** (never a judge) |
| Source weights | eRAG per-unit downstream calibration | precomputed per-query-class weights (lookup, not live eRAG) |
| Fusion / when-to-fuse | offline ablations per query class | query-class router → fixed fusion policy |
| Temporal validity | as-of/supersession test suite | store-level Cypher point-in-time query (deterministic) |
| Conflict | conflict test suite | store-level edge-invalidation/recency (deterministic, not prompt-time) |
| Routing / T | recall(T) curves; complexity-classifier study | fixed T-cap (≈3) + retrieve-or-not signal |
| Abstain / escalate | sufficiency×confidence logistic fit | thresholded logistic score + CRAG-style buckets |
| Judge gates | ≥25-trial debiased sweeps (position/length controlled) | — (judges are calibration-only; never in the hot path) |

---

## §2 — Calibrating the architecture's open parameters

Each provisional value in `HYBRID_RETRIEVAL_ARCHITECTURE.md` → how it gets *set* (not asserted) + the grounded basis. **This table specifies *how* each provisional parameter will be calibrated — the calibration is actually *run* in §7-B (research-grade DoD), not asserted here.**

**Routing ontology (the query classes the gates condition on — names the "query-type-conditional" work explicitly):** `direct-lookup` · `bridge-multi-hop` · `long-doc-section-nav` · `temporal-as-of` · `conflict/update-sensitive` · `role-scoped/private`. Source behavior, fusion, and T are calibrated *per class*, not globally.

| Param (provisional) | How to calibrate | Grounded basis | Depth |
|---|---|---|---|
| **Source weights** (graph=fact / vector=recall / PageIndex=prose) | Tune on **eRAG per-source downstream signal**, NOT relevance. Make weights **query-type-conditional** (graph wins comprehensiveness/diversity; vector wins **directness** — point-lookups). Penalize confident distractors (negative UDCG utility). | eRAG τ 0.505 vs 0.179; GraphRAG directness-loss + 1–2pt overall (2404.16130, 2506.02404); HippoRAG2 **+2.8 F1 avg**, concentrated in 2Wiki bridge-multi-hop (2502.14802); BEIR dense-fragility | `[paper-walked]` |
| **Iteration cap T ≈ 3** | Keep as a **hard ceiling**. Plot recall(T) on the golden set; expect diminishing returns past ~3. Do NOT let a per-query complexity-router set it (only 0.31–0.66 accurate). | Adaptive-RAG steps 2.17 vs 4.69 (~95% quality at half); FLARE/CRAG re-query ≤ couple; LazyGraphRAG budget-scaling | `[paper-walked]` (router acc); `[abstract-only]` (LazyGraphRAG blog) |
| **Drift threshold τ** | Use **context-perplexity** + token-prob as the cheap drift trigger; calibrate against staleness-labeled set. RAGChecker's relevant- vs irrelevant-noise-sensitivity split measures exactly what τ suppresses. | FLARE θ=0.8/β=0.4 [paper-walked]; PerpC +0.04 Kendall [paper-walked]; RAGChecker [verified-from-docs] | mixed |
| **Faithfulness gate** | Threshold with a known **~80% F1 band**; route the ~20% (esp. numeric/date/name claims) to human-escalation. | AttributionBench 77.7–81.9% F1, 66% errors fine-grained [paper-walked]; RAGAS faithfulness 0.95 vs human [paper-walked] | `[paper-walked]` |
| **Abstain / escalate τ** | **sufficiency × confidence → logistic → threshold** (never sufficiency alone). CRAG 2-threshold buckets as the escalation shape. | Sufficient Context 35–62% correct-on-insufficient, +5–10% selective [paper-walked]; CRAG [paper-walked] | `[paper-walked]` |
| **Conflict resolution** | Validate **store-level structural** resolution (edge-invalidation/recency), NOT prompt-time LLM judgment. | WikiContradict + DynamicQA: LLMs poor at detection AND overwrite [abstract-only] | `[abstract-only]` |
| **Judge calibration** (cross-cutting) | position-swap + length-control + ≥25 trials + dispersion + no self-family. | 2506.06331 (66.70→39.06 flip), 2306.05685 (35% flip), G-Eval self-pref [all paper-walked] | `[paper-walked]` |

---

## §3 — Tooling: which framework for which gate

Anchored to the tooling stream's comparison ([verified-from-docs] unless noted). Principle: **Langfuse is the online seam** (already mandated by `tracing.md`), RAGAS/RAGChecker the offline depth, the Sufficient-Context autorater the abstain gate, eRAG the source-weight protocol.

| Gate / need | Tool | Why | Note |
|---|---|---|---|
| Online scoring on live traces | **Langfuse evals** | `@observe()` + `as_type='retriever'` spans already mandated → add async LLM-judge evaluators in ~4 lines; scores join the same trace tree as cost/latency | **lowest-friction path**; but async/post-hoc — **cannot block generation** (inline logic needed for the abstain gate) |
| Faithfulness + context P/R (offline audit) | **RAGAS v0.4** | canonical formulas; faithfulness validates 0.95 vs human; reference-free faithfulness for live, reference-based context-recall for periodic audit | context-recall *always* needs a reference; its Context-Relevance only 0.70 — weakest metric |
| τ drift / noise diagnosis | **RAGChecker** | among the reviewed tools, the one separating **relevant-** vs **irrelevant-noise-sensitivity** → directly measures what τ gates | needs GT answer; batch |
| Abstain / sufficiency gate | **Sufficient-Context autorater** (Google method) | 93% acc, no-GT, designed for inference-time | combine with confidence (logistic), don't gate alone |
| Source-weight calibration | **eRAG protocol** | among the reviewed methods, the one that best correlates with downstream answer quality | 50× cheaper than end-to-end |
| OTel-native tracing eval | **TruLens RAG triad** | context-relevance / groundedness / answer-relevance; least instrumentation if already OTel | reference-free; no recall signal |
| High-stakes domain judge | **ARES** | DeBERTa judges + PPI CIs; +59.9pp vs RAGAS context-relevance | needs 150+ human labels + per-domain fine-tune |
| Custom branching criteria (isolation, format) | **DeepEval DAG / G-Eval** | decision-tree LLM eval for isolation namespace checks | CI/CD focused |

**A structural limit (logical, not benchmarked):** these tools validate response↔context *consistency*, not whether the context itself is *true* — a consistency check cannot certify source-corpus accuracy. (A single secondary source [claimed: atlan] reports entity-swapped negatives fooling several frameworks; treat as illustrative, not established.) Corpus-truth stays a human/provenance concern; our conflict + temporal gates only partially touch it.

---

## §4 — The golden eval set (build spec)

1. **Per-CXO-role datasets** (6 roles) — RAGAS TestsetGen KG-based generation over each role's corpus slice; 50/25/25 single/multi-hop-abstract/multi-hop-specific.
2. **Golden retrieval set** — committed, deterministic ordering, scored `hitRate@k` + `ndcg@k` (CI-stable baseline).
3. **Two-level labels** — support-fact/triple set (retrieval correctness) *separate from* answer (generation correctness).
4. **Null queries** — answer-not-in-KB, for abstention + isolation (planted cross-role facts → leakage must be 0).
5. **Temporal episodes** — synthetic supersession chains for as-of + invalidation correctness (we build; no public benchmark).
6. **Downstream-utility labels** — eRAG per-unit answer scoring for source weights.

Public benchmarks to track as external sanity-checks (not our primary set): LongMemEval (memory: update + temporal + abstention), LOCOMO (temporal + adversarial), MuSiQue/2Wiki (multi-hop bridge), BEIR (retrieval generalization).

---

## §5 — Honest gaps (what we did not find public ground truth for, in this review)

- **Cross-CXO-role isolation** — no benchmark identified; we define (null-query scaffold; leakage=0 enforced deterministically, see dim 8).
- **Per-fact bi-temporal validity** — no benchmark identified; we build (TempLAMA cloze-by-year as the template).
- **Graph-vs-vector-vs-PageIndex source weighting** — we found no direct published prior coupling *graph* retrieval to answer faithfulness; eRAG's per-source downstream protocol is the closest transferable method found.
- **Edge/triple-granularity P/R** — no canonical formalization identified; Path-Consistency + minimal-sufficient-subgraph are loose directional anchors, not standards.

---

## §6 — Evidence ledger + corrections

**Corrections caught by this research (do NOT propagate the errors):**
- ⚠️ **"Zep 84% on LOCOMO" is WRONG** — that figure is a *contested vendor blog claim*, **not in arxiv 2501.13956** (the Zep paper uses DMR 94.8% + LongMemEval gpt-4o **71.2% vs 60.2% full-context, +18.5% rel**). Mem0 re-scored the blog's LOCOMO to **58.44%**; Zep counter-claimed 75.14%. **Cite LongMemEval (the paper's actual benchmark), never "Zep 84% LOCOMO."** (The existing `RETRIEVAL.md`/`EVIDENCE_LOG.md` "Zep +18.5%, LOCOMO F1 13.9–32.1" is fine — +18.5% is LongMemEval; 13.9–32.1 is LOCOMO's *own* paper numbers — but verify no doc asserts the 84% conflation.)
- HippoRAG "+20%" headline maps to 2Wiki Recall@5; an OCR artifact in extraction means the "20%" *phrasing* is `[paper-walked, verify phrasing]` though the underlying **+32pt 2Wiki Recall@5** is solid.

**Review trail:** an internal adversarial pass + 3 independent reviewers (2026-06-02) → *APPROVE WITH REVISIONS*. Revisions applied: claim-hygiene (softened abstract-only sources that carried prescriptive weight; "only tool/method"→"among reviewed"; "no benchmark exists"→"not identified in this review"; ATLAN universal claim softened to illustrative; minimal-sufficient-subgraph demoted from metric to direction); **offline-calibration-vs-online-enforcement split** (new §1 table + staged §7 DoD); **deterministic-first isolation** (dim 8 namespace/ACL filter primary, attribution as audit); **explicit routing ontology** (§2, 6 query classes); **failure taxonomy** (§1). Held: the structural-conflict-resolution and store-level-temporal-validity *direction* (architecture call stands; only the certainty language was softened).

**Paper-walked anchors (results table read):** Sufficient-Context, eRAG, UDCG, Predicting-Utility, RAGAS, ALCE, AttributionBench, Judging-LLM-Judge, G-Eval, AutoNuggetizer, Self-RAG, CRAG, Adaptive-RAG, FLARE, GraphRAG, GraphRAG-Bench, HippoRAG 1&2, LightRAG, Unbiased-GraphRAG-Eval (2506.06331), BEIR, LOCOMO, Zep, Judge's-Verdict.
**Abstract-only / [claimed] (re-verify before a number becomes a load-bearing constant):** FActScore, RAGTruth, LLMs-not-Fair-Evaluators, MultiHop-RAG retrieval Hits@K, TempLAMA/CronQuestions/TimeQA, LongMemEval, ConflictBank/WikiContradict/DynamicQA, LazyGraphRAG, RRF.
**Local extracts (re-check exact cells):** `/tmp/{suffctx,erag,adaptiverag,alce,predutil}.txt`.

---

## §7 — Definition of Done (two stages — don't let the eval program become a ship-blocking wall)

**Stage A — Production-beta DoD** (ship a trustworthy beta on these; deterministic gates + fixed defaults + sampled audits):
1. Langfuse tracing live on retriever spans; sampled offline faithfulness audits running.
2. Small per-CXO golden retrieval set + null queries committed; retrieval baselines (hitRate@k / ndcg@k) recorded.
3. **Isolation leakage = 0** via the deterministic namespace/ACL filter (dim 8) + planted-leakage probes.
4. Store-level temporal/supersession + conflict tests passing (Cypher as-of, deterministic).
5. **Fixed T-cap (≈3)**; citation-required answer path + abstain on risky (numeric/date/name) claim types.
6. Simple fusion ablations per query class.

**Stage B — Research-grade eval-layer DoD** (deepen *after* beta; NOT a prerequisite to ship):
1. Full **eRAG** per-unit source-weight calibration → per-query-class weights replace asserted ones.
2. **Sufficiency × confidence** logistic abstain gate calibrated (selective-accuracy gain vs confidence-alone demonstrated).
3. **≥25-trial debiased judge studies** (position/length controlled, no self-family) for every judge-based metric.
4. Graph edge/triple/minimal-subgraph metrics formalized.
5. Temporal-benchmark expansion; full 6-role benchmark program.
6. ARES / domain-trained judge path if precision demands it.

This is `LAYER1_TODO.md` H2 (**Stage A ≈ ship; Stage B = the research investment**). The provisional params in the other docs are *specified* here and *calibrated* in Stage B; Stage A ships on deterministic gates + fixed defaults + sampled audits — the eval program never blocks the beta.

---

## §8 — Citations (full reference list)

Every source referenced above, with depth tag and what it grounds. `[paper-walked]` = results table read; `[verified-from-docs]` = official doc read; `[abstract+search]` / `[abstract-only]` = arxiv abstract / secondary; `[claimed]` = secondary/blog. Author + venue fields included only where the research agents reported them (no fabrication). arxiv links resolve at `https://arxiv.org/abs/<id>`.

### A. The thesis — sufficiency + retrieval↔answer coupling
1. `[paper-walked]` **arxiv 2411.06037** — *Sufficient Context: A New Lens on Retrieval Augmented Generation Systems* — Joren, Zhang, Ferng, Juan, Taly, Rashtchian (Google) — ICLR 2025. (Blog: research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/) → §0 finding 2; dim 3 sufficiency autorater (93%); dim 10 abstain = sufficiency×confidence.
2. `[paper-walked]` **arxiv 2404.13781** — *eRAG: Evaluating Retrieval Quality in Retrieval-Augmented Generation* — Salemi, Zamani (UMass Amherst) — SIGIR 2024. → §0 finding 1 (relevance ≠ answer quality, τ 0.505 vs 0.179 vs 0.049); §2 source-weight calibration protocol.
3. `[paper-walked]` **arxiv 2510.21440** — *Redefining Retrieval Evaluation in the Era of LLMs* (UDCG) — 2025. → §0 (distractors = negative utility, +36% ρ vs nDCG); dim 1/2.
4. `[paper-walked]` **arxiv 2601.14546** — *Predicting Retrieval Utility and Answer Quality in RAG* — Tian, Ganguly, Macdonald (Univ Glasgow) — Jan 2026. → dim 10 / drift-τ (context-perplexity PerpC as cheap pre-filter).

### B. RAG eval metrics + frameworks
5. `[paper-walked]` **arxiv 2309.15217** — *RAGAS: Automated Evaluation of Retrieval Augmented Generation* — Es, James, Espinosa-Anke, Schockaert (Exploding Gradients / Cardiff Univ) — EACL 2024 (demo). → dim 4 faithfulness formula (0.95 vs human); origin of the context-precision/recall/faithfulness suite.
6. `[verified-from-docs]` **RAGAS v0.4 docs** — docs.ragas.io → dim 11 metric formulas; TestsetGen golden-set spec (§4).
7. `[verified-from-docs]` **arxiv 2311.09476** — *ARES: An Automated Evaluation Framework for RAG Systems* — (Stanford FutureData). → §3 high-stakes judge (DeBERTa + PPI CIs; +59.9pp context-relevance vs RAGAS).
8. `[verified-from-docs]` **TruLens — RAG Triad** — trulens.org/getting_started/core_concepts/rag_triad/ → §3 OTel-native triad (context-relevance / groundedness / answer-relevance).
9. `[verified-from-docs]` **DeepEval (Confident AI)** — deepeval.com/docs → §3 contextual precision/recall + G-Eval + DAG metric (isolation namespace checks).
10. `[verified-from-docs]` **Arize Phoenix** — RAG relevancy / hallucination eval templates → §3 post-span batch eval.
11. `[verified-from-docs]` **Langfuse evals** — langfuse.com/docs/evaluation → §3 the online seam (`@observe()` + `as_type='retriever'` spans; async eval queue; cannot block generation).
12. `[verified-from-docs]` **Relari continuous-eval** — continuous-eval.docs.relari.ai → §3 deterministic (precision/recall/nDCG, no LLM) + LLM metrics.
13. `[verified-from-docs]` **RAGChecker** — github.com/amazon-science/RAGChecker (Amazon Science) → §3 + drift-τ: the only tool separating relevant- vs irrelevant-noise-sensitivity. *(arxiv id not captured by the research pass.)*
14. `[paper-walked]` **arxiv 2510.09738** — *Judge's Verdict* (54-LLM judge benchmark) — Oct 2025. → §0 / dim 11 judge ceiling (best LLM κ=0.813 vs human-human 0.801).

### C. Faithfulness / groundedness / attribution
15. `[paper-walked]` **arxiv 2305.14627** — *ALCE: Enabling Large Language Models to Generate Text with Citations* — Gao, Yen, Yu, Chen (Princeton) — EMNLP 2023. → dim 4 attribution via NLI (citation recall/precision; also dim 8 isolation instrument).
16. `[paper-walked]` **arxiv 2402.15089** — *AttributionBench: How Hard is Automatic Attribution Evaluation?* — Li et al. (OSU-NLP) — ACL 2024 Findings. → §0 finding 3 (faithfulness gate ~80% F1 ceiling, worst on numbers/dates/names).
17. `[abstract+search]` **arxiv 2305.14251** — *FActScore* — Min et al. (UW / Allen AI / Meta) — EMNLP 2023. → dim 4 atomic-fact granularity (estimator <2% error).
18. `[abstract+search]` **arxiv 2401.00396** — *RAGTruth: A Hallucination Corpus for Trustworthy RAG* — Niu et al. (Tencent / Northeastern) — ACL 2024. → dim 4 cheap fine-tuned span-level detector (18k annotated).

### D. LLM-as-judge reliability (the debiasing mandate)
19. `[paper-walked]` **arxiv 2506.06331** — *How Significant Are the Real Performance Gains? An Unbiased Evaluation Framework for GraphRAG* — 2025. **★ governs every judge gate.** → §0 mandate (position/length/trial bias; LightRAG-vs-NaiveRAG 66.70→39.06).
20. `[paper-walked]` **arxiv 2306.05685** — *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* — Zheng et al. (LMSYS / UC Berkeley) — NeurIPS 2023. → §0 (35% verdict flip on order swap; verbosity attack; self-enhancement).
21. `[paper-walked]` **arxiv 2303.16634** — *G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment* — Liu et al. (Microsoft) — EMNLP 2023. → §0 (self-preference: judge over-scores own family; SummEval ρ 0.514).
22. `[abstract+search]` **arxiv 2305.17926** — *Large Language Models are not Fair Evaluators* — Wang et al. (Peking Univ) — ACL 2024. → §0 (position-bias flips 66/80; MEC + BPC fix = average both orders).

### E. Nugget / answer-completeness
23. `[paper-walked]` **arxiv 2504.15068** — *The Great Nugget Recall: AutoNuggetizer* — Pradeep, Thakur, …, Lin (Univ Waterloo) — SIGIR 2025. (Companion: **arxiv 2411.09607**, TREC 2024 RAG initial report.) → dim 11 nugget recall (run-level τ 0.887 aggregate-only; per-topic τ ~0.49 noisy).

### F. Inference-time / online gating
24. `[paper-walked]` **arxiv 2310.11511** — *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection* — Asai, Wu, Wang, Sil, Hajishirzi (UW / Allen AI / IBM) — ICLR 2024. → dim 9 inline gate map (ISREL→ISSUP→ISUSE).
25. `[paper-walked]` **arxiv 2401.15884** — *Corrective Retrieval Augmented Generation (CRAG)* — Yan, Gu, Zhu, Ling (USTC / Google) — 2024. → dim 9/10 retrieval-evaluator 2-threshold {correct/incorrect/ambiguous}; the escalation template.
26. `[paper-walked]` **arxiv 2403.14403** — *Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity* — Jeong et al. (KAIST) — NAACL 2024. → §2 T-cap (steps 2.17 vs 4.69; router only 0.31–0.66 accurate → T≈3 hard ceiling).
27. `[paper-walked]` **arxiv 2305.06983** — *FLARE: Active Retrieval Augmented Generation* — Jiang, Xu, Gao, …, Callan, Neubig (CMU) — EMNLP 2023. → drift-τ (token-prob trigger θ=0.8, mask β=0.4).
28. `[claimed]` **arxiv 2510.05310** — RAG context can override response-level guardrails → §3 note (need context-aware guardrails).

### G. Graph-native retrieval + benchmarks
29. `[paper-walked]` **arxiv 2404.16130** — *From Local to Global: A Graph RAG Approach to Query-Focused Summarization* (Microsoft GraphRAG) — Edge, Trinh, et al. (Microsoft Research) — 2024. (Repo: github.com/microsoft/graphrag.) → dim 2 (4-metric win-rate; comprehensiveness/diversity ~72–82% vs vector, but vector wins **directness**).
30. `[abstract-only / blog]` **LazyGraphRAG** — Microsoft Research blog, 2024-11-25 (BenchmarkQED). → §2 T-cap (budget-scaling; vendor cost claims).
31. `[paper-walked]` **arxiv 2506.02404** — *GraphRAG-Bench* (+ companion **arxiv 2506.05690**, *When to use Graphs in RAG*) — DEEP-PolyU — ICLR 2026. (Repo: github.com/GraphRAG-Bench/GraphRAG-Benchmark.) → dim 2 when-to-fuse (graph hurts on MC/math/fill-in-blank; +1–2pt overall); R/AR score ≈ blast-radius.
32. `[paper-walked]` **arxiv 2405.14831** — *HippoRAG* — (OSU-NLP) — NeurIPS 2024. → dim 1 (Recall@5 2Wiki +32pt; loses HotpotQA QA-F1 — query-conditional weights).
33. `[paper-walked]` **arxiv 2502.14802** — *HippoRAG 2: From RAG to Memory* — (OSU-NLP) — 2025. → §2 realistic fusion expectation (+2.8 F1 avg vs strong dense, concentrated in bridge-multi-hop).
34. `[paper-walked]` **arxiv 2410.05779** — *LightRAG* — (HKUDS) — EMNLP 2025. → dim 2 (win-rates — but see #19 debiasing inversion).

### H. Multi-hop QA + graph-retrieval metrics
35. `[abstract-only]` **arxiv 1809.09600** — *HotpotQA* — answer + supporting-fact EM/F1 (distractor setting). → dim 1 two-level scoring.
36. `[abstract-only]` **arxiv 2011.01060** — *2WikiMultiHopQA* — answer EM/F1 + evidence-triple F1. → dim 1 bridge-entity-path retrieval correctness.
37. `[abstract-only]` **arxiv 2108.00573** — *MuSiQue* — shortcut-resistant 2–4 hop. → dim 1.
38. `[abstract-only]` **arxiv 2401.15391** — *MultiHop-RAG* — Tang & Yang — COLM 2024 — Hits@K/MAP@K/MRR@K + null-query (abstention). → dim 1/8/10. *(retrieval Hits@K table not opened.)*
39. `[abstract-only]` **arxiv 2603.07179** — minimal-sufficient-subgraph (smallest subgraph that still answers). → dim 6 surgical blast-radius metric.
40. `[abstract-only]` **RRF** — *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods* — Cormack, Clarke, Büttcher (Univ Waterloo) — SIGIR 2009. → dim 2 fusion mechanism (1/(k+rank), k=60).
41. `[paper-walked]` **arxiv 2104.08663** — *BEIR* — Thakur, Reimers et al. — NeurIPS 2021 (D&B). → dim 1 / §2 (dense −2.8→−47.7% vs BM25 zero-shot; BM25+CE rerank +11% → vector = recall-only).

### I. Temporal / memory
42. `[paper-walked]` **arxiv 2501.13956** — *Zep: A Temporal Knowledge Graph Architecture for Agent Memory* (engine = Graphiti, bi-temporal) — getzep — 2025. → dim 5/7 (DMR 94.8%; LongMemEval +18.5%). **⚠ uses LongMemEval, NOT LOCOMO — "84% LOCOMO" is a contested blog claim, see §6.**
43. `[paper-walked]` **arxiv 2402.17753** — *LOCOMO* — Maharana et al. (Snap Research) — 2024. → dim 5 (temporal worst at 20.3 F1; adversarial 2.1 = abstention stress).
44. `[abstract-only]` **arxiv 2410.10813** — *LongMemEval* — Wu et al. — ICLR 2025. → dim 6/7/10 (knowledge-update + temporal + abstention categories; the memory-store benchmark to adopt).
45. `[abstract-only]` **arxiv 2106.15110** — *TempLAMA* — Dhingra et al. — TACL 2022 — cloze-by-year. → dim 5 the as-of correctness template.
46. `[abstract-only]` **arxiv 2106.01515** — *CronQuestions* — Saxena et al. — ACL 2021 — temporal-KGQA, Hits@1/10. → dim 5 scaling temporal-reasoning complexity.
47. `[abstract-only]` **TimeQA** — Chen et al. — NeurIPS 2021 — time-scoped QA (~66% consistency under perturbation). → dim 5 robustness probe.
48. `[abstract-only]` **arxiv 2406.09170** — *Test of Time* — synthetic temporal reasoning. → dim 5.
49. `[abstract-only]` **arxiv 2509.16720** — EM-critique for temporal QA (use graded temporal distance, not binary EM). → dim 6 freshness scoring.

### J. Conflict / contradiction
50. `[abstract-only]` **arxiv 2408.12076** — *ConflictBank* — 2024 — context-memory + inter-context conflicts. → dim 7.
51. `[abstract-only]` **arxiv 2406.13805** — *WikiContradict* — NeurIPS 2024 (D&B) — 253 human-annotated real contradictions (LLMs poor at detection). → dim 7.
52. `[abstract-only]` **arxiv 2403.08319** — Knowledge-Conflicts survey (incl. *DynamicQA*) — EMNLP 2024 — LLMs fail to overwrite parametric knowledge under conflict. → dim 7 (⟹ resolve structurally in store).
53. `[abstract-only]` **arxiv 2603.15892** — Temporal Fact Conflicts (DynamicQA+MULAN) — temporal supersession. → dim 5/7.
54. `[abstract-only]` **arxiv 2601.15495** — multi-step conflict propagation. → dim 7.

### K. Secondary / [claimed]
55. `[claimed]` **ATLAN** — *LLM Evaluation Frameworks Compared* — atlan.com/know/llm-evaluation-frameworks-compared/ → §3 (single secondary source, illustrative only — the consistency≠truth point stands on its own logic; the "fools all frameworks" specifics are citation-fragile, do not load-bear).

**Local full-text extracts** (for re-checking exact cells): `/tmp/{suffctx,erag,adaptiverag,alce,predutil}.txt`.

**Re-verify-before-load-bearing** (not personally table-walked): #17 FActScore, #18 RAGTruth, #22 Wang, #28 guardrails, #30 LazyGraphRAG, #35–40 multi-hop retrieval tables + RRF TREC tables, #44–54 temporal/conflict result tables.
