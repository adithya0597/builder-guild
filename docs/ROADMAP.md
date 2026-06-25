# Roadmap — in capability terms

Ordered by what the last calibration run proved is missing (see
`03-evals/CASE_STUDY_calibration.md`). Each item states its acceptance test.

## Status (2026-06-14)

RAG-pattern coverage (see `01-context/RETRIEVAL.md` + `HYBRID_RETRIEVAL_ARCHITECTURE.md`):
- **Hybrid RAG** — ✅ shipped (keyword + graph + vector ladder, RRF fusion).
- **GraphRAG** — ✅ shipped; communities exist as a standalone module, NOT wired into the live serve() path (`01-context/src/communities.py`, per-namespace Leiden, isolation-proven).
- **Corrective RAG** — ✅ shipped; corrective_serve() exists but is NOT the default serve() path (it wraps serve()) (`01-context/src/corrective.py`, bounded rewrite→re-retrieve + $0-or-STOP web fallback).
- **Agentic RAG** — ◐ PARTIAL (mechanism only) → gap **G1** below.
- **Multimodal RAG** — ✗ NOT built (text-only) → gap **G2** below.

**Gate state: suggest-only.** `01-context/src/abstain.py` has `CALIBRATED=False` with provisional
weights, so every decision routes to a human — autonomy is not leased. The calibration run recorded
in `03-evals/CASE_STUDY_calibration.md` (N=10 human-validated golden, 6-namespace graph, external $0
judge) measured a **+10.0pp selective gain** over confidence-alone (stable across three fits) yet
**refused to certify** — because the sufficiency proxy refit with a **negative weight** (anti-correlated,
−3.167 → −4.089: the selective gain came from confidence alone), the serving layer was only 40% correct
on its own golden before the fixes (80% after), and **judge κ was unmeasurable** (8/10 items scored
deterministically — N=10 is a smoke test). The gate correctly refuses on a broken sufficiency signal →
trust track **G3** below.

## Near

1. **Temporal-evidence layer.** `valid_from`/`valid_to` event history + an as-of query path, so
   "who owned X on <date>" is answered from evidence or abstained — never from current state.
   *Accept:* the temporal golden item flips from abstain-expected to pass-with-evidence and a
   planted supersession chain answers correctly at three time points.
2. **Real sufficiency signal.** Replace the facts-count proxy (which fitted with a *negative*
   weight) with a coverage-vs-question signal (Sufficient-Context-style autorater or deterministic
   support-fact coverage). *Accept:* refit yields a positive sufficiency weight and selective gain
   holds.
3. **Decision-channel scoring** for abstain items in the golden scorer (text-matching "abstain" is
   a category error). *Accept:* judge easy-agreement artifact disappears.

## Mid

4. **Golden set v1 — measurable judge trust.** ≥30 judgment-requiring items, balanced
   pass/abstain prevalence, across all six role namespaces. *Accept:* judge-human κ is computable
   with a confidence interval; κ ≥ 0.8 with CI excluding 0.6 becomes a meaningful bar.
5. **Per-namespace autonomy lease.** `CALIBRATED` becomes a per-role, reversible flag; any sweep
   whose κ/gain drops below bar auto-reverts that namespace to suggest-only. *Accept:* a forced
   bad sweep revokes exactly one namespace and the regression stays green.
6. **Weighted fusion + reranker.** Replace tie-break-by-order with eRAG-weighted RRF; add a
   cross-encoder rerank stage (BM25/keyword + CE rerank is the strongest published baseline).
   *Accept:* fusion ablation per query class beats unweighted RRF on the golden set.

## Later

7. **Silence/coverage monitoring.** Absence as signal: a namespace that stops producing facts is
   an alert, not a blank. (A monitoring eval, distinct from the QA golden set.)
8. **Fleet orchestration** on the patterns in `02-agents/COORDINATION_PATTERNS.md`, with the
   action-audit loop attributing outcomes per acting agent.
9. **Long-doc navigation rung** (ToC-guided section retrieval) behind the eval gate, scoped by
   the graph — pilot design in `01-context/PAGEINDEX_PILOT.md`.

## Gaps to close next — fresh-session entry points

The three named gaps from the 2026-06-14 status review, written so a cold session can pick one up.
Each says where to start. G3 is the existing items 2→5 in dependency order (framed, not duplicated).

### G1 — Agentic RAG: the autonomous planner-loop (mechanism shipped, policy deferred)
Today the retrieve-decision is bounded + mechanical: rung escalation (`ladder.py`) + the corrective
rewrite loop (`corrective.py`). The Agentic-RAG pattern is a *planner* that decides **what** to
retrieve, **when**, and **from where**, looping until confident — the policy was deliberately
deferred (mechanism exists, autonomy of the loop does not). Distinct from item 8 (fleet/multi-agent
coordination); G1 is one agent choosing its own retrieval strategy.
*Start:* `02-agents/AGENT_ARCHITECTURE.md` §5 (`demo_agent`) + `01-context/src/corrective.py`.
*Accept:* a planner answers a multi-step question by issuing ≥2 distinct retrievals it chose itself
(not the fixed ladder), terminates on a confidence/abstain signal (bounded — no unbounded loop),
and the trace shows each decision point. Stays $0/local + namespace-scoped (isolation self-check clean).

