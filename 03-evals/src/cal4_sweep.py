"""CAL-4 (G3): the full >=25-trial DEBIASED judge sweep — resumable background batch.

Judge-based metrics only get judge-based rigor (§0 mandate): >=25 trials with median+percentiles,
position-swap on every pairwise comparison, no-self-family (asserted in judge_adapter at import).
Deterministic metrics were settled deterministically in CAL-2/CAL-3 and are NOT re-judged here —
25 trials of an exact-match would measure nothing.

Sweep composition (REAL hermes gpt-5.4 calls, ~23 s/call mean n=3, 3 workers, checkpointed):
  pointwise  2 prose items x 25 trials                      =  50 calls (match-rate dispersion)
  pairwise   2 prose items x 25 trials x 2 orders           = 100 calls (position-bias measured)
  easy-agree 8 deterministic items x 3 trials               =  24 calls (judge sanity floor;
             agreement vs deterministic labels — INFLATED by design, labelled as such)
Every verdict checkpoints to cal4_progress.jsonl (resume = skip done keys). ~174 calls -> ~22 min
at 3 workers (LABELED-ESTIMATE from 23 s mean).

Outputs cal4_results.json: per-item match medians/percentiles, position-bias delta, easy-case
agreement, and the discretionary judge-vs-human kappa with its N (=2 -> reported UNMEASURABLE).
DOES NOT flip CALIBRATED.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np

# 01-context/src must be on path (mirroring eval_corrective.py convention)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

from golden import read_golden
from serve import serve
from judge_adapter import score_match, judge_pair, load_checkpoint
from cal3_fit import answer_text

HERE = os.path.dirname(os.path.abspath(__file__))
CKPT = os.path.join(HERE, "cal4_progress.jsonl")
TRIALS = 25
WORKERS = 3
PROSE = ["fin-s2", "eng-m1"]
EASY_TRIALS = 3


def main():
    fail = []
    items = {i["id"]: i for i in read_golden(os.path.join(HERE, "..", "example_golden.jsonl"))}
    answers = {iid: answer_text(serve(items[iid]["question"], items[iid]["role"])) for iid in items}

    jobs = []
    for iid in PROSE:
        q, gold = items[iid]["question"], items[iid]["correct_answer"]
        for t in range(TRIALS):
            jobs.append(("point", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         score_match(q, answers[iid], gold, key=f"cal4:point:{iid}:t{t}", ckpt=CKPT)))
            jobs.append(("pairA", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         judge_pair(q, answers[iid], gold, key=f"cal4:pairA:{iid}:t{t}", ckpt=CKPT)))
            jobs.append(("pairB", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         judge_pair(q, gold, answers[iid], key=f"cal4:pairB:{iid}:t{t}", ckpt=CKPT)))
    # Item 3 fix: exclude abstain-expected items from the easy-agree judge jobs.
    # Sending abstain-expected items to the prose judge inflated kappa (the judge always
    # sees "abstain" vs "abstain" as trivially matching — the kappa-inflation artifact).
    # Abstain items are scored on the DECISION channel in cal3_fit.label_correct, not here.
    easy = [iid for iid in items
            if iid not in PROSE and items[iid].get("expected_decision") != "abstain"]
    for iid in easy:
        q = items[iid]["question"]
        gold = items[iid]["correct_answer"]
        gold_s = ", ".join(gold) if isinstance(gold, list) else gold
        for t in range(EASY_TRIALS):
            jobs.append(("easy", iid, t, lambda iid=iid, t=t, q=q, gold_s=gold_s:
                         score_match(q, answers[iid], gold_s, key=f"cal4:easy:{iid}:t{t}", ckpt=CKPT)))

    done_before = len(load_checkpoint(CKPT))
    print(f"[sweep]   {len(jobs)} judge jobs ({done_before} already checkpointed -> resumed), "
          f"{WORKERS} workers")
    errors = []
    def run(job):
        kind, iid, t, fn = job
        try:
            return kind, iid, t, fn()[0]
        except Exception as e:
            errors.append(f"{kind}:{iid}:t{t}: {e}")
            return kind, iid, t, None
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(run, jobs))
    print(f"[sweep]   completed; errors={len(errors)}")
    for e in errors[:5]:
        print(f"            ERR {e}")

    out = {"trials": TRIALS, "workers": WORKERS, "errors": errors, "items": {}}
    by = {}
    for kind, iid, t, v in results:
        if v is not None:
            by.setdefault((kind, iid), []).append(v)

    # pointwise match dispersion + pairwise position bias, per prose item
    for iid in PROSE:
        pts = [1.0 if v["match"] else 0.0 for v in by.get(("point", iid), [])]
        a_first = [1.0 if v["winner"] == "first" else 0.0 for v in by.get(("pairA", iid), [])]
        a_second = [1.0 if v["winner"] == "second" else 0.0 for v in by.get(("pairB", iid), [])]
        arr = np.array(pts) if pts else np.array([np.nan])
        debiased = (np.mean(a_first) + np.mean(a_second)) / 2 if (a_first and a_second) else float("nan")
        pos_bias = abs(np.mean(a_first) - np.mean(a_second)) if (a_first and a_second) else float("nan")
        out["items"][iid] = {
            "match_median": float(np.median(arr)), "match_mean": round(float(np.mean(arr)), 3),
            "match_p10": float(np.percentile(arr, 10)), "match_p90": float(np.percentile(arr, 90)),
            "n_trials": len(pts),
            "serve_winrate_debiased": round(float(debiased), 3),
            "position_bias_delta": round(float(pos_bias), 3)}
        print(f"[{iid}]  match median={out['items'][iid]['match_median']} "
              f"mean={out['items'][iid]['match_mean']} n={len(pts)} | serve-vs-gold debiased "
              f"winrate={out['items'][iid]['serve_winrate_debiased']} "
              f"position-bias-delta={out['items'][iid]['position_bias_delta']}")
        fail += [] if len(pts) >= TRIALS else [f"{iid} pointwise n={len(pts)} < {TRIALS}"]

    # easy-case agreement: judge majority vs the deterministic CAL-3 labels (sanity floor, inflated)
    cal3 = json.load(open(os.path.join(HERE, "cal3_fit_results.json")))
    det_label = {r["id"]: r["correct"] for r in cal3["rows"]}
    agree = []
    for iid in easy:
        votes = [1 if v["match"] else 0 for v in by.get(("easy", iid), [])]
        jl = 1 if sum(votes) * 2 >= len(votes) else 0
        agree.append(1 if jl == det_label[iid] else 0)
    out["easy_agreement"] = {"rate": round(float(np.mean(agree)), 3), "n": len(agree),
                             "note": "judge vs deterministic labels on easy items — sanity floor, INFLATED by design"}
    print(f"[easy]    judge-vs-deterministic agreement={out['easy_agreement']['rate']} (n={len(agree)})")

    # discretionary judge-vs-HUMAN kappa: N=2 -> unmeasurable, reported as such
    out["discretionary_kappa"] = {"n": len(PROSE), "value": None,
                                  "verdict": "UNMEASURABLE at N=2 (needs 6-role golden set)"}
    print(f"[kappa]   discretionary judge-vs-human: N={len(PROSE)} -> UNMEASURABLE (by design of this slice)")

    import abstain
    # CALIBRATED is now a dict; must-not-flip guard: all namespaces remain False
    all_false = isinstance(abstain.CALIBRATED, dict) and all(v is False for v in abstain.CALIBRATED.values())
    fail += [] if all_false else ["CAL-4 must not flip CALIBRATED (all namespaces must stay False)"]
    fail += [] if not errors else [f"{len(errors)} judge calls failed"]

    with open(os.path.join(HERE, "cal4_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("[write]   cal4_results.json")
    if fail:
        print("CAL4_FAIL:", fail); sys.exit(1)
    print("CAL4_OK")


if __name__ == "__main__":
    main()
