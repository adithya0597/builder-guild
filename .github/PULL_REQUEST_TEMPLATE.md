## What & why
<!-- What does this change and why? Link any related issue. -->

## Invariants checklist (Builder Guild keeps these by design)
- [ ] **No LLM writes a fact** — LLM output stays in the recall layer (`:SearchProxy`, embeddings, hypothetical questions), never in `:Entity` properties or `:RELATES_TO` edges
- [ ] **Namespace** present on any new node type *and* edge (isolation is a hard property, not an optional filter)
- [ ] **Bi-temporal** — new edges respect `valid_at`/`invalid_at`; functional edges supersede, additive edges accumulate (see `company-brain/schema/relations.yaml`)
- [ ] **No secrets** committed (env vars only; see `.env.example`)
- [ ] **Determinism** — the same input ingested twice produces the same graph

## How tested
<!-- commands run / output -->
