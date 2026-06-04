# SYSTEM_COHERENCE.md — do the three layers compose, and where does the whole break?

Date: 2026-06-02. This validates the **whole system** — context **engineering** (build), context **management** (serve), and the **eval** layer — as one composed thing, not three docs. It answers: *how do they work together, what are the real drawbacks, and does the architecture make sense?*

**Method (honest):** I synthesized the integration narrative (I hold the full doc set), then spawned **two independent adversarial reviewers** (fresh context, different lenses — systems-integration + eval-epistemics, both Opus) to validate drawbacks without anchoring to my framing. Both grounded every finding in quoted doc text. Where they **converged** independently, confidence is highest. Companion visual: `diagrams/context-architecture.excalidraw` (4 zones + the offline/online split + loops + a validated-drawbacks callout).

---

## §1 — How the three layers compose (the integration narrative)

The system is a left-to-right pipeline with a cross-cutting eval band:

**BUILD → STORE → SERVE, with EVAL calibrating offline and enforcing online.**

1. **BUILD (engineering):** sources → ingest+provenance (`:Episodic`) → cosine-anchor to the tiered ontology (T0 CXO domains → T3) → node properties (short / fact-free long / chunks[] / bi-temporal / freshness / namespace) → dual chunk + 0-hop content embed → **MATCH ingest** (structured = `MERGE`/`MATCH-SET` $0; free-text = LLM extract only).
2. **STORE (Neo4j, one store):** the property graph (`:Entity`/`:RELATES_TO` bi-temporal fact/`:MENTIONS`/`:NEXT_EPISODE`) + all index types (label/range/FTS/vector HNSW) + the MATCH mutation engine (resolve/supersede/retract) + the lazy freshness lifecycle (dirty → re-embed, blast-radius ≤1-hop).
3. **SERVE (management):** agent query → role×query router (retrieve-or-not, T-cap≈3) → the **eval-gated ladder** (① graph index default → ② vector recall → ③ PageIndex) → RRF+rerank → the **online gate band** (namespace filter → validity/freshness stamp → sufficiency×confidence → faithfulness + APC action gate) → pass/partial/abstain/escalate.
4. **EVAL:** the load-bearing split — **offline calibration** (golden sets, eRAG source weights, ≥25-trial debiased judges, RAGChecker) *sets* the thresholds; **online enforcement** (deterministic namespace/Cypher, lightweight sufficiency classifier+confidence, context-perplexity, citation-required gen) *runs* per request. Three loops close the system: **stale/dirty → refresh** (serve→store), **conflict/gate-fail → requery ≤T=3** (serve→router), **offline calibration → online thresholds** (eval→serve).

**The composition is logically clean.** The data flows one way; the epistemic roles are consistent (graph=fact-authority, vector=recall-only, PageIndex=prose-authority) end to end; the offline/online split is correct; the loops are well-defined. Within each layer the engineering is honest and mostly sound — three prior review passes (3-expert panel, codex adversarial, Hermes) already drew the within-layer blood and the docs absorbed it with unusual integrity.

**But "composes logically" ≠ "composes into a shippable whole."** The drawbacks below live almost entirely in the **seams between layers** (which no single doc owns) and in the **eval layer's foundation** (measurement trust + the proxy→objective link).

---

## §2 — Validated drawbacks (deduped, severity-ranked, both reviewers + my judgment)

Tags: **[CONVERGENT]** = both reviewers independently flagged it (highest confidence). **[fixable]** = bounded engineering. **[foundational]** = needs a strategy, not code. **[ack]** = docs already disclose it (credit); **[gap]** = genuinely unaddressed.

### BLOCKERS (must fix before the beta can be trusted to *act*)

**B1 — Isolation is asserted but neither the FIELD nor the BUILD-time discipline exists. [CONVERGENT] [gap] [fixable]**
Two distinct, compounding failures of the one *hard security* property (`leakage = 0`):
- *No field:* the node-property schema (HYBRID PART 1 / LAYER1_TODO C2) and the index list (B3) store **no `namespace`/ACL on nodes — and none on fact-edges**, where the actual knowledge lives. `namespace` appears only in the *evidence schema* at fusion time and as a routing *axis*, never as a stored, indexed, queryable predicate. The deterministic filter the eval layer leans on filters a field that doesn't exist.
- *Build-time leak (upstream of any serve filter):* community summaries (member-set spanning domains), PageIndex tree glosses (multi-section docs), and multi-role doc embeddings **bake cross-role content at BUILD time**. A node-level namespace tag cannot represent a *mixed-role* unit, so the serve-time filter (and its attribution audit) structurally cannot catch it.
→ *Fix:* add `namespace` to the node **and edge** schema + index it; define namespace for derived artifacts (summaries/trees) or forbid cross-role aggregation; enforce isolation at build, not just serve. Bounded, but the schema doc (`ONTOLOGY_SCHEMA.md`) must commit to it.

