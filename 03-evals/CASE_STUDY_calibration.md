# Case study — the first real calibration run (and why it refused to certify)

A complete, real execution of the eval pipeline against a live deployment of this architecture:
a 15-node / 6-namespace operating graph, a 10-item human-validated golden set (the structure
mirrored by `example_golden.jsonl`, ACME ids here), and an external cross-family judge CLI at $0
marginal cost. Names are demo-org; every number is a real measurement from the run.

## Setup

- **Generator:** deterministic fact-serving (no LLM writes facts → generator has no model family
  to bias the judge toward).
- **Judge:** an external CLI judge (gpt-class model), non-self-family, strict-JSON verdicts,
  every verdict checkpointed (full sweep resumable). Latency measured n=174: median 12.8 s,
  p90 20.2 s — which makes the ≥25-trial sweep a background batch, never an inline loop.
- **Governance, fixed before the run:** loss ratio C(wrong act) : C(missed act) = **10:1** for
  routine actions; irreversible/security categorically human-gated; *the run cannot flip the
  autonomy flag* — it produces an evidence packet for a human.

## Run 1 — the system as it stood

| Measure | Result |
|---|---|
| Golden accuracy (base rate) | **0.40** (4/10) |
| eRAG source weights | graph 0.512 / vector 0.488 — near parity; graph patterns over-retrieve (one `ASSIGNED_TO` pattern returns every issue of that assignee) |
| Fitted gate | W_SUFFICIENCY **−3.167** (negative!), W_CONFIDENCE +1.304 |
| Selective accuracy | combined 0.90 vs confidence-only 0.80 → **+10.0pp** |
| TAU* @ 10:1 | 0.41 → acts 3/10, **wrong-acts 0**, missed-correct 1 |
| Judge stability | zero dispersion across 25 trials × both orders; position-bias delta 0.0 |
| Judge-human κ | **unmeasurable** — only 2 items required judge discretion (8/10 scored deterministically) |

**Verdict: do not certify.** Two measured disqualifiers, one structural one:

1. **The sufficiency proxy was anti-correlated with correctness.** "Number of retrieved facts / 3"
   measures *how much came back*, not *whether it answers the question*. A cross-role probe
   retrieved 2 facts (high "sufficiency") and was wrong; the correct abstentions scored 0.
   Calibrating that proxy into an autonomous gate would have armed a harmful one.
2. **The serving layer was 40% correct on its own golden set** — answer-shape gaps (edge-only
   cards, single-card answers, no multi-hop composition), not retrieval failures.
3. **κ had no sample to stand on** — the golden set was too deterministic to measure judge trust.

## The fixes (driven by the run's failure table)

1. **Content channel:** present node content alongside edge facts (status/prose answers live in
   content). 2. **Multi-card composition + 1-hop expansion:** set answers and second hops span
   cards. 3. **Keyword/exact-ID retrieval rung:** "what does ACME-2 block" was embedding-matching
   cards containing the *word* "blocked" instead of the node named ACME-2 — a lexical-semantic
   trap a deterministic ID rung removes. Gate inputs were deliberately left unchanged (don't feed
   an uncalibrated proxy a bigger number for free); isolation re-proven after each change.

## Run 2 — after the fixes

| Measure | Result |
|---|---|
| Golden accuracy | **0.80** (from 0.40) |
| Fitted gate selective accuracy | **1.00 @ TAU\*=0.67** — acts 8/10, wrong-acts 0, missed-correct 0; it abstains on exactly the two genuinely-wrong cases |
| Selective gain | **+10.0pp, stable across all three fits** |
| W_SUFFICIENCY | still negative (−4.089) — the proxy needs replacing, not more data |

And one new failure, the most instructive of the run: **better retrieval unmasked a temporal-truth
violation.** The as-of probe ("who owned ACME-4 as of <date>?") had been *passing* its abstain
expectation only because retrieval was too weak to find the node. With the keyword rung, the
system confidently answered from **current** ownership — exactly the "current truth ≠ historical
truth" violation the architecture bans. The temporal-evidence layer moved up the roadmap; the
golden item stays red until it exists.

## What this case study claims — and refuses to claim

- The machinery (golden → deterministic-first scoring → debiased judge → fit → evidence packet)
  runs end-to-end on live data, reproducibly, at $0 marginal judge cost. ✔
- A sufficiency×confidence gate beats confidence-alone selectively (+10pp, three independent
  fits) — consistent with the published +5–10pp effect. ✔
- **N=10 is a smoke test.** No research-grade claim is made; κ remains unmeasured; the autonomy
  flag remains off. The calibration's most valuable outputs were its refusals: a broken proxy
  caught before it gated anything, and a temporal gap surfaced by a capability gain.

The pattern to copy is the ratchet: **measure → refuse → fix → re-measure**, with every refusal
recorded as precisely as every pass.
