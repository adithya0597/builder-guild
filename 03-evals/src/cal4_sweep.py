"""CAL-4 (G3): the full >=25-trial DEBIASED judge sweep — resumable background batch.

Judge-based metrics only get judge-based rigor (§0 mandate): >=25 trials with median+percentiles,
position-swap on every pairwise comparison, no-self-family (asserted in judge_adapter at import).
Deterministic metrics were settled deterministically in CAL-2/CAL-3 and are NOT re-judged here —
25 trials of an exact-match would measure nothing.

Sweep composition (REAL judge-CLI gpt-5.4 calls, ~23 s/call mean n=3, 3 workers, checkpointed):
  pointwise  2 prose items x 25 trials                      =  50 calls (match-rate dispersion)
  pairwise   2 prose items x 25 trials x 2 orders           = 100 calls (position-bias measured)
  easy-agree 8 deterministic items x 3 trials               =  24 calls (judge sanity floor;
             agreement vs deterministic labels — INFLATED by design, labelled as such)
Every verdict checkpoints to cal4_progress.jsonl (resume = skip done keys). ~174 calls -> ~22 min
at 3 workers (LABELED-ESTIMATE from 23 s mean).

Outputs cal4_results.json: per-item match medians/percentiles, position-bias delta, easy-case
agreement, and the discretionary judge-vs-human kappa with its N (=2 -> reported UNMEASURABLE).
Does not grant leases. Any auto-revert action is process-local evidence for founder review; it
does not persist a lease rewrite or revoke an already-running serving process.

SERVE-JOIN SCOPE (6gw): like cal3_fit, this sweep runs serve() GRAPH-ONLY (deep_serve OFF) — it
does not judge the serve-join / deep_serve (PageIndex) path. The serve-join path is validated
separately (serve.py INT3_OK + PAGEINDEX_ADAPTER_OK); a deep_serve judge sweep is deferred pending
a real PageIndex corpus.
"""
import argparse
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
from judge_adapter import score_match, judge_pair, load_checkpoint, is_unscored, judge_available
from cal3_fit import answer_text, _is_exact_gold

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLDEN_PATH = os.path.join(HERE, "..", "example_golden.jsonl")
DEFAULT_CKPT = os.path.join(HERE, "cal4_progress.jsonl")
DEFAULT_CAL3_RESULTS = os.path.join(HERE, "cal3_fit_results.json")
DEFAULT_RESULTS_PATH = os.path.join(HERE, "cal4_results.json")
TRIALS = 25
WORKERS = 3
EASY_TRIALS = 3


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run the CAL-4 debiased judge sweep on a golden set.")
    p.add_argument("--golden", default=DEFAULT_GOLDEN_PATH,
                   help="Path to a validated golden JSONL file. Defaults to the public example set.")
    p.add_argument("--cal3-results", default=DEFAULT_CAL3_RESULTS,
                   help="Path to cal3_fit_results.json for easy-case agreement labels.")
    p.add_argument("--ckpt", default=DEFAULT_CKPT,
                   help="Path to the resumable judge checkpoint JSONL file.")
    p.add_argument("--out", default=DEFAULT_RESULTS_PATH,
                   help="Path to write cal4_results.json.")
    return p.parse_args(argv)


def sweep_autorevert(role, kappa, gain, kappa_bar=0.8, gain_bar=0.0):
    """Fail-closed, process-local evidence wrapper around abstain.auto_revert.

    Unmeasurable inputs (None/NaN/inf) are revoke-worthy by definition. This mutates only this
    sweep process's imported abstain.CALIBRATED dict; it does not persist a lease rewrite or revoke
    any already-running serving process.
    """
    import abstain
    if not (abstain._is_measurable_number(kappa) and abstain._is_measurable_number(gain)):
        if abstain.CALIBRATED.get(role, False):
            abstain.CALIBRATED[role] = False
            return {"role": role, "revoked": True,
                    "reason": f"kappa={kappa} gain={gain} -> unmeasurable, process-local revoke evidence"}
        return {"role": role, "revoked": False,
                "reason": "already False -> no-op (unmeasurable, process-local evidence only)"}
    return abstain.auto_revert(role, kappa, gain, kappa_bar, gain_bar)


def apply_autorevert(kappa, gain, kappa_bar=0.8, gain_bar=0.0):
    """Run sweep_autorevert over every namespace currently leased in this process.

    This is evidence-only for persisted/live-serving lease state. It never claims to revoke another
    Python process. Returns (actions, fail): actions is {role: action} for roles that were leased (empty
    dict when nothing was leased -- the common/default case); fail is a list of founder-policy
    violation messages (empty = policy holds). Policy: every role must be False unless it passed
    BOTH bars this sweep -- collapses to 'if anything is still leased, kappa/gain both passed',
    since kappa/gain are sweep-wide scalars, not per-role."""
    import abstain
    actions = {r: sweep_autorevert(r, kappa, gain, kappa_bar, gain_bar)
               for r, leased in list(abstain.CALIBRATED.items()) if leased}
    passed_both_bars = (abstain._is_measurable_number(kappa)
                         and abstain._is_measurable_number(gain)
                         and kappa >= kappa_bar and gain >= gain_bar)
    still_leased = [r for r, v in abstain.CALIBRATED.items() if v]
    fail = [] if (not still_leased or passed_both_bars) else [
        f"founder policy violated: {still_leased} remain leased without kappa>={kappa_bar} "
        f"and gain>={gain_bar} (kappa={kappa}, gain={gain})"]
    return actions, fail


