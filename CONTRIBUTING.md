# Contributing to Builder Guild

Thanks for your interest — Builder Guild is early and the surface area is wide, so contributions are very welcome.

## Ground rules (the invariants that make this work)

- **Never let an LLM write a fact.** The fact path (`:Entity` nodes + typed `:RELATES_TO` bi-temporal edges) is deterministic by design. LLM-generated content belongs only in the **recall layer** (`:SearchProxy` nodes, embeddings, hypothetical questions) — never in entity properties or edges.
- **Namespace on node *and* edge.** Any new node type or relation must carry a `namespace`. Isolation is a hard property, not a filter you can forget to apply.
- **Bi-temporal by default.** New edge types respect `valid_at` / `invalid_at` (and `created_at` / `expired_at`). *Functional* edges supersede (invalidate the old, add the new); *additive* edges accumulate. See [`01-context/schema/relations.yaml`](01-context/schema/relations.yaml).
- **No secrets in commits.** Everything sensitive comes from environment variables — see [`.env.example`](.env.example). The repo ships only a local-dev Neo4j password.

## Dev setup

Follow the Quickstart in the [README](README.md). Useful checks:

- `bash 01-context/verify_a1.sh` — confirms your Neo4j has the required range/fulltext/vector index types.
- `python 01-context/smoke_test.py` — fastest write/read sanity check.

## Where help is most useful

- The **vector / embedding rung** (EmbeddingGemma-300M, local, $0) — making vector recall live.
- The **context-evals harness** — faithfulness, isolation = 0, abstain calibration.
- The **recall layer** — HyDE / hypothetical-question generation on `:SearchProxy` nodes.
- **Adapters** for agent runtimes beyond Paperclip.

## Pull requests

Keep changes focused and explain the *why*. If you touch a write path, include a determinism check: the same input ingested twice must produce the same graph (idempotency is a core guarantee).
