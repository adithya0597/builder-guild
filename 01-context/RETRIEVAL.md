# RETRIEVAL.md — retrieval decision card

Companion to `MODEL_ROUTING.md`. That card covers **context-management** (RCR-Router) and **information-exchange** (the 3 couplings). This one fills the thin third bucket: **retrieval** — how an agent finds the right facts before it reasons. Grounded 2026-06-01 from 4 parallel research streams (arxiv abstracts + vendor reports + leaderboards). Depth is **abstract/leaderboard-level**, not full-paper-walked, unless a bullet says otherwise.

## The one principle

> Retrieval quality is set by the **pipeline shape**, not the embedder. The biggest, repeatable wins come from (1) a reranker on top of first-stage recall, (2) contextualizing chunks before embedding, and (3) routing reasoning-heavy queries to query-planning, not raw cosine.

A SOTA embedder buys a few points; a cross-encoder reranker buys ~+11% and contextual chunking cuts failure ~49–67%. Spend effort on the pipeline, not the model leaderboard.

## The grounded map — what actually moves the number

| Lever | Effect (grounded) | Source |
|---|---|---|
| **Cross-encoder rerank** on BM25 top-k | **+11% avg nDCG@10** vs BM25, wins 16/18 BEIR datasets | BEIR [2104.08663](https://arxiv.org/abs/2104.08663), Table 2 [paper-walked] |
| **Contextual chunking** (prefix each chunk w/ doc context before embed) | top-20 retrieval **failure −49%** (5.7→2.9%); **+rerank → −67%** (5.7→1.9%) | Anthropic [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) [vendor-confirmed] |
| **Corrective RAG** (retrieval evaluator + re-search on low confidence) | over standard RAG (SelfRAG-LLaMA2-7b): **PopQA +19.0%** (40.3→59.3), **Bio +14.9 FactScore**, **PubHealth +36.6%** | CRAG [2401.15884](https://arxiv.org/abs/2401.15884) **[paper-walked; my earlier "+7.0% PopQA" was WRONG — real +19.0%]** |
| **Self-reflective RAG** (decide *when* to retrieve, self-critique) | PopQA **55.8%** (13B) vs 14.7% base Llama2-13B | Self-RAG [2310.11511](https://arxiv.org/abs/2310.11511) **[paper-walked]** (beats retrieval-Llama2 on all tasks; loses to ChatGPT on ARC-Challenge + ASQA-str-em — not a uniform win) |
| **Query planning / CoT before retrieval** | lifts BM25 on reasoning-retrieval **14.5 → 27.0** nDCG@10 (+12.2, GPT-4 CoT best case) | BRIGHT [2407.12883](https://arxiv.org/abs/2407.12883) **[paper-walked; my earlier "14.8→26.5" was WRONG]** (needs a strong LLM writing CoT queries per request; even SOTA stays <30 — reasoning-retrieval is unsolved) |
| **Late-interaction (ColBERTv2)** | wins 22/28 out-of-domain; **6–10× smaller** index via residual compression | [2112.01488](https://arxiv.org/abs/2112.01488) [paper-walked] |

## RAG vs long-context — when to even retrieve

- **Long-context wins on quality when resourced** (GPT-4o/Gemini-1.5-Pro); LC ≡ RAG on >60% of queries — RAG vs LC [2407.16833](https://arxiv.org/abs/2407.16833) [abstract].
- **But retrieve for cost**: the hybrid "Self-Route" (let model answer from RAG, fall back to LC only when it declines) **matches LC quality at −65% cost** (Gemini-1.5-Pro) / −39% (GPT-4o). Same source.
- **And retrieve when the corpus doesn't fit / changes / must be cited.** 1M-ctx is not free: single-needle recall >99.7% at 1M (Gemini-1.5, [2403.05530](https://arxiv.org/abs/2403.05530)) but **multi-needle collapses to ~60%**, and quality decays with length (context rot, [Chroma](https://www.trychroma.com/research/context-rot): NIAH −20–50% from 10k→100k+ across 18 models).
- **Context-length discipline in this stack (why the caps exist):** context rot is the grounding for the serve-side node-card truncating injected `long_context` to a fixed prefix (`serve.py`: `ctx['ctx'][:200]`) and presenting only the role's top-K cards rather than the whole subgraph — a shorter, position-stable context beats a longer one the model handles unevenly ([Chroma context-rot](https://www.trychroma.com/research/context-rot)).

> Rule for this stack: default to **plan-mode + agentic search** (the model greps/reads files itself) for known repos; reach for embedded retrieval only when the corpus is large, external, or must be cited. Add a reranker before adding a bigger embedder.

## Failure modes to design against

| Failure | Grounded magnitude | Source |
|---|---|---|
| **Lost in the middle** — mid-context facts ignored | accuracy ~75% (pos 1) → ~55% (middle of 20 docs); can fall *below* closed-book 56.1% | [2307.03172](https://arxiv.org/abs/2307.03172) [abstract] |
| **Semantic distractors** — related-but-wrong passages | worse than random noise; Llama2 acc → 0.17–0.37 w/ 18 distractors | Power of Noise [2401.14887](https://arxiv.org/abs/2401.14887) [abstract] |
| **Reasoning-intensive retrieval** — cosine can't reason | top MTEB embedder (59.0) scores **18.3** on BRIGHT | [2407.12883](https://arxiv.org/abs/2407.12883) [abstract] |
| **Split facts** — answer spans 2 chunks | "no embedder or reranker fully recovers it" | community-sentiment, unverified |

## Long-term agent memory (engram / claude-mem / mempalace)

The retrieval question for *memory across sessions*. Benchmark = **LOCOMO** ([2402.17753](https://arxiv.org/abs/2402.17753)): ~300-turn convs; raw LLMs score F1 13.9–32.1 (human 87.9) — i.e. **a memory layer is mandatory; long-context alone fails it.**

| System | Class | LOCOMO / metric | Source |
|---|---|---|---|
| Generative Agents | retrieval = recency×importance×relevance, top-k | the design every later system copies | [2304.03442](https://arxiv.org/abs/2304.03442) |
| **Mem0** (vector) | flat vector memory | J=66.9%; **−90% tokens, −91% p95 latency** vs full-ctx; +26% vs OpenAI memory | [2504.19413](https://arxiv.org/abs/2504.19413) |
| **Mem0g** (graph) | entity/relation graph | **J=68.44%** (best); +11% temporal, +7% multi-hop | same |
| **Zep / Graphiti** (temporal KG) | time-aware KG | DMR 94.8% (>MemGPT 93.4%); LongMemEval **+18.5%** acc, **−90% latency**, 1.6K vs 115K tokens | [2501.13956](https://arxiv.org/abs/2501.13956) |
| **A-MEM** (Zettelkasten) | self-linking notes | **≥2× multi-hop** vs baselines | [2502.12110](https://arxiv.org/abs/2502.12110) |

**Mapping to our stores** [all memory numbers paper-walked 2026-06-01]:
- **engram / claude-mem** = the **Mem0-base / A-MEM** class (flat vector). Strong + cheap on single-hop fact recall; weaker on temporal/relational chains.
- **mempalace** (knowledge-graph sqlite) = the **Mem0g / Zep-Graphiti** class. Payoff concentrates in **temporal (Zep +38.4% relative)** and **multi-hop (A-MEM up to 2.28× on GPT-4o; only ~1.8× on 4o-mini vs MemGPT)**.
- **⚠ Two verified caveats that change the mapping:** (1) **Graph LOSES to flat vector on simple recall** — Mem0g vs Mem0-base: single-hop 65.71 vs **67.13**, multi-hop 47.19 vs **51.15** (graph only wins Open-Domain + Temporal). So do NOT justify mempalace for single-hop/one-shot facts on these numbers — flat vector is as good or better. (2) **Metrics are NOT comparable across papers** — Mem0 "J=66.9%" is LLM-as-judge, LOCOMO-paper "F1 32.1" is F1, A-MEM "45.85" is also F1. Don't rank stores by mixing them; the −90% token / −91% latency wins are all **vs full-context, not vs flat-vector** (they don't show graph is cheaper than vector).

## Embedders in the stack

- **EmbeddingGemma-300M** (local, $0) — 308M params, 768-dim w/ Matryoshka truncation to 512/256/128; **1st among sub-500M** on MTEB-multilingual-v2, 8th overall ([2509.20354](https://arxiv.org/abs/2509.20354)). Right default for local/private retrieval.
- **gemini-embedding-001** (hosted) — Mean-task 68.32, retrieval 67.71 on MTEB-multilingual; #1 at release ([2503.07891](https://arxiv.org/abs/2503.07891)). Use when quality > privacy/cost.
- **nomic-embed-text-v1.5** — a common local default (512-dim Matryoshka). Fine; the leverage is rerank + contextual chunking, not swapping this.

## Evidence base + honesty

**Depth upgrade 2026-06-01:** a 6-agent panel read the actual results tables. **Confirmed (paper-walked):** BEIR rerank +11%/16-18; ColBERTv2 39.7 MRR / 22-28 OOD / 6-10× index; Anthropic −49%/−67%; Self-RAG 55.8; CRAG (corrected); RAG-vs-LC −65%/−39%; RouteLLM ~75%; Router-R1 0.409-0.416; RCR-Router −25-47%; Mem0/Zep/A-MEM/LOCOMO; GraphRAG; Lost-in-Middle; Power-of-Noise; Gemini-embed/EmbeddingGemma.
**Corrections found (were wrong at abstract-level):** CRAG PopQA +7.0% → **+19.0%**; BRIGHT CoT 14.8→26.5 → **14.5→27.0**; GraphRAG comprehensiveness "72/57/64" → **72-83%** + diversity **62-82%** (not 57/60); PageIndex vector baseline "30-50%" → **19% shared-store** (see below). RCR-Router T=3 = single measured point, not a swept optimum.
**Conditionals the levers carry:** rerank costs latency (BM25+CE ~450 ms GPU / 6100 ms CPU) and *loses* on out-of-distribution tasks (ArguAna, Touché) — "always rerank" needs a budget; contextual-chunking 49/67% is config-specific (Gemini embedder, 1−recall@20); Self-Route "cost" = input-tokens only (not wall-clock); **Power-of-Noise: random padding can *help* (+35%) while semantic hard-negatives *hurt* — so distractor-filtering must drop HIGH-similarity non-gold, not low-similarity random** (the naive "filter low-relevance" is backwards).
- MTEB v1 vs v2 not comparable. Community signal = sentiment, direction only.
- Companion: `MODEL_ROUTING.md`. Community raw: `~/Documents/Last30Days/rag-retrieval-failure-for-ai-agents-raw-v3.md`.

## Multimodal RAG — OCR-first (G2)

**Design choice: default to OCR-first for general document ingestion.**

Per Most et al., "Lost in OCR Translation? Vision-Based Approaches to Robust Document Retrieval",
arXiv 2505.05666 (2025): **OCR-based retrieval generalizes better to unseen / varying-quality
documents, while vision-native (ColPali) does well on in-domain / fine-tuned documents.** Because
a company brain ingests a wide, heterogeneous, mostly-unseen document mix (scans, exports, mixed
quality), the generalization edge points to **OCR-first as the default**; vision-native is the
specialized choice when you have fine-tuned on a known in-domain corpus.

This is reinforced by an engineering rationale independent of the paper: OCR-first is **$0/local**
(tesseract CLI, no model download) and **reuses the existing text ladder** — OCR text lands in
`long_context` and flows through embed → vector-rung → serve **unchanged**, so no new retrieval
machinery is introduced. The only new seam is the OCR ingestion path (`ocr_adapter.py` +
`etl.ingest_ocr_doc()`). Vision encoders (CLIP/ColPali) remain available as an optional baseline
but are NOT the default retrieval path.

**Implementation:** `01-context/src/ocr_adapter.py` (tesseract CLI, $0/local, env-at-call-time,
local-by-default with a $0-or-STOP regex backstop) + `etl.ingest_ocr_doc()` (additive, isolated
from the structured ETL path). Acceptance: `03-evals/src/eval_ocr.py` (T1-T4; T4 runs the real
serve() + cross-role isolation; the A/B is an honest smoke check, not a comparison).

Depth: **abstract-level** — paper read at title/abstract; the generalization-vs-in-domain claim is
the abstract-supported framing. **LABELED-ESTIMATE (abstract-level; full results table not walked):**
any specific per-benchmark MRR/nDCG margins are not cited here because the results tables were not
walked; treat the directional claim (OCR generalizes better; vision-native wins in-domain) as the
load-bearing one, and re-verify exact numbers against the paper before quoting them.

## Corrective RAG — bounded rewrite→re-retrieve loop (Corrective-RAG)

Implementation of CRAG [2401.15884] at the serve layer. When `abstain` is returned by the grader,
`corrective_serve()` (in `01-context/src/corrective.py`) rewrites the query deterministically
and re-retrieves, up to `max_rewrites` distinct probes. Pure Python, $0/local — no model calls.

**Loop shape:**

```
initial serve() → grade
  if pass/partial/escalate → return immediately (answer stands or human gate)
  if abstain:
    for tactic in [id_extract, pattern_synth, neighbor_expand, decompose]:
        if rewrites_used >= max_rewrites: break
        if probe already tried (no-op guard): skip
        candidate = serve(rewritten_query, role, pattern=new_pattern)
        assert trace.isolation.clean   # namespace isolation on every hop
        if candidate.decision != abstain: return candidate (resolved)
        rewrites_used += 1
    optional web fallback (OFF by default; $0-or-STOP on payment signal)
    return exhausted
```

**When to reach for it:** any query path where `decision == "abstain"` but the correct node
provably exists in the graph — weak/verbose user phrasings, prose-buried IDs, verb→relation
queries. Not a substitute for fixing the retrieval pipeline; use after the keyword/graph/vector
rungs are already tuned.

**Interface:**

```python
from corrective import corrective_serve

result = corrective_serve(
    query_text, role,
    pattern=None,       # optional structural {rel, obj}
    action=None,
    max_rewrites=2,     # hard bound on distinct probes
    web_fallback=False, # OFF by default; requires CORRECTIVE_WEB_ENABLED=true
)
# result is serve()'s dict plus result["corrective"]:
#   {attempted, resolved_at, rewrites_used, web_fallback}
```

See `03-evals/src/eval_corrective.py` for acceptance tests (6 tests including isolation,
bounded loop, $0-or-STOP web guard).
