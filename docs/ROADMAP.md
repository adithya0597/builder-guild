# Roadmap — in capability terms

Ordered by what the last calibration run proved is missing (see
`03-evals/CASE_STUDY_calibration.md`). Each item states its acceptance test.

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

> Provenance: distilled from `company-brain/research/RAG_PATTERNS_AND_PAPERS_FOR_BUILDER_GUILD.md`
> (Part B verified-from-source, 2026-06-13). All six fetched from canonical URLs after an earlier
> title-card-only pass was caught and corrected (see that doc's Part F).
