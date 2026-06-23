# Serve-Join Design (SERVE_JOIN_DESIGN)

How `serve()` augments graph evidence with deep long-document (PageIndex) prose and feeds **both**
through the *single* sufficiency×confidence gate. This is the design the inline citations in
`01-context/src/serve.py`, `evidence.py`, and `pageindex_adapter.py` refer to (§1–§3, §2.1, §2.3, §7).

Scope: the serve-join is **opt-in and $0 by default**. Every existing caller of `serve()` is
byte-identical with the drill OFF; the deep rung executes only under `deep_serve=True`. In the public
mirror the drill is always **stubbed** (`pageindex_adapter` returns `resolved_at="gated"`); a real
drill is a private grant (an authenticated retrieval call over a private long-document index) for
which this repo ships the *mechanism + interface*, not the grant itself.

## §1 — Overview: one homogeneous evidence set, one gate

Graph retrieval (keyword + graph + vector → RRF-fused) yields structured facts. The serve-join adds a
second evidence kind — prose sections drilled from a long document — and **normalizes both into a
single homogeneous evidence set** that the existing gate consumes. There is no second gate and no
separate "PageIndex answer": a drilled section becomes an `EvidenceItem` alongside graph facts, is
ordered by `epist` authority, and is judged by the same `abstain` stage.
(Referenced from `evidence.py` §1–§3.)

## §2 — The deep rung: trigger signal + drill

### §2.1 — Frozen trigger constant

The deep rung is *warranted* when ALL of these hold (the signal is ALWAYS computed and traced,
regardless of `deep_serve`):

1. non-empty `query_text` (there is something to navigate for);
2. `coverage_initial < DEEP_COVERAGE_TAU` — the graph evidence does not already cover the question.
   `DEEP_COVERAGE_TAU` is the **frozen trigger constant** defined in `evidence.py`;
3. a long-document node is in scope with a non-empty `pageindex_doc_sha` (an empty-string sha is
   treated as absent); and
4. the answer surface is not isolation-leaked.

`serve()` selects the same candidate the retrieval ladder would (`sorted(in-scope nodes with
pageindex_ref)[0]`). The signal (`deep_warranted`) is recorded in `trace["serve_join"]` even when the
drill does not run, so the coverage gap is observable without paying for the drill.

### §2.3 — Drill interface contract

A drill (real or stub) fulfills:

```
drill(allowed, query_text, t_cap) -> {
    "resolved_at": "pageindex" | "gated",
    "answer":   str,            # prose answer synthesized over the selected sections
    "doc":      str,            # the host long-doc node key
    "sections": [str, ...],     # selected section node id(s)
}
```

- `"pageindex"` — resolved: `answer` + `doc` + `sections` are populated.
- `"gated"` — could not resolve (no grant / no live tree): NO augmentation; the gate runs on the
  original graph evidence (fail-safe).

The public stub always returns `"gated"` with zero external calls; tests inject a fake via
`pageindex_adapter._inject(fn)` to exercise the positive path. (Referenced from `pageindex_adapter.py`.)

## §3 — Hard boundary + freshness contract

**Hard boundary.** `evidence` decides evidence **shape** only; `epist` decides authority **ordering**;
the **gate** decides actionability. These three never bleed into each other — a drilled section never
"wins" by itself; it is ordered, then judged, like any other evidence.
(Referenced from `evidence.py` §3.)

**Freshness contract.** A drilled section inherits the freshness of its **host** long-doc node:

- host confirmable + fresh → the section is actionable evidence;
- host confirmable + dirty (stale) → the section is included but **non-actionable** (a stale claim is
  a hard faithfulness violation, so the gate refuses to act and routes to a human);
- host **unconfirmable** (out of scope / missing) → the section is **dropped** (fail-closed): no
  `EvidenceItem` with a fabricated namespace ever reaches the answer or the gate.

This is the freshness propagation cited at `evidence.py` (the freshness contract) and `serve.py`.

## §7 — `deep_serve` opt-in (the $0 default-off law)

`serve(..., deep_serve=False)` is the default. With it off:

- the trigger SIGNAL is still computed + traced (so the gap is observable), but
- the drill **never executes**: `deep_fired = deep_warranted AND deep_serve`, so there are zero
  external/LLM calls and behavior is identical to pre-serve-join.

The drill runs only under `deep_serve=True` AND a warranted signal — keeping deep retrieval an
explicit, budgeted, intentional-run decision.

## Validation

- `serve.py` `INT3_OK` demo: exercises the `deep_serve=True` positive path (asserts `deep_fired` and
  `deep_augmented` and `resolved_at == "pageindex"`) AND the $0 default-off law (a tripwire proves the
  drill is NOT called when `deep_serve=False`), all via the stub injection.
- `pageindex_adapter.py` `PAGEINDEX_ADAPTER_OK`: the drill interface contract + the inject mechanism
  (gated stub, positive fake, restore) — CI-gated.

> Calibration scope: `03-evals/cal3_fit.py` and `cal4_sweep.py` currently fit/sweep the gate on the
> GRAPH-ONLY `serve()` path; a `deep_serve` calibration refit is deferred pending a real PageIndex
> deployment + a prose-augmented golden set. The serve-join *mechanism* is validated as above (6gw).
