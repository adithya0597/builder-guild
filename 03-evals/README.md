# 03-evals — the AI evaluation layer

The offline program that turns asserted thresholds into measured ones. Nothing in this directory
runs inside a live request (`CONTEXT_EVALS.md` §1: never wire an offline metric as a live decision
signal). The research base is `CONTEXT_EVALS.md` — 39 sources, results-table-walked, with every
load-bearing number tagged.

## The pipeline (each stage is a runnable module)

```
golden.py          the golden-set CONTRACT: two-level labels (support_facts ⟂ correct_answer),
                   normal / null / temporal / temporal_null kinds, abstain probes, schema validation
gt2_draft.py       draft-then-human-validate: an LLM drafts Q+candidate+support-facts FROM THE
                   GRAPH (grounded, reproducible); a human confirms — candidates are never
                   promoted to ground truth automatically (no self-grading)
judge_adapter.py   any one-shot CLI judge (env JUDGE_CMD/JUDGE_MODEL): strict-JSON verdicts,
                   exponential backoff, per-verdict checkpoint/resume, no-self-family guard
h2b3_judge.py      the DEBIASING harness: position-swap, length-control, ≥25-trial floor with
                   median+percentiles, self-family rejection — demonstrated against a mock judge
                   with known biases (naive 1.00 → debiased 0.50)
cal2_erag.py       eRAG source weights: each retrieved unit scored by what it ALONE answers vs
                   gold (downstream utility, not relevance) → per-source weights
cal3_fit.py        the real fit: live serve() traces × human labels → sufficiency×confidence
                   logistic; selective accuracy vs a confidence-only baseline; TAU* derived from
                   a human-chosen loss ratio (wrong-act : missed-act)
cal4_sweep.py      the full ≥25-trial debiased judge sweep as a resumable, checkpointed batch
h2b1_calib.py      fit machinery + synthetic fixture (the unit-test side of cal3)
h3_instr.py        Phase-A instrumentation: score every serve call, change nothing
```

`example_golden.jsonl` is a synthetic 10-item set (ACME demo org) mirroring the structure of a
human-validated production set — including the null (cross-role + absent-entity) and
temporal-abstain probes.

## Scoring rules that survived contact with reality

1. **Deterministic-first.** ID/enum/set/abstain answers are scored by exact logic; the LLM judge
   is reserved for prose equivalence. 8/10 of the reference golden set never needed a judge.
2. **Abstain items are decision-channel, never text-channel.** "Does `''` match `'abstain'`" is a
   category error a naive judge fails on; score *did the system abstain*, not the text.
3. **Judge-human agreement (κ) needs enough judgment-items to mean anything.** With N=2
   discretionary items, κ is unmeasurable at any value — and inflated agreement on deterministic
   items measures parser correctness, not judgment. Design golden sets for measurable κ.
4. **The calibration may refuse.** A negative fitted weight on a "sufficiency" signal is the eval
   layer telling you the proxy is broken. Refusing to certify is a success mode.

See it all happen on real data: [`CASE_STUDY_calibration.md`](CASE_STUDY_calibration.md).