def main(argv=None):
    args = parse_args(argv)
    fail = []
    items = {i["id"]: i for i in read_golden(args.golden)}

    # PROSE = pass items whose gold is free-form (not an entity key / enum / set / abstain). Derived
    # from the golden, not hardcoded — an all-deterministic set yields [] (the old ["fin-s2","eng-m1"]
    # KeyError'd on any non-example golden). §0: deterministic facts were already settled in cal3.
    prose = [iid for iid, it in items.items()
             if it.get("expected_decision") != "abstain"
             and not isinstance(it["correct_answer"], list)
             and not _is_exact_gold(it["correct_answer"])]

    if not prose:
        # Fully deterministic golden: nothing for the judge to score. cal4's whole purpose is judge
        # rigor on prose (position-bias, match dispersion, judge-vs-human kappa) -> all N/A here, and
        # cal3 is the operative gate. Emit an explicit N/A packet; invoke NO judge and NO serve.
        out = {"trials": TRIALS, "workers": WORKERS, "errors": [], "items": {}, "prose_items": [],
               "easy_agreement": None,
               "discretionary_kappa": {"n": 0, "value": None,
                   "verdict": "N/A — golden has no prose items; judge sweep + kappa gate not applicable"},
               "judge_degradation": {"unscored_count": 0, "by_kind_item": {},
                                      "sentinel_degraded": False},
               "verdict": "FULLY_DETERMINISTIC — no prose items; cal3 is the operative gate; judge not invoked"}
        print(f"[input]   golden={args.golden}")
        print("[prose]   0 prose items -> judge sweep + easy-agree + kappa gate N/A (cal3 is operative)")
        actions, arfail = apply_autorevert(kappa=None, gain=None)
        out["autorevert"] = actions
        out["autorevert_scope"] = "process-local evidence only; no persistent/live serving-process revoke"
        print(f"[gate]    autorevert actions={actions} (kappa=None gain=None -> unmeasurable; "
              f"fail-closed process-local evidence; founder flips only, not this)")
        if arfail:
            print("CAL4_FAIL:", arfail); sys.exit(1)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2)
        print(f"[write]   {args.out}")
        print("CAL4_OK (deterministic golden — judge sweep skipped)")
        return

    answers = {iid: answer_text(serve(items[iid]["question"], items[iid]["role"])) for iid in items}

    jobs = []
    for iid in prose:
        q, gold = items[iid]["question"], items[iid]["correct_answer"]
        for t in range(TRIALS):
            jobs.append(("point", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         score_match(q, answers[iid], gold, key=f"cal4:point:{iid}:t{t}", ckpt=args.ckpt)))
            jobs.append(("pairA", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         judge_pair(q, answers[iid], gold, key=f"cal4:pairA:{iid}:t{t}", ckpt=args.ckpt)))
            jobs.append(("pairB", iid, t, lambda iid=iid, t=t, q=q, gold=gold:
                         judge_pair(q, gold, answers[iid], key=f"cal4:pairB:{iid}:t{t}", ckpt=args.ckpt)))
    # Item 3 fix: exclude abstain-expected items from the easy-agree judge jobs.
    # Sending abstain-expected items to the prose judge inflated kappa (the judge always
    # sees "abstain" vs "abstain" as trivially matching — the kappa-inflation artifact).
    # Abstain items are scored on the DECISION channel in cal3_fit.label_correct, not here.
    easy = [iid for iid in items
            if iid not in prose and items[iid].get("expected_decision") != "abstain"]
    for iid in easy:
        q = items[iid]["question"]
        gold = items[iid]["correct_answer"]
        gold_s = ", ".join(gold) if isinstance(gold, list) else gold
        for t in range(EASY_TRIALS):
            jobs.append(("easy", iid, t, lambda iid=iid, t=t, q=q, gold_s=gold_s:
                         score_match(q, answers[iid], gold_s, key=f"cal4:easy:{iid}:t{t}", ckpt=args.ckpt)))

    done_before = len(load_checkpoint(args.ckpt))
    print(f"[input]   golden={args.golden} cal3_results={args.cal3_results} ckpt={args.ckpt}")
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
    unscored_by = {}
    for kind, iid, t, v in results:
        if v is not None:
            if is_unscored(v):
                unscored_by[f"{kind}:{iid}"] = unscored_by.get(f"{kind}:{iid}", 0) + 1
                continue
            by.setdefault((kind, iid), []).append(v)
    unscored_count = sum(unscored_by.values())
    # Founder split (run-5), mirroring cal3_fit: absent judge degrades (recorded, per-item n<TRIALS
    # gates below still catch missing coverage); present-but-malfunctioning judge is a hard FAIL.
    judge_absent = not judge_available()
    out["judge_degradation"] = {"unscored_count": unscored_count,
                                "by_kind_item": unscored_by,
                                "sentinel_degraded": bool(unscored_count),
                                "judge_absent": judge_absent}
    fail += [] if (not unscored_count or judge_absent) else [
        f"judge scoring degraded with JUDGE_CMD present: {unscored_count} unscored trials {unscored_by}"]

    # pointwise match dispersion + pairwise position bias, per prose item
    for iid in prose:
        pts = [1.0 if v["match"] else 0.0 for v in by.get(("point", iid), [])]
        a_first = [1.0 if v["winner"] == "first" else 0.0 for v in by.get(("pairA", iid), [])]
        a_second = [1.0 if v["winner"] == "second" else 0.0 for v in by.get(("pairB", iid), [])]
        arr = np.array(pts) if pts else None
        debiased = (np.mean(a_first) + np.mean(a_second)) / 2 if (a_first and a_second) else None
        pos_bias = abs(np.mean(a_first) - np.mean(a_second)) if (a_first and a_second) else None
        out["items"][iid] = {
            "match_median": (float(np.median(arr)) if arr is not None else None),
            "match_mean": (round(float(np.mean(arr)), 3) if arr is not None else None),
            "match_p10": (float(np.percentile(arr, 10)) if arr is not None else None),
            "match_p90": (float(np.percentile(arr, 90)) if arr is not None else None),
            "n_trials": len(pts),
            "serve_winrate_debiased": (round(float(debiased), 3) if debiased is not None else None),
            "position_bias_delta": (round(float(pos_bias), 3) if pos_bias is not None else None)}
        print(f"[{iid}]  match median={out['items'][iid]['match_median']} "
              f"mean={out['items'][iid]['match_mean']} n={len(pts)} | serve-vs-gold debiased "
              f"winrate={out['items'][iid]['serve_winrate_debiased']} "
              f"position-bias-delta={out['items'][iid]['position_bias_delta']}")
        fail += [] if len(pts) >= TRIALS else [f"{iid} pointwise n={len(pts)} < {TRIALS}"]
        fail += [] if len(a_first) >= TRIALS else [f"{iid} pairA n={len(a_first)} < {TRIALS}"]
        fail += [] if len(a_second) >= TRIALS else [f"{iid} pairB n={len(a_second)} < {TRIALS}"]

    # easy-case agreement: judge majority vs the deterministic CAL-3 labels (sanity floor, inflated)
    cal3 = json.load(open(args.cal3_results))
    det_label = {r["id"]: r["correct"] for r in cal3["rows"]}
    agree = []
    for iid in easy:
        votes = [1 if v["match"] else 0 for v in by.get(("easy", iid), [])]
        if not votes:
            fail.append(f"{iid} easy-agreement n=0")
            continue
        jl = 1 if sum(votes) * 2 >= len(votes) else 0
        agree.append(1 if jl == det_label[iid] else 0)
    out["easy_agreement"] = {"rate": (round(float(np.mean(agree)), 3) if agree else None),
                             "n": len(agree),
                             "note": "judge vs deterministic labels on easy items — sanity floor, INFLATED by design"}
    print(f"[easy]    judge-vs-deterministic agreement={out['easy_agreement']['rate']} (n={len(agree)})")

    # discretionary judge-vs-HUMAN kappa: N=2 -> unmeasurable, reported as such
    out["discretionary_kappa"] = {"n": len(prose), "value": None,
                                  "verdict": f"UNMEASURABLE at N={len(prose)} (needs more validated prose items)"}
    print(f"[kappa]   discretionary judge-vs-human: N={len(prose)} -> UNMEASURABLE (insufficient prose items)")

    kappa = out["discretionary_kappa"]["value"]
    gain = cal3["selective"].get("gain_pp_raw", cal3["selective"]["gain_pp"])
    actions, arfail = apply_autorevert(kappa, gain)
    out["autorevert"] = actions
    out["autorevert_scope"] = "process-local evidence only; no persistent/live serving-process revoke"
    print(f"[autorevert] kappa={kappa} gain={gain} actions={actions} "
          f"(process-local evidence only)")
    fail += arfail
    fail += [] if not errors else [f"{len(errors)} judge calls failed"]

    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[write]   {args.out}")
    if fail:
        print("CAL4_FAIL:", fail); sys.exit(1)
    print("CAL4_OK")


if __name__ == "__main__":
    main(sys.argv[1:])
