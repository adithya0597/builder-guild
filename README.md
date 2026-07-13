# Builder Guild

**A graph-primary, bi-temporal, role-scoped knowledge base — with a calibrated evaluation layer — that an AI agent fleet can read from, write to, and be trusted with.**

Builder Guild is the knowledge spine an agent fleet reads and writes through. One graph-primary
store where facts are explicit, typed, point-in-time-queryable, and isolated per role — built so
**no LLM ever writes a fact** (zero hallucinated state), and **no metric certifies itself**
(every gate threshold is measured against human-validated ground truth, never asserted). The bet:
for organizational memory an agent can act on, a deterministic graph you can audit beats a vector
store you can only sample.

**New here?** Start with the [Quickstart](#quickstart), then the [docs front page](docs/README.md).
Questions or bugs → open a GitHub issue.

## Status — read this first

Context + retrieval run **end-to-end on a synthetic demo graph** (`python src/etl.py` →
`python src/serve.py demo`), CI-gated on a real Neo4j (import smoke + the ingest/write engine +
invariant sweeps). The evaluation layer ran its **first real calibration — and correctly refused
to certify autonomy** (see [the honest part](#the-honest-part-read-this-before-the-benchmarks)).

This is a **working research codebase, not a supported product.** There is no hosted service, no
enterprise deployment, and no autonomy grant: **every agent decision routes to a human today.** The
agent layer is a design + contract + one reference consumer; fleet orchestration and org-adoptable
templates are roadmap, not shipped. Run it locally, read the code, open an issue — but don't deploy
it expecting a product.

### What's built vs. what's not

- [x] Graph-primary, bi-temporal fact store with a **deterministic, zero-LLM write path**
- [x] **Namespace isolation** enforced at read time on **node AND edge** (defense-in-depth)
- [x] Hybrid retrieval — keyword → graph → vector, **RRF-fused**, role-scoped `serve()`
- [x] **Deterministic audit envelope** (input-sensitive `audit_id`) on every `serve()` call
- [x] **Staging truth-gate** — LLM-proposed facts enter as `:Candidate`; only a human-approved `promote()` writes an edge
- [x] **Suggest-only enforcement** — while a role is uncalibrated, even a `pass` decision is blocked and routed to a human
- [x] **Cross-session persistence** + deterministic ingest of real memory stores into a `history` namespace
- [x] Agentic **planner loop** + a read-only / suggest-only **MCP surface** (reference implementation)
- [x] **Evals machinery** — golden sets, debiased judges, eRAG source weights, calibration fit
- [~] Evidence provenance tags (11 fields on every fact; a deep `:Episodic` lineage link is deferred)
- [~] Action-audit outcome loop (records real decisions; outcome labels are still mock — no downstream telemetry yet)
- [~] Calibration (machinery shipped; the trust **grant is manual and founder-gated** — only *revoke* is automatic)
- [ ] Org-adoptable agent templates / workflows (design prose today, not a runnable onboarding path)
- [ ] Fleet orchestration (roadmap)
- [ ] Enterprise deployment (vision — see [Where this is going](#where-this-is-going))

## Quickstart

```bash
cd 01-context && docker compose up -d        # Neo4j (community)
bash setup_a2.sh                             # venv + driver + smoke test
. .venv/bin/activate                         # reuse that venv (else pip/python below hit system python)
export PYTHONPATH="$PWD/src:$PWD/../03-evals/src:$PWD/../02-agents/src"
pip install -r ../requirements.txt -r ../requirements-dev.txt   # adds sentence-transformers (EmbeddingGemma) for the vector path
python ../tools/apply_cypher.py schema/01_constraints.cypher schema/03_indexes.cypher   # constraints + indexes (vector rungs need these)
python src/etl.py                            # synthetic demo graph (deterministic writes)
python src/demo_seed.py                      # embed the seed + add the vector-path demo nodes (needs sentence-transformers)
python src/serve.py demo                     # end-to-end: retrieve→fuse→stamp→gate, traced
python ../02-agents/src/demo_agent.py        # an agent consuming governed context
python ../03-evals/src/golden.py             # golden-set schema + validation demo
```

Every module is self-demonstrating: run it, it prints a `*_OK` tag or a failure list. Those tags
double as the CI gates. Full local-dev walkthrough: [docs/README.md](docs/README.md).

## The three layers

```
01-context/   Context + Retrieval — the graph store, deterministic writes, hybrid retrieval
              (keyword → graph → vector, RRF-fused), role-scoped serving, ONLINE gates
02-agents/    Agent layer — agents as consumers of governed context: role trust boundary,
              suggest-only → leased autonomy, action audit
03-evals/     AI Evaluation — the OFFLINE program: golden sets, debiased judges, eRAG source
              weights, abstain-gate calibration, meta-evaluation
```

The layout encodes a safety rule (see `03-evals/CONTEXT_EVALS.md` §1): **online enforcement**
(namespace filters, the sufficiency×confidence gate) ships in `01-context/` and runs on every
retrieved-answer path (a no-retrieval result fails closed before the gate); **offline evaluation**
(judges, golden sets, calibration) lives in `03-evals/` and is never wired as a live decision signal.

## Why graph-primary

Vector RAG answers "what's similar?". It can't answer "who owns X **now**", "what was true
**when** we decided F", or "what's blocked, on whom, visible to which role" — the multi-hop,
point-in-time, permissioned questions a fleet actually asks. Builder Guild makes those first-class:

- **Three kinds of truth, never mixed:** current truth (bi-temporal edges, current = `invalid_at > now` via a sentinel stamp),
  role-scoped truth (namespace on node AND edge, enforced at read), temporal truth (as-of queries
  require historical evidence — current owner ≠ past owner).
- **Deterministic writes:** facts enter via `MERGE`/`MATCH…SET` ETL with per-relation rules
  (cardinality, supersession, contradiction policy). LLMs help *find*; they never *assert*.
- **Hybrid retrieval with honest roles:** keyword = exact IDs/names, graph = structural truth,
  vector = fuzzy recall. Fused by RRF with a fixed epistemic-authority ordering today; per-source
  weights are *measured* offline via eRAG (wiring them into live fusion is roadmap).
- **Abstention as a feature:** the serve gate combines sufficiency × confidence (never sufficiency
  alone — models answer correctly 35–62% of the time even on insufficient context). Uncalibrated
  ⇒ the system only *suggests*; autonomy is leased by evidence, per role, reversibly.

## The honest part (read this before the benchmarks)

This repo's evaluation layer caught its own system twice:

1. The serving gate's **sufficiency proxy fitted with a NEGATIVE weight** on real data — more
   retrieved facts predicted *less* correctness. Calibrating it into autonomy would have armed a
   harmful gate. Autonomy stayed off.
2. Fixing retrieval **unmasked a temporal-truth violation** — better recall made the system answer
   "as of <date>" questions from *current* state. Visible failure beats hidden failure.

Both are documented with numbers in the [calibration case study](03-evals/CASE_STUDY_calibration.md).
That discipline — measure, refuse, fix, re-measure — is the product. A trust layer that can't refuse
itself isn't a trust layer.

## Why I'm building this

I started this after watching the same two failures over and over: an agent loses its state between
sessions, and an agent confidently states a fact that was never true. My own personal knowledge
system — a capture-classify-graph pipeline I built to turn scattered thoughts into a versioned,
agent-readable knowledge layer, single-user, just for me — kept hitting the same wall.

Then an idea clicked. What actually stops an enterprise from handing real autonomy to AI agents?
It's trust. If you can **trace** every fact an agent reads and every decision it makes, set up
**guardrails**, **calibrate** an agent to act only on evidence, and **role-scope** it — so an agent
in an AI-native org can only reach the knowledge its role permits and can't make a decision its role
doesn't authorize — that's the unlock. Builder Guild is me building that spine in the open, starting
from the piece I understand best: the knowledge layer underneath.

This isn't only my hunch. The research literature frames trust — traceability, guardrails,
role-scoping — as *the* gating problem for enterprise agent autonomy: static, rule-based access
control is fundamentally insufficient for agents whose information flows are dynamic and contextual
([arXiv:2510.11108](https://arxiv.org/abs/2510.11108)), and deployed agentic systems need a
structured trust/risk/security framework spanning explainability and lifecycle governance to be
accountable at all ([arXiv:2506.04133](https://arxiv.org/abs/2506.04133)). Practitioners hit the
same wall from the other side: teams log the tool call but not the *policy decision*, so when
something breaks they can't tell whether policy allowed it or just never covered it
([HN](https://news.ycombinator.com/item?id=46719774)); and the hard part of an audit trail isn't
tamper-proofing, it's **completeness** — proving nothing was omitted
([HN](https://news.ycombinator.com/item?id=47079460)). Builder Guild answers those directly: a
deterministic write path (no LLM in the fact decision), namespace-scoped reads, and a
reproducible audit envelope on every `serve()` call.

## Where this is going

Today Builder Guild is a knowledge spine and a trust gate. The direction is three layers for
AI-native orgs — each clearly framed as where this is *headed*, not what it is:

- **A context layer** — the graph-primary, role-scoped, point-in-time-queryable memory an agent
  fleet reads from and writes to. This is what's furthest along (most of the [checklist](#whats-built-vs-whats-not) above).
- **An agent layer** — templates and workflows so any part of any org can run with autonomy without
  fearing an agent will act on a fact it shouldn't or take a call above its role. The goal is a
  system that **self-evolves and self-calibrates** as it grows: autonomy *leased* on measured
  evidence, *auto-revoked* on bad evidence. To be exact about today: the grant is **manual and
  human** (see the [founder gate](#founder-gate-mechanism-is-public-trust-grant-is-manual)); only
  the revoke direction runs automatically. The org-adoptable templates don't exist yet — what's in
  the repo is design prose, not a runnable onboarding path.
- **An evals layer** — the offline program that decides whether any of the above can be trusted,
  and refuses when it can't. This is the piece already exercising real discipline (see above).

Fleet orchestration is roadmap; enterprise deployment is vision. This section is the destination —
the [Status](#status--read-this-first) block is the odometer.

## Founder gate: mechanism is public, trust grant is manual

The repo ships the abstain mechanism and the enforcement boundary, not an automatic path to
agent autonomy.

- `01-context/src/abstain.py` keeps `CALIBRATED` as a per-role lease dict, defaulting every role to
  `False`.
- `abstain_gate()` computes the selective score from **sufficiency × self-confidence**. The shipped
  weights are provisional placeholders until a real fit is run.
- `execute()` is the real guardrail: while a role is uncalibrated, even a `pass` result is blocked
  and routed to a human. "Suggest-only" is enforced behavior, not metadata.
- `auto_revert()` is **revoke-only**. Bad evidence can flip a role from `True` back to `False`, but
  no production function grants `True`.

That creates an intentional asymmetry: code can revoke autonomy, never grant it.

The grant path lives in the founder review flow under `03-evals/`:

1. Validate the larger golden set by hand, see `03-evals/golden_v1_review.md`.
2. Run `03-evals/src/cal3_fit.py` on that validated golden + the live graph to refit the logistic
   and measure gain over the confidence-only baseline.
3. Run `03-evals/src/cal4_sweep.py` to measure judge stability and position bias.
4. Read `cal3_fit_results.json` and `cal4_results.json`.
5. Only then hand-edit `CALIBRATED[role] = True` for namespaces that earned the lease.

The public example set proves the mechanism and the refusal behavior. It does **not** prove that any
role deserves autonomous execution. That evidence is founder-only, graph-local, and intentionally
kept outside the auto-grant path.

## Building in public

I'm building this in the open because a trust layer nobody can inspect is a contradiction.
Contributions are welcome, with honest expectations:

- **I'm a solo maintainer, and review is the bottleneck** — not ideas. This is the well-documented
  open-source reality: contributions grow faster than any one person can review them. So the intake
  is deliberately bounded — I triage new issues weekly.
- **Open an issue before you open a PR.** Let's agree on the shape before you write code — it saves
  your time and mine. Unsolicited large PRs may sit unreviewed.
- **Keep PRs focused and explain the *why*.** If you touch a write path, include a determinism
  check: the same input ingested twice must produce the same graph — CI already asserts this (the
  `etl.py` self-test), so your check just needs to keep it true.
- **The invariants are non-negotiable — and machine-checked:** no LLM ever writes a fact; namespace
  on node *and* edge; bi-temporal by default. A CI write-gateway gate (`tools/check_write_gateway.py`)
  rejects edge writes outside the sanctioned path; [`CONTRIBUTING.md`](CONTRIBUTING.md) spells the
  rest out.
- **A lightweight CLA** keeps the dual license maintainable — you sign once, via an automated check
  on your first PR. Details in [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Found a security issue?** Please don't open a public issue — use GitHub's private
  vulnerability reporting (Security tab). See [`SECURITY.md`](SECURITY.md).

Where help is most useful right now: the vector / embedding rung (EmbeddingGemma-300M, local, $0),
the context-evals harness, and adapters for agent runtimes. Details in
[`CONTRIBUTING.md`](CONTRIBUTING.md); the roadmap is in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Docs

Start at the [docs front page](docs/README.md) — a navigable reference where every substantive claim
cites its `file:function` and was codex-reviewed against the source.

| Doc | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | the mental model: three layers, data model, the three kinds of truth, namespace isolation |
| [`docs/INGEST_AND_WRITE_PATH.md`](docs/INGEST_AND_WRITE_PATH.md) | how facts enter deterministically: ETL, `apply_edge`, the staging truth-gate |
| [`docs/RETRIEVAL_AND_SERVE.md`](docs/RETRIEVAL_AND_SERVE.md) | how a query becomes an answer: retrieval rungs, RRF + rerank, the `serve()` contract |
| [`docs/AGENTS_AND_MCP.md`](docs/AGENTS_AND_MCP.md) | the agent layer + external surface: the planner loop and the MCP servers (read/suggest only) |
| [`docs/EVALS_AND_TRUST.md`](docs/EVALS_AND_TRUST.md) | calibration, the abstain/autonomy gate, golden sets, judges, the case study |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | what's next, in capability terms (G1/G2/G3 + gate state) |
| [`03-evals/CASE_STUDY_calibration.md`](03-evals/CASE_STUDY_calibration.md) | the first real calibration run, numbers + verdict |

## License

Builder Guild is licensed under **AGPL-3.0** (see [LICENSE](LICENSE)) — free to
use, modify, and self-host, with network-use copyleft (§13). A **commercial
license** with no AGPL obligations is available for proprietary or
closed-hosted use — see [DUAL_LICENSE.md](DUAL_LICENSE.md), which also has
contact details for commercial licensing.

The default community-detection backend is networkx (BSD-3). An optional,
higher-quality Leiden backend (`requirements-leiden.txt`) pulls GPL deps and is
**off by default**.

Contributions require a lightweight CLA so the dual-license can be maintained —
see [CONTRIBUTING.md](CONTRIBUTING.md).