**B2 — Stage-A ships the abstain/action gate WITHOUT the calibration the thesis calls mandatory. [CONVERGENT] [ack-partial] [fixable]**
`CONTEXT_EVALS §0` finding 2 is explicit: sufficiency-alone and confidence-alone are both wrong; only **sufficiency × confidence (logistic)** is validated, because models are 35–62% correct on insufficient context. But `§7` ships that mechanism in **Stage B**, and Stage A ships "abstain on risky claim types" — an uncalibrated proxy — on uncalibrated `T` / `τ` / source-weights (themselves public-benchmark constants standing in for unmeasured private values, exactly what §0 says doesn't transfer). So the "production-beta" acts on the gate shape the doc's own headline proves is harmful. The deferral is disclosed; that *the deferred piece is the load-bearing one* is not.
→ *Fix:* move sufficiency×confidence into Stage A, **or** stop calling the Stage-A action gate production-ready (downgrade to "suggest-only until calibrated").

**B3 — The calibration foundation is LLM-generated and self-unvalidated; eRAG's ground-truth is unsourced for a private corpus. [foundational] [gap]**
The golden set (the standard *everything* offline calibrates against) is RAGAS-TestsetGen synthetic Q&A over the company's own corpus: **an LLM writes the exam an LLM sits, and nothing validates the exam.** It's structurally blind to retrieval-miss / insufficient-context (it's built from what's retrievable). eRAG — the source-weight backbone — needs per-unit ground-truth answers; for a private brain with no public benchmark, those are either the same synthetic GT (circular) or an unbudgeted human-labeling program. The doc rigorously vets *external* benchmark provenance and never vets its *own primary instrument's* provenance. → "Calibrated" currently means "fit to an unverified target." *Fix is not code:* a human-seeded, validated GT slice + a labeling budget, before eRAG numbers can be trusted.

**B4 — No gate measures DECISION QUALITY; the layer optimizes proxies it has itself proven may not track the objective. [foundational] [gap]**
The system's stated goal is "the company brain helps agents make **better decisions**." Every eval dimension is a proxy *upstream* of that (retrieval/sufficiency/faithfulness). The doc's *own* headline finding — relevance ↛ answer-quality (eRAG τ 0.049 for LLM-judged relevance) — almost certainly recurs one rung out: **faithfulness ↛ decision-quality** (an answer can be 100% faithful to the wrong/complete-but-misleading facts and still drive a bad decision). There is no outcome / decision-audit / action-success gate to detect the divergence. *Fix is not code:* a decision-outcome loop (post-hoc action audit) — arguably partly the governance layer's job, but **nothing currently closes it**, so the eval layer cannot validate the brain's actual purpose.

### SERIOUS (degrade quality/trust over time; mostly fixable seams)

**S1 — Stale-embedding ↔ live-serve window. [CONVERGENT-ish] [gap] [fixable]** The "facts are live-queried at read, so the card is always current" defense protects *answer facts* but **not the vector recall that finds the node in the first place**. A node with a stale embedding can be missed (so the live-fact defense never fires) or wrongly surfaced. Worse, the docs are **internally contradictory** on whether a fact change re-embeds (PART 3-C says 0-hop "re-embed nothing"; PART 3-B's `dirty` flag pulls it into the re-embed sweep) — so the stale-window *size is undefined* — and the async sweep that closes it has **no liveness monitoring** (silent rot; cold nodes "stay stale until read"). *Fix:* resolve the 0-hop/1-hop contradiction, monitor the sweep (queue-depth alarm), define read-during-dirty semantics.

**S2 — Concurrent-write race on functional edges. [gap] [fixable]** The supersession Cypher is MATCH→SET→CREATE; two concurrent re-ingests of the same subject+relation both invalidate the same current edge and both CREATE new ones → **two "current" edges**, violating the functional-cardinality invariant the rule exists to enforce. No lock/MVCC/uniqueness-constraint story. *Fix:* serialize per-key, or a constraint/lock.

**S3 — Free-text extraction (the real "brain") is deferred past the $0 "plumbing" spine. [ack-partial] [scope]** The $0 structured-ETL milestone (D1) ingests the *keyed scaffold* deterministically, but the relational knowledge a company brain needs ("what blocks what," "which decision a PR implements," "why a task was dropped") lives in **free-text fields** (issue bodies, commit messages) handled by the deferred D4 LLM extraction. So "$0 spine proves Layer 1" conflates *proves the plumbing* with *proves the brain*; once D4 is the value driver it re-imports the full latency/cost/faithfulness-ceiling problem — worst on numbers/dates/names, i.e. issue IDs and dates.

**S4 — Faithfulness ~80% ceiling × the action gate, with no human-capacity model. [ack-partial] [gap on composition]** The faithfulness judge caps ~80% F1 *and is worst exactly on the claim types that dominate categorical actions* (dollar amounts, dates, entity names). The escalation trigger fires on the *judge's own verdict* — so it only catches what the unreliable judge correctly flags — and escalation volume scales with action volume with **no costed human capacity**: at real throughput the "autonomous agent army" collapses into a human-review queue.

**S5 — The judge program is a recurring eval-ops cost mislabeled as a finite task. [ack-partial] [gap]** ≥25 trials × 2 orders × 6 query-classes × 6 CXO-roles × every judge-metric ≈ **~1,800 judge calls per metric per sweep** (COMPUTED from the doc's own mandate), re-run on every threshold/model/drift change. The "no self-family" rule *forces* a per-token non-Anthropic judge (the expensive path). Correctly scoped out of the beta, but never *costed as a standing commitment*.

**S6 — Per-card validity/freshness reconciliation + "confidence" naming collision. [gap] [fixable]** A served node-card mixes per-node freshness (`dirty`) with per-edge validity (`superseded`); the rule when they disagree (clean node, one superseded fact among five current) is unspecified. And "confidence" names three different quantities across layers (retrieval confidence / generator self-confidence / per-claim faithfulness) — the exact collision the `long_context`-vs-PageIndex fix was meant to prevent.

**S7 — The per-relation rule trichotomy may not cover all relations. [ack] [fixable]** B2 (functional/additive + bi-temporal/static + structural/semantic) is "the load-bearing artifact," but codex already flagged it misses bounded-N, set-valued, time-windowed, and numeric/range contradictions — which fall back to LLM contradiction-detection, eroding the determinism claim by the fraction of messy relations. Open question in the one unwritten doc.

---

## §3 — Verdict: does the architecture make sense?

**Yes, the architecture makes sense — it is well-reasoned, internally consistent in its data flow and epistemic roles, and unusually honest within each layer. But it does NOT yet compose into a shippable whole**, for two distinct reasons the whole-system view exposes that the per-layer docs don't:

1. **The seams have holes no single doc owns.** Isolation has no field (B1); the abstain gate ships uncalibrated (B2); the embedding-staleness window is undefined and unmonitored (S1); writes can race (S2); per-card reconciliation and "confidence" are ambiguous (S6). These are **bounded, fixable** — but they're real seam failures, not nitpicks, and "Stage A = ship" currently overstates readiness.

2. **The eval layer's foundation and objective are asserted, not earned.** "Calibrated" means "fit to an LLM-generated, unvalidated target" (B3); and nothing measures the actual objective — decision quality (B4). These are **foundational** — not fixed by code, but by a measurement-trust strategy (human-seeded GT) and a decision-outcome loop.

**The sharpest framing (from the eval reviewer, and I agree): the docs' honesty is *asymmetric*.** They are rigorous about the limits *retrieval science already knows to disclaim* (relevance≠quality, ~80% faithfulness ceiling, judge bias, "no benchmark identified," offline≠online) — and they go quiet exactly where *this* project's specific debt lives: the provenance of its own test set, the GT behind its own calibration backbone, the build-time surface of its own security claim, the human capacity behind its own escalation valve, and the gap between its proxies and its goal. The fix for the architecture is, in part, to **apply its own disclosure discipline to its own bootstrapping economics.**

So: a strong, honest **design** that is **not yet a trustworthy system**. The gap between those two is exactly §2.

---

## §4 — What to fix before "shippable whole" (remediation, mapped)

**Bounded (do in the build):**
1. **Add `namespace`/ACL to the node AND edge schema + index it** (`ONTOLOGY_SCHEMA.md` B1/B3); define namespace for derived artifacts or forbid cross-role aggregation → closes B1.
2. **Resolve the 0-hop vs 1-hop embedding contradiction** (HYBRID PART 3-B/C) + add **sweep liveness monitoring** + define read-during-dirty semantics → closes S1.
3. **Either move sufficiency×confidence into Stage A or rename the Stage-A action gate "suggest-only until calibrated"** (`CONTEXT_EVALS §7`) → closes B2's honesty gap.
4. **Add a write-concurrency rule** (per-key serialize / constraint) to the MATCH engine → closes S2.
5. **Specify the per-card validity+freshness reconciliation rule + rename the three "confidence"s** → closes S6.

**Foundational (need a strategy, not just code):**
6. **A human-seeded, validated GT slice** (even small) before eRAG/golden-set numbers are trusted; state where eRAG GT comes from → addresses B3.
7. **A decision-outcome / action-audit loop** (does acting on the served context produce good decisions?) — the one gate that closes the proxy→objective gap → addresses B4.
8. **Cost the judge program + escalation capacity** as standing eval-ops, not a finite task → addresses S4/S5.

**Honest re-scope:** the $0 structured spine proves the *plumbing*; the *brain* is free-text-extraction-bound (S3) — frame the milestone accordingly.

---

## Provenance
Integration narrative: synthesized from `HYBRID_RETRIEVAL_ARCHITECTURE.md` (rev 4) + `CONTEXT_EVALS.md` + `LAYER1_TODO.md` + `EVIDENCE_LOG.md`. Drawbacks: **2 independent Opus adversarial reviewers (2026-06-02)** — systems-integration lens + eval-epistemics lens — every finding grounded in quoted doc text; deduped + severity-ranked + fixable/foundational-classified here, with my orchestrator judgment on the verdict. Convergent findings (B1, B2) carry the highest confidence. This doc is the whole-system companion to `CONTEXT_LAYER_INDEX.md`.