### G2 — Multimodal RAG (OCR-first, NOT vision-default)
Not built; text-only. When built, default to an **OCR pipeline (or hybrid), NOT ColPali/vision** —
`arXiv:2505.05666` found OCR beats ColPali in *all* evaluated settings (L0 MRR .5151 vs .2971);
vision wins only when fine-tuned on target data, and CLIP/ColPali would break the $0/local simplicity.
*Start:* a pluggable OCR adapter (env-generic, mirrors `03-evals/src/judge_adapter.py`) that feeds
text into the existing ladder; keep it behind the eval gate.
*Accept:* a PDF-with-diagram doc is indexed via OCR and retrieved through the existing
namespace-scoped ladder; an A/B vs a vision baseline is *measured* (not assumed); $0/local default holds.

### G3 — Calibration / autonomy: the trust track (BLOCKS the autonomy lease)
The gate is suggest-only because the last run FAILED its coverage gate and the sufficiency proxy
fitted with a **negative** weight (a broken signal). This is items **2 → 3 → 4 → 5** in dependency
order: (2) a *real* sufficiency signal → (3) decision-channel golden scoring → (4) golden-set v1 for
a *measurable* κ → (5) the reversible per-namespace autonomy lease. Until 2–4 land, `CALIBRATED`
stays False **by design** (refusing to certify is a success mode, not a bug).
*Start:* re-run the sweep for a *current* reading (`03-evals/src/cal3_fit.py` + `cal4_sweep.py`),
then `03-evals/CASE_STUDY_calibration.md`.
*Accept:* sufficiency refits **positive** with a selective-accuracy gain over the confidence-only
baseline; κ ≥ 0.8 with a CI excluding 0.6 on golden v1; then exactly one namespace flips to
autonomous via the reversible lease (item 5) and the regression stays green.

**Autonomy boundary (by design):** when a namespace is leased, autonomous action is restricted to
*edge-validated* answers (a presentable graph edge whose relation matches the query's intent);
correctly-answered-but-text-only facts (status is the canonical case) stay suggest-only — correctness
is necessary but not sufficient for action. See `03-evals/CASE_STUDY_calibration.md`.

Non-goals: prompt-time conflict resolution (conflicts resolve structurally in the store);
relevance-tuned retrieval (sources are weighted by downstream utility, not similarity); any
autonomy flip without a human reading the evidence packet.

## Research grounding (citations) — to wire into the layer docs

To-do (doc-only, not a capability — no code): wire each evidence citation into the layer doc whose
otherwise-arbitrary-looking limit it justifies, and add a references block. Turns design constants
from "hobby-grade" into "evidence-backed." *Accept:* every cited limit in `01-context` / `02-agents`
/ `03-evals` links to its paper, and the references below resolve.

**Active citations (cite into the docs):**
- **Context Rot: How Increasing Input Tokens Impacts LLM Performance** — Hong, Troynikov, Huber
  (Chroma technical report, 2025-07-14). <https://www.trychroma.com/research/context-rot>
  → `01-context`: justifies the `ctx[:200]` / top-K caps. LLMs do not process long context uniformly;
  the 10,000th token is not handled as reliably as the 100th.
- **Defeating Nondeterminism in LLM Inference** — Horace He et al., Thinking Machines Lab
  (blog, 2025-09-10; *not peer-reviewed*). <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>
  → `03-evals`: justifies ≥25-trial averaging + content-hash checkpoints + κ. Batch-invariance: 1000
  identical prompts → **80 unique completions** without batch-invariant kernels; **1000/1000 identical**
  with them.
- **When "A Helpful Assistant" Is Not Really Helpful: Personas in System Prompts Do Not Improve
  Performance** — Zheng, Pei, Logeswaran, Lee, Jurgens (Findings of EMNLP 2024).
  <https://aclanthology.org/2024.findings-emnlp.888/>
  → `02-agents`: role = authorization scope, **not** a performance knob. Personas don't reliably
  improve factual accuracy; automatic persona-selection is "no better than random."

**Roadmap-only references (cited when the feature lands, not before):**
- **XGrammar** — Dong, Ruan, et al. (T. Chen), MLSys '25. <https://arxiv.org/abs/2411.15100>
  → constrained-decoding for a strict verdict schema `{match, confidence, reason}`; "up to 100x" vs
  other *constrained-decoding* engines (NOT vs unconstrained).
- **DoRA: Weight-Decomposed Low-Rank Adaptation** — Liu et al. (NVIDIA), ICML '24.
  <https://arxiv.org/abs/2402.09353> → train-your-own-judge PEFT method; +3–4% over LoRA on
  commonsense + visual tasks ONLY — transfer to judging is **undemonstrated**; premature at n=33 goldens.
- **Lost in OCR Translation? Vision-Based Approaches to Robust Document Retrieval** — Most et al.
  (Los Alamos). <https://arxiv.org/abs/2505.05666> → corrects the multimodal default: OCR beats
  ColPali in all evaluated settings (L0 MRR .5151 vs .2971); go OCR/hybrid, **not** vision-default.

> Provenance: distilled from internal research notes.
> (Part B verified-from-source, 2026-06-13). All six fetched from canonical URLs after an earlier
> title-card-only pass was caught and corrected (see that doc's Part F).
