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
