# Builder Guild

**A graph-primary, bi-temporal, role-scoped knowledge base — with a calibrated evaluation layer — for a fleet of AI agents.**

Builder Guild is the knowledge spine an agent fleet reads from and writes to. One graph-primary
store where facts are explicit, typed, point-in-time-queryable, and isolated per role — built so
**no LLM ever writes a fact** (zero hallucinated state), and **no metric certifies itself**
(every gate threshold is measured against human-validated ground truth, never asserted).

> **Status:** context + retrieval layer integrated end-to-end on a live graph (23-module regression
> green); evaluation layer ran its first real calibration — and correctly **refused** to certify
> autonomy (see the [case study](03-evals/CASE_STUDY_calibration.md)). The agent layer is the
> design + contract + a demo consumer; fleet orchestration is roadmap.

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
(namespace filters, the sufficiency×confidence gate) ships in `01-context/` and runs in every
request; **offline evaluation** (judges, golden sets, calibration) lives in `03-evals/` and is
never wired as a live decision signal.

## Why graph-primary

Vector RAG answers "what's similar?". It can't answer "who owns X **now**", "what was true
**when** we decided F", or "what's blocked, on whom, visible to which role" — the multi-hop,
point-in-time, permissioned questions a fleet actually asks. Builder Guild makes those first-class:

- **Three kinds of truth, never mixed:** current truth (bi-temporal edges, `invalid_at IS NULL`),
  role-scoped truth (namespace on node AND edge, enforced at read), temporal truth (as-of queries
  require historical evidence — current owner ≠ past owner).
- **Deterministic writes:** facts enter via `MERGE`/`MATCH…SET` ETL with per-relation rules
  (cardinality, supersession, contradiction policy). LLMs help *find*; they never *assert*.
- **Hybrid retrieval with honest roles:** keyword = exact IDs/names, graph = structural truth,
  vector = fuzzy recall. Fused by RRF; sources weighted by *measured downstream utility* (eRAG),
  not assumed authority.
- **Abstention as a feature:** the serve gate combines sufficiency × confidence (never sufficiency
  alone — models answer correctly 35–62% of the time even on insufficient context). Uncalibrated
  ⇒ the system only *suggests*; autonomy is leased by evidence, per role, reversibly.

## Quickstart

```bash
cd 01-context && docker compose up -d        # Neo4j (community)
bash setup_a2.sh                             # venv + driver + smoke test
export PYTHONPATH="$PWD/src:$PWD/../03-evals/src:$PWD/../02-agents/src"
python src/etl.py                            # synthetic demo graph (deterministic writes)
python src/serve.py demo                     # end-to-end: retrieve→fuse→stamp→gate, traced
python ../02-agents/src/demo_agent.py        # an agent consuming governed context
python ../03-evals/src/golden.py             # golden-set schema + validation demo
```

Every module is self-demonstrating: run it, it prints a `*_OK` tag or a failure list.

## The honest part (read this before the benchmarks)

This repo's evaluation layer caught its own system twice:

1. The serving gate's **sufficiency proxy fitted with a NEGATIVE weight** on real data — more
   retrieved facts predicted *less* correctness. Calibrating it into autonomy would have armed a
   harmful gate. Autonomy stayed off.
2. Fixing retrieval **unmasked a temporal-truth violation** — better recall made the system answer
   "as of <date>" questions from *current* state. Visible failure beats hidden failure.

Both are documented with numbers in the [calibration case study](03-evals/CASE_STUDY_calibration.md).
That discipline — measure, refuse, fix, re-measure — is the product.

## Docs map

| Doc | What it covers |
|---|---|
| `01-context/ONTOLOGY_SCHEMA.md` | entity/relationship taxonomy, namespaces, per-relation write rules |
| `01-context/HYBRID_RETRIEVAL_ARCHITECTURE.md` | the full design: write path, read path, freshness, conflict |
| `01-context/RETRIEVAL.md` · `PAGEINDEX_PILOT.md` | retrieval evidence base; long-doc navigation pilot |
| `02-agents/AGENT_ARCHITECTURE.md` | agents on governed context: roles, trust boundary, leased autonomy |
| `03-evals/CONTEXT_EVALS.md` | the eval research synthesis (39 sources, paper-walked) |
| `03-evals/CASE_STUDY_calibration.md` | the first real calibration run, numbers + verdict |
| `docs/ROADMAP.md` | what's next, in capability terms |

## License

See [LICENSE](LICENSE). Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
