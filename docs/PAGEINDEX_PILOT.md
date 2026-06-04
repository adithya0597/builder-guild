# PAGEINDEX_PILOT.md — adopt-and-measure spec

Date: 2026-06-01. Goal: **decide whether PageIndex earns a place on the retrieval ladder by measuring it, not trusting the vendor's 98.7%.** Its mechanism is sound (vectorless reasoning-tree); its headline benchmark is self-scored and *exceeds the FinanceBench oracle* (see `EVIDENCE_LOG.md`) — so we pilot on OUR corpus before committing. All install/format facts below are repo-grounded (github.com/VectifyAI/PageIndex, read 2026-06-01).

## What PageIndex is (confirmed)
Builds a hierarchical **table-of-contents tree** over a long doc; an LLM **reasons over the tree** to pick relevant sections (no embeddings, no chunking). Node = `{title, node_id, start_index, end_index, summary, nodes[]}`. Retrieval returns **selected node_ids + titles + page/line refs** → directly scorable.

## How to run it (self-host, $0 infra)
```bash
git clone https://github.com/VectifyAI/PageIndex && cd PageIndex
pip3 install -r requirements.txt      # litellm, pymupdf, PyPDF2, python-dotenv, pyyaml
echo "OPENAI_API_KEY=sk-..." > .env    # LiteLLM → can point at Anthropic/local instead
```
- **NOTE:** `pip install pageindex` is the *cloud SDK* (hosted API, needs a Vectify key) — NOT what we want. Self-host = run from the cloned repo.
- **Phase 1 — BUILD tree:** `python3 run_pageindex.py --md_path doc.md` (markdown natively supported — `--md_path` parses `#/##/###` into tree levels). Build LLM = `gpt-4o-2024-11-20` default, **swappable via LiteLLM** (`config.yaml` → e.g. `anthropic/claude-sonnet-4-6` or a local model to cut cost). Cost ≈ **O(#sections)** LLM calls (TOC detect + per-large-node parse + one summary/node).
- **Phase 2 — RETRIEVE:** agentic tree-search (default `retrieve_model: gpt-5.4`) — the agent loops over 3 tools (`get_document_structure` → pick node page-ranges → `get_page_content`). Simple notebook variant = fixed **2 calls** (tree-search → answer); agent variant = 3-5 tool-turns.

## Input-format verdict (matches our corpus)
- ✅ **Native markdown** — our docs are markdown-shaped, no conversion. Caveat (maintainers): markdown *auto-converted from PDF/HTML* has broken heading hierarchy → use their OCR; our docs are *native* md, so this doesn't bite.
- ⚠️ **Code files** — no language-aware parser; the md parser *skips fenced code blocks*. Treat code as text or wrap in fences. (Code retrieval is better served by the graph-index / AST-chunk path anyway — PageIndex is for long prose docs.)
- ❌ Plain `.txt`/`.html` not directly supported (raises ValueError) — convert to md.
- **Fit:** pilot it on our **long markdown design/architecture docs** (the natural PageIndex use case), NOT on code.

## Pilot eval design (minimal, runnable; mirrors FinanceBench methodology)
1. **Corpus:** 1 representative long markdown doc, target **>50 sections** so tree-search matters (e.g. a concatenated architecture/runbook doc, or a merged design doc-set).
2. **Q&A set:** hand-write **15-20 pairs**, each tagged with the **gold section/heading** holding the answer. Mix: **8 single-section** lookups · **7 multi-section/synthesis** · **5 negative** ("not in doc" — must abstain).
3. **Arms:**
   - **A = PageIndex** — `index(doc.md)` → agentic query; record selected `node_id`s + answer.
   - **B = Vector baseline** — chunk same doc (512-token), embed **EmbeddingGemma-300M local ($0)**, top-k=5; same answer-LLM.
4. **Metrics** (per query-class):
   - **Retrieval hit-rate / recall@k** — did the returned section(s) contain the gold heading? (PageIndex node→title; vector chunk→heading.)
   - **Answer correctness** — % correct vs gold (LLM-judge + human spot-check on disagreements).
   - **Faithfulness** — answer claims grounded in returned context (LLM-judge 1-5).
   - **Negative handling** — does it abstain on the 5 not-in-doc Qs?
5. **Pass criterion:** PageIndex retrieval hit-rate **≥ baseline +10 pts** AND answer-correctness ≥ baseline, **on the multi-section questions specifically** (where reasoning-retrieval should win; if it only ties on single-section lookups, the graph-index/vector path already covers those cheaper).
6. **Measure (unpublished, get real numbers):** per-doc build cost, per-query retrieval cost + latency. The vendor publishes none — this pilot produces them.

## What we need
- An **LLM API key** (OpenAI default; or LiteLLM → Anthropic/local for the build phase to cut cost). **No PageIndex cloud key** needed for self-host.
- EmbeddingGemma-300M local for the baseline arm ($0).
- ~1 long md doc + 15-20 hand-written Q&A (the only manual effort).

## Cost at scale — do NOT run PageIndex over a whole projects folder
Measured on a large projects tree (excluding node_modules/.venv/.git/site-packages/dist/build): **18,035 markdown files · 493 MB · 446,332 heading lines (≈sections)** + 22,089 code files (113,300 files total). PageIndex builds **one tree per doc**, so "over the folder" = 18,035 separate tree-builds.

**Computed build cost (LABELED-ESTIMATE; inputs: 493 MB → ÷4 ≈ 123M tokens; build reads the corpus ~1.3× for TOC+per-node summary; output ≈ #nodes × ~200 tok):**
- **input** ≈ 123M × 1.3 (TOC + per-node summary read overhead — a rough fudge, validate in pilot) ≈ **160M tokens** → 160M × $2.5 = **$400**.
- **output** = #nodes × ~200 tok. #nodes is bounded **below** by token-budget grouping (123M ÷ 20k/node ≈ **6K nodes**) and **above** by the measured **446K headings** (if every heading becomes a node). So output spans **6K×200=1.2M tok (~$12)** → **446K×200=89M tok (~$890)**.
- **total @ gpt-4o ≈ $410 (coarse grouping) → $1,290 (per-heading)** — the spread is entirely node-granularity (the earlier "50–100K nodes" was inconsistent with the 446K measurement; corrected). @ Haiku ≈ half; local ≈ $0-marginal. All LABELED-ESTIMATE — the 1.3× overhead and node-count are unverified assumptions; the pilot produces the real per-doc number.
- @ Haiku 4.5 ($1/$5) ≈ **~$235**; @ local model via LiteLLM ≈ **$0 marginal but slow**.
- **Latency is the real wall:** tens-of-thousands → ~446K LLM calls = **hours to days**, not minutes.

**Verdict: never run it over the whole folder — it's expensive AND wrong.** The 18K md are mostly *vendored* library/framework docs (langchain-course, swarms, dependency docs), not your knowledge. Scope to **your authored long docs** (design docs, internal notes, project READMEs — hundreds, not 18K) → cost drops ~100×. And with surgical updates (HYBRID PART 3-C): a doc's tree is built **once** and rebuilt **only when that doc changes** (blast radius = 1 doc), so ongoing cost ≈ per-edit, not per-folder. The pilot above runs on **1** doc — that's the right unit.

## Decision rule (what the pilot outputs)
- **Pass** → PageIndex becomes method 3 on the ladder for long-doc nodes (`chunk_count` high / `long_context` is a structured doc). Wire it to fire only on that node class.
- **Fail / ties** → drop it; node-vector + chunk-vector + rerank cover the need at lower cost. Record the measured numbers either way in `EVIDENCE_LOG.md`.

## How this connects to the graph KB (what we're really testing)
PageIndex is the **deep in-doc reader, scoped by the graph** — method 3 on the retrieval ladder, NOT a standalone RAG. At runtime: graph/vector locate a node → if it's a long-doc node and the query needs in-doc reasoning, drill via that node's PageIndex tree. The seam (see HYBRID PART 2 "How PageIndex connects to the graph"): a long-doc node carries `pageindex_ref` + `tree_built_at`; the tree is built over the node's **full source doc** (`chunks[]`/source file), distinct from `long_context` (the fact-free abstract that feeds the vector). Returned sections → evidence schema (`source_path`/`chunk_span`) → trace to `:Episodic`; validity/freshness flags propagate from the node. **This pilot tests that exact method-3 component in isolation** — pass → it plugs into long-doc nodes; tie/lose → chunk-vector covers them and the graph spine is unchanged.

## Dependencies
- Runs **before** the full KB build (standalone, on a sample doc) — does NOT need Neo4j or the ontology in place. This is the cheapest way to de-risk the Case-3 ladder's top rung. Decoupled by design: the graph spine (Layer 1) does not depend on the pilot's outcome.
