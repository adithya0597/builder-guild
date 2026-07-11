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

Comment on the issue you're taking before opening a PR, so two people don't duplicate the same work. If a PR already exists for it, work with that author instead of opening a competing one.

## AI-assisted contributions

AI-assisted PRs are welcome — this project is built with AI tools too.

- **Disclosure required.** State the tool and how much of the change it produced in the PR description (an `Assisted-by:` trailer works too).
- **A human owns every PR.** Commits can be agent-authored; the PR can't be agent-owned — the person submitting it must understand the change without AI help.
- **Judged on quality and intent, not origin.** Unreviewed, low-effort AI output may be closed without detailed feedback.
- **Routine use is exempt.** Autocomplete, Q&A, and code-explanation don't need disclosure.

## Licensing & contributor agreement (please read)

Builder Guild is **dual-licensed**: AGPL-3.0 for everyone, plus a separate commercial license for users who can't accept AGPL's network-copyleft (see [DUAL_LICENSE.md](DUAL_LICENSE.md)).

For the project to keep offering that commercial option, the maintainer must be able to license **all** of the code — including your contribution — under **both** licenses. So contributions require a lightweight **Contributor License Agreement (CLA)**: you keep copyright to your work and grant the maintainer the right to license it under AGPL-3.0 **and** the commercial license.

- By opening a PR you agree your contribution is offered under these terms.
- Signing is a one-time automated check (cla-assistant) that runs on your first PR — sign once and every future PR is covered.
- **Don't paste in code you can't relicense** (e.g. GPL-only snippets) — it would break the dual-license guarantee for everyone.

*Not legal advice — the CLA text itself should be finalized with counsel.*
