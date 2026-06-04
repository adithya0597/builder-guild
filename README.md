# Builder Guild

**A graph-primary, bi-temporal, hybrid-retrieval knowledge base — the shared "company brain" for a fleet of AI agents.**

Builder Guild is the knowledge spine a team of autonomous agents reads from and writes to. Instead of giving each agent its own opaque vector store, Builder Guild keeps **one graph-primary store** where facts are explicit, typed, point-in-time-queryable, and isolated per role — built so that **no LLM ever writes a fact** (zero hallucinated state), while LLMs are still free to help *find* things.

> **Status: M1 deterministic spine built + verified** — Neo4j substrate + schema + deterministic ETL + live node-card assembly + the retrieval-ladder skeleton. The vector/embedding rung and the context-evals layer are designed and in progress (see [`docs/`](docs/)).

## Why graph-primary

Vector RAG answers "what's similar to this?" It can't answer "who owns X **now**", "what was the budget **when** we approved feature F", or "what's blocked, and on whom" — the multi-hop, point-in-time, relational questions an agent fleet actually needs. Builder Guild makes those first-class:

- **Typed relationships**, not just embeddings — `ASSIGNED_TO`, `BLOCKS`, `DEPENDS_ON`, `OWNS`, …
- **Bi-temporal edges** — every fact carries *valid_at / invalid_at* (true-in-world) **and** *created_at / expired_at* (system-knowledge), so you can query the graph **as of any point in time**.
- **Deterministic writes** — facts are written with `MERGE` / `MATCH … SET` per an explicit per-relation rule table ([`relations.yaml`](company-brain/schema/relations.yaml)). **No LLM in the fact path.**
- **Namespace isolation** — a `namespace` on every node **and** edge means a role-scoped read physically cannot see another domain's facts (Finance can't read Engineering).

## Architecture at a glance

- **Substrate:** Neo4j 5.26 Community (range + fulltext + 768-dim vector indexes, all native).
- **Ontology (tiered):** T0 = six domains (Engineering · Product · Finance · Market · Operations · Governance) = the namespace partitions; T2 = entity-type labels (Agent, Issue, Repo, Budget, Feature, …).
- **Topology:** `:Entity` facts · `:RELATES_TO` bi-temporal edges · `:Episodic` provenance · `:MENTIONS` · `:NEXT_EPISODE` timeline.
- **Node card** is assembled **live at read time** = fact-free `long_context` + a *live* bi-temporal edge query, role-scoped and validity-stamped (nothing fact-bearing is cached).
- **Retrieval ladder:** graph index (default, instant, 0-LLM) → vector recall (eval-gated) → long-doc drill (eval-gated). The graph **scopes**; vector/long-doc **drill**.
- **Recall layer (LLM-OK):** embeddings + HyDE-style hypothetical-question vectors live on separate `:SearchProxy` nodes — out of the fact path *by construction*, so they improve findability but can never assert a fact.
- **Eval-gated:** a context-evals layer (faithfulness, isolation = 0, abstain calibration) decides what's trusted; offline calibration is kept separate from online enforcement.

The full design lives in [`docs/`](docs/): [`HYBRID_RETRIEVAL_ARCHITECTURE.md`](docs/HYBRID_RETRIEVAL_ARCHITECTURE.md) (the spine), [`ONTOLOGY_SCHEMA.md`](docs/ONTOLOGY_SCHEMA.md), [`RETRIEVAL.md`](docs/RETRIEVAL.md) (retrieval levers), [`CONTEXT_EVALS.md`](docs/CONTEXT_EVALS.md) (eval methodology), [`SYSTEM_COHERENCE.md`](docs/SYSTEM_COHERENCE.md) (whole-system review), and [`LAYER1_TODO.md`](docs/LAYER1_TODO.md) (the build roadmap).

## Quickstart

Requires Docker and Python 3.10+.

```bash
git clone https://github.com/adithya0597/builder-guild.git
cd builder-guild
cp .env.example .env                 # tweak NEO4J_PASSWORD if you like

cd company-brain
# 1. Neo4j substrate (bolt :7687, browser :7474)
docker compose up -d
bash verify_a1.sh                    # confirms range + fulltext + vector indexes exist

# 2. Python client
python3 -m venv .venv && . .venv/bin/activate
pip install -r ../requirements.txt

# 3. Load the schema (constraints, indexes, topology, node props)
for f in schema/*.cypher; do
  docker exec -i cb-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD:-companybrain}" < "$f"
done

# 4. Run the deterministic ETL spine on the built-in fixture
python etl.py        # MERGEs a small fixture company into the graph — 0 LLM
python serve.py      # assembles a role-scoped, validity-stamped node card
python ladder.py     # the retrieval ladder (graph rung)
```

To ingest a live **Paperclip** company instead of the fixture, set `PAPERCLIP_COMPANY_ID` (and `PAPERCLIP_BASE_URL`) in `.env`, then run `python etl_live.py`.

## Repo layout

```
company-brain/
  docker-compose.yml      Neo4j 5.26 Community stack
  schema/*.cypher         constraints · indexes · topology · node props
  schema/relations.yaml   per-relation rule table (drives deterministic writes)
  etl.py                  deterministic ETL spine (fixture) — 0 LLM
  etl_live.py             live ingestion from a Paperclip instance
  serve.py                node-card assembly (role-scoped, validity-stamped)
  ladder.py               retrieval ladder (graph → vector → long-doc)
  smoke_test.py           write/read smoke test
docs/                     design notes (architecture, ontology, evals, roadmap)
```

## Contributing

Open project — see [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome, especially around the vector/embedding rung, the eval harness, the recall layer, and adapters for other agent runtimes.

## License

[GPL-3.0](LICENSE) © Builder Guild contributors.
