# Agents and MCP — the external interface

Agents don't own knowledge; they consume governed context. This doc is the navigable reference
for everything that sits *outside* the context layer (`01-context/`) and talks to it: the
agentic-RAG planner, the two MCP servers, the suggest-only prose-miner, the optional web
fallback, and the two reference agents. The design rationale lives in `02-agents/AGENT_ARCHITECTURE.md`,
`02-agents/MCP_RUNBOOK.md`, and `02-agents/COORDINATION_PATTERNS.md` — this doc summarizes and
cross-links them rather than repeating them.

**The one invariant that governs every file below: the agent surface is READ + SUGGEST only.**
No file documented here imports the edge-write engine (`mutate.apply_edge`) directly. Agent/LLM
proposed candidates only ever become a real graph edge via `staging.promote()`, run by a human
from the staging CLI — that step also delegates to `mutate.apply_edge`, the sole edge-write
gateway. (Trusted structured ETL, outside this doc's agent surface, writes edges straight through
`mutate.apply_edge` without staging — `01-context/src/etl.py:93-116` — but no code documented
here calls that path.)

## What you'll find here

- [The read contract](#the-read-contract) — `serve()`, roles as trust boundaries
- [planner.py — the agentic-RAG loop](#plannerpy--the-agentic-rag-loop)
- [mcp_server.py — read-only MCP](#mcp_serverpy--read-only-mcp)
- [mcp_stage_server.py — agent-facing MCP (plan + suggest)](#mcp_stage_serverpy--agent-facing-mcp-plan--suggest)
- [extract.py — suggest-only LLM prose-miner](#extractpy--suggest-only-llm-prose-miner)
- [web_fallback_adapter.py — corrective web fallback](#web_fallback_adapterpy--corrective-web-fallback)
- [demo_agent.py + fix_decision.py — reference agents](#demo_agentpy--fix_decisionpy--reference-agents)
- [Shipped vs roadmap](#shipped-vs-roadmap)
- [Source of truth](#source-of-truth) / [See also](#see-also)

## The read contract

`serve(query_text, role, ...)` in `01-context/src/serve.py` is the primary query contract every
agent goes through. The read-only MCP server also exposes a second, narrower read path,
`node_card(key, as_of)`, which calls `_node_card()` directly rather than `serve()`
(`02-agents/src/mcp_server.py:57-61`) — still read-only, still role-scoped. `role` is a trust
boundary, not a performance knob: it must be bound by the *caller's environment*, never accepted
as a parameter from an untrusted client (`02-agents/AGENT_ARCHITECTURE.md` §1-2). Every server
documented below enforces this the same way — role/namespace comes from an environment variable
read once at process start, and no `@mcp.tool()` function below has a role/namespace argument for
a client to fill in.

## planner.py — the agentic-RAG loop

`02-agents/src/planner.py` is the one place in this repo where an agent *chooses its own
retrieval strategy* rather than following a fixed script. Entry point:

```python
plan(question, role, *, max_steps=4, tau=0.5, as_of=None, _serve=None) -> dict
```

Each iteration of the bounded loop (`plan()`, `planner.py:214-352`) does three things:

1. Call `serve(current_query, role, pattern=current_pattern, as_of=as_of)` — one retrieval probe.
2. Read *that step's* signal (decision, score, sufficiency, self_confidence) via
   `_read_confidence()` (`planner.py:63-84`), deriving `score` from `abstain.selective_score`
   only when the result carries `sufficiency` and `self_confidence` but no `score` yet. The true
   no-retrieval early-abstain path (`serve.py:310-317`) has no `gate_abstain`, `sufficiency`, or
   `self_confidence` at all, so `score` stays `None` there.
3. If not yet answered, hand the signal to `_choose_next()` (`planner.py:139-211`) — the
   agentic core — which picks the next retrieval **mode** based on what came back:

   | Signal | Chosen mode | What it does |
   |---|---|---|
   | No facts at all (UNSUPPORTED abstain) | `id_extract` → `graph_pattern` | Re-query on extracted ids first (`_extract_ids`), then a structural verb→relation probe (`_extract_verb_rel` + `_split_ids_by_verb`) derived from the *original* question, not the mutated current query (`planner.py:170-184`) |
   | Has facts, still abstaining | `neighbor_hop` | Pull 1-hop neighbor keys from `presentable_facts` and, cautiously, from `composed_evidence` prose, then re-query (`_neighbor_keys`, `planner.py:106-127`) |
   | Low sufficiency (`< 0.34`) with some recall | `decompose` | Split the question into sub-queries and probe each core term set (`planner.py:198-209`) |

   A no-op guard (`_probe_key`, `planner.py:57-60`) prevents re-trying an identical
   `(query, pattern)` pair.

**Untrusted-prose guard (pdk).** `composed_evidence` is LLM-composed narrative prose, not a
retrieved edge — an attacker-influenceable content card could contain a forged `issue:FORGED-999`
token. `_resolve_seed_tokens()` (`planner.py:87-103`) only lets a token seed the next probe if it
resolves to a real, in-scope `:Entity` (namespace-checked against the role's `allowed_namespaces`);
`_neighbor_keys()`'s own self-test (`_pdk_selftest`, `planner.py:355-372`) proves a real seeded
entity survives and a forged one does not.

**Isolation is asserted every step**, not just once (`planner.py:244-271`): a missing
`trace.isolation` is only tolerated on the genuine early-abstain shape (nothing retrieved); if
something *was* retrieved with no isolation record, `plan()` raises rather than defaulting clean.

**Termination is honestly labeled** (`planner.py:292-334`) — five outcomes, only one of which is
a real answer:

- `"confidence"` — genuine answer (decision is `pass`/`partial`)
- `"escalate"` — gate routed to a human; **not** an answer
- `"confident_abstain"` — score crossed `tau` but the decision is still abstain (guarded so a
  pure-cosine, zero-support score never masquerades as confidence — `planner.py:299-306`)
- `"abstain"` — no fresh probe left
- `"max_steps"` — bounded loop exhausted on a non-abstain, non-answer state

Injecting `_serve` (tests use this for isolation, `planner.py:11`, `221-223`) avoids the default
`serve()` connection, but doesn't guarantee zero Neo4j traffic: `_neighbor_keys()` can still call
`_resolve_seed_tokens()`, which opens its own Neo4j driver directly to validate composed-evidence
seed tokens (`planner.py:87-103`, `119-125`, `188-190`).

## mcp_server.py — read-only MCP

`02-agents/src/mcp_server.py` is a stdio MCP server (FastMCP) with exactly four tools, all
read-only over `serve()`/`node_card()`:

| Tool | Signature | Notes |
|---|---|---|
| `query_context` | `(query_text, pattern=None, deep_serve=False, rerank=False, include_communities=False, as_of=None)` | Returns the `serve()` envelope verbatim — no post-filtering, no gate bypass (`mcp_server.py:34-54`) |
| `node_card` | `(key, as_of=None)` | Role-scoped node card; `as_of` for point-in-time (`mcp_server.py:57-61`) |
| `health` | `()` | Connectivity check against `bg-neo4j`, no write (`mcp_server.py:64-69`) |
| `list_namespaces` | `()` | This server's bound-role namespace slice (`mcp_server.py:72-75`) |

`ROLE` comes from `BG_MCP_ROLE`, read once at import (`mcp_server.py:26`) and **validated
fail-fast** in `__main__` before `mcp.run()` — an invalid or unset role exits non-zero rather
than serving with a default (`mcp_server.py:78-82`). No tool signature has a role/namespace
parameter, so a client that sends one has no field for it to land in — FastMCP's generated
(pydantic) schema silently drops it (`mcp_server.py:1-7`).

`selftest_mcp.py` proves this end to end over a live stdio subprocess: exact tool-set match,
client-supplied `role="governance"` ignored (env role wins), the full gated envelope present
(no filtered keys), a malformed `pattern` surfacing as a clean tool error without killing the
server, a second server instance started with `BG_MCP_ROLE=governance` reporting governance's
wider slice, and a no-`BG_MCP_ROLE` startup failing fast (`selftest_mcp.py:37-139`). Prints
`MCP_SERVE_OK`.

Runbook, client wiring, and the role→namespace table: `02-agents/MCP_RUNBOOK.md`.

## mcp_stage_server.py — agent-facing MCP (plan + suggest)

`02-agents/src/mcp_stage_server.py` exposes exactly two tools — the bounded planner loop and a
suggest-only staging call — bound to role *and* staging namespace from the environment
(`BG_MCP_ROLE`, `BG_STAGE_NS`), both validated fail-fast before `mcp.run()`
(`mcp_stage_server.py:73-84`).

```python
plan_context(question, max_steps=4, as_of=None) -> dict   # planner.plan() over the bound role
propose_edge(s_key, rel, o_key, evidence=None, source=None) -> str   # -> cand_id
```

- `plan_context` clamps `max_steps` to `[1, 8]` at the tool boundary (`MAX_STEPS_CAP=8`,
  `mcp_stage_server.py:40`; clamp expression at `mcp_stage_server.py:68-70`) —
  `planner.plan()`'s `range(1, max_steps+1)` would silently return an empty envelope for
  `max_steps <= 0` if unclamped.
- `propose_edge` calls `staging.stage_llm()` **only** — it can create a pending `:Candidate` and
  nothing else. This file imports no edge-write engine at all, so it is structurally incapable
  of writing a graph edge (`mcp_stage_server.py:8-11`). Re-proposing an identical
  `(s_key, rel, o_key)` is idempotent (first-write-wins, same as the underlying gate).
- Turning a candidate into a real edge is a separate, human-only step run from `staging`'s own
  CLI — deliberately never surfaced as an MCP tool here.

**No-write-leak invariant**, checked two ways:
1. Structurally — no `mutate` import, no reference to `staging.promote/approve/reject`.
2. Mechanically, in `selftest_stage_mcp.py`'s `_grep_gate()` (`selftest_stage_mcp.py:74-85`) —
   a source-level regex scan of `mcp_stage_server.py` for `staging\.(promote|approve|reject)` and
   `mutate\.`, the exact leak a lexical import-scan on `import staging; staging.<verb>(...)`
   cannot catch by itself.

`selftest_stage_mcp.py` also proves a proposed candidate is **invisible** to a same-key
`node_card()` read (pending ≠ visible fact, `selftest_stage_mcp.py:108-133`), that `plan_context`
returns a well-formed bounded envelope including the `max_steps=0` floor regression guard
(`:152-160`), that `as_of` forwards through `plan_context` → `plan()` → `serve()` all the way to
a planted bi-temporal supersession (`:162-184`), and three startup-failure shapes (missing
`BG_STAGE_NS`, out-of-scope `BG_STAGE_NS`, missing `BG_MCP_ROLE`). Prints `STAGE_MCP_OK`.

## extract.py — suggest-only LLM prose-miner

`01-context/src/extract.py` mines already-ingested Observation/Source prose (`long_context` on
`:Entity:Observation`/`:Entity:Source` nodes from the `etl_history` ingest path) for free-form
`(subject, relation, object)` triples via an external LLM, and stages the accepted ones as
`:Candidate` nodes — origin `"llm"`, never a written edge (`extract.py:1-8`).

**How a triple gets accepted or dead-lettered** (`mine()`, `extract.py:138-169`):

1. Pull prose nodes for the namespace (`_prose_nodes`, `extract.py:130-135`).
2. For each, call the LLM once (`_call`) and parse the last balanced JSON array out of its output
   (`_parse` / `_last_array`, `extract.py:61-108`).
3. Map the LLM's free-form relation string onto the **16-relation enum** read directly from
   `01-context/schema/relations.yaml` (`_normalize_rel`, `extract.py:111-116`) — read directly
   rather than importing the mutation engine, because importing it would trip the write-gateway's
   import scan and license a write the suggest-only posture must not have (`extract.py:12-13`).
4. An unknown relation, or an LLM reply that isn't parseable JSON, is written to
   `01-context/extract_deadletter.jsonl` and **never staged** (`_deadletter`, `extract.py:119-127`).
5. Accepted triples go through `staging.stage_llm()` **only** — the same suggest-only entrypoint
   `mcp_stage_server.py.propose_edge` uses.

**EXTRACT_CMD contract** — the LLM is reached only through a subprocess CLI, never a vendor SDK
or network library (`extract.py:10`):

- `EXTRACT_CMD` unset → `mine()` is a clean no-op, `([], 0)` (`extract.py:144-146`).
- `EXTRACT_CMD` set but not resolvable to an executable → loud `RuntimeError`, never a silent
  disable (`extract.py:147-149`).
- Auth/payment/quota signal in the CLI's output (`_is_auth_payment_error`, `extract.py:54-58`,
  copied verbatim from `03-evals/src/judge_adapter.py`'s $0/STOP guard) → hard `RuntimeError`
  **before** the returncode is even checked — never a silent fallback to a paid path
  (`_call`, `extract.py:79-95`).
- A present-but-broken CLI (nonzero returncode) is a loud malfunction, not trusted stdout.

A dead-letter file cap (5 MB, `_DEADLETTER_CAP`, `extract.py:46`) rolls to a single `.1`
generation so a runaway or adversarial `EXTRACT_CMD` can't disk-fill (`_deadletter`,
`extract.py:119-127`).

`01-context/src/selftest_extract.py` proves the fixture/dead-letter/skip/STOP slice of this with a
**throwaway fixture** `EXTRACT_CMD` (a tiny self-written script echoing canned JSON — never a real
LLM call): one valid triple stages exactly one `origin='llm'` candidate (`EXTRACT_FIXTURE_OK`), an
unknown relation and malformed JSON both dead-letter without staging (`EXTRACT_DEADLETTER_OK`),
and an unset `EXTRACT_CMD` degrades clean (`EXTRACT_SKIP`, `selftest_extract.py:46-107`). The
unconditional `_selftest_stop()` guard (auth-regex + broken-CLI rejection) runs first and requires
no `EXTRACT_CMD` at all (`selftest_extract.py:46-48`). The dead-letter roll cap and a set-but-
unresolvable `EXTRACT_CMD` are proved separately, in `extract.py` itself
(`_selftest_roll`/`EXTRACT_ROLL_OK`, `extract.py:204-240`; `_selftest_badcmd`/`EXTRACT_BADCMD_OK`,
`extract.py:248-254`). CI wiring for the fixture path is still pending (`extract.py:21-22` —
"CI-wirable next run", not yet CI-gated).

## web_fallback_adapter.py — corrective web fallback

`01-context/src/web_fallback_adapter.py` is Corrective-RAG's optional web branch (§5) — **off by
default**, gated by `CORRECTIVE_WEB_ENABLED` (must be exactly `"true"`, case-insensitive,
`is_enabled()`, `web_fallback_adapter.py:39-43`). When disabled, the default path after local
retrieval tactics exhaust is an abstain result annotated `resolved_at="exhausted"` — normal flow
when this adapter isn't explicitly turned on (`web_fallback_adapter.py:16-18`).

When enabled, `fetch(query_text, role)` (`:95-115`) builds a role-scoped prompt and calls a
one-shot CLI (`CORRECTIVE_WEB_CMD -z <prompt> -m CORRECTIVE_WEB_MODEL`) with exponential backoff
(`_call`, `:46-92`). It shares the same $0-or-STOP discipline as `extract.py`: any
auth/key/payment/billing/quota signal in the CLI's output raises immediately, never falling back
to a paid path (`_AUTH_RE`, `:32`). Facts returned are tagged `provenance="web"`
(`web_fallback_adapter.py:113-115`), but corrective serving doesn't rank them as lower-authority
graph evidence — it segregates them entirely into a `web_advisory` field tagged
`scope="external-unverified"`, re-grades the decision through the same faithfulness gate as
UNSUPPORTED, and never merges them into `presentable_facts`/`composed_evidence`
(`01-context/src/corrective.py:294-323`); `epist.DEFAULT_AUTHORITY` has no web weight at all
(`epist.py:20-25`). Only ever reached from `corrective_serve()` when both `web_fallback=True` is
passed *and* the env flag is on (`:20-21`).

## demo_agent.py + fix_decision.py — reference agents

**`02-agents/src/demo_agent.py`** is the smallest correct agent — 92 lines, because the context
layer does the work. `agent_step()` (`demo_agent.py:20-31`) asks through `serve()`, checks
`r["executed"]` (only ever `True` when the namespace is calibrated *and* the gate passed), and
otherwise treats a pass/partial as a suggestion routed to a human, or an abstain as "no action
proposed." `demo()` (`:34-88`) proves, against a live graph: an in-scope question never
auto-executes while uncalibrated; an out-of-role question surfaces zero isolation leakage
(`:42-45`, the decision itself isn't asserted here); the audit loop is exercised by attaching a
simulated outcome (`:47-48` — no real downstream-outcome telemetry exists yet); and — via
`planner.plan()` — a multi-step question
self-chooses ≥ 2 distinct retrievals, terminates on `"confidence"`, and actually answers with the
seeded `ASSIGNED_TO → agent:cto` edge (not just any non-empty blob, `:74-75`). Prints
`DEMO_AGENT_OK`.

**`02-agents/src/fix_decision.py`** is the action-audit loop that keeps the gate honest after
calibration: faithfulness (facts were grounded and present, `record_decision`, `:20-32`) is a
*proxy*; decision quality (the realized outcome, `attach_outcome`, `:35-43`) is the *objective*,
and the two are deliberately independent — a faithful answer can still drive a bad decision, and
an abstain can still be the right call. `audit()` (`:46-56`) surfaces both proxy-gap directions
(`faithful_but_bad`, `unfaithful_but_good`). **Honest scope note baked into the module's own
docstring** (`fix_decision.py:11-14`): there is no real downstream-outcome telemetry yet —
outcomes recorded here are mock-labelled. This module is the *seam* where real outcomes would be
recorded; it does not gate `serve()` and does not flip `CALIBRATED`.

## Shipped vs roadmap

| Capability | Status | Evidence |
|---|---|---|
| **G1 — Agentic RAG** (this doc's `planner.py` + both MCP surfaces) | ✅ **CLOSED** | `docs/ROADMAP.md:74-77`; self-test `PLANNER_OK`, CI-gated, agent-callable via `mcp_stage_server.py`'s `plan_context` |
| **G2 — Multimodal RAG (OCR)** | ✅ **CLOSED** | `docs/ROADMAP.md:80-88`: `etl.ingest_ocr_doc` embeds at ingest via `embed.embed_node` and is retrieved through the live `serve()` vector rung (`01-context/src/etl.py --g2-selftest` → `G2_OCR_SERVE_OK`). Vision/ColPali deliberately not adopted as default — OCR outperforms it per the cited benchmark; see ROADMAP for the full citation |
| **G3 — Calibration / autonomy lease** | ❌ **OPEN, founder-gated** | `docs/ROADMAP.md:90-101`; `abstain.py`'s `CALIBRATED` dict defaults every namespace to `False` (`abstain.py:26`); the last real calibration sweep **failed** its coverage gate and fit the sufficiency proxy with a **negative** weight (`03-evals/CASE_STUDY_calibration.md`) |

**Do not read any of the above as "autonomy works."** Every agent and MCP tool documented in
this file is suggest-only today: `plan_context` and `query_context` only ever read;
`propose_edge` only ever stages a pending candidate; `extract.mine()` only ever stages or
dead-letters. The only way an agent/LLM-proposed candidate enters the graph is a human running
`staging.promote()`, which delegates to `mutate.apply_edge` — the sole edge-write gateway for
both this promote path and the structured-ETL path outside the agent surface.

## Source of truth

- `02-agents/src/planner.py`
- `02-agents/src/mcp_server.py`
- `02-agents/src/mcp_stage_server.py`
- `02-agents/src/selftest_mcp.py`
- `02-agents/src/selftest_stage_mcp.py`
- `02-agents/src/demo_agent.py`
- `02-agents/src/fix_decision.py`
- `01-context/src/extract.py`
- `01-context/src/selftest_extract.py`
- `01-context/src/web_fallback_adapter.py`

## See also

- `02-agents/AGENT_ARCHITECTURE.md` — the design rationale: roles as trust boundaries, why
  autonomy is *leased* not granted, the action-audit loop
- `02-agents/MCP_RUNBOOK.md` — client wiring, prereqs, role→namespace table for `mcp_server.py`
- `02-agents/COORDINATION_PATTERNS.md` — the five fleet-coordination patterns for when multiple
  agents share the context layer
- `docs/ROADMAP.md` — current G1/G2/G3 status and citations
- `03-evals/CASE_STUDY_calibration.md` — why `CALIBRATED` stays `False` today
- `01-context/src/abstain.py` — the action gate (`CALIBRATED`, `selective_score`, `auto_revert`)
