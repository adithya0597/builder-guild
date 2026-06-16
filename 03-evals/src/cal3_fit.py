"""CAL-3 (G3): REAL logistic fit — serve() traces x human golden labels.

For each of the 10 validated golden items: run the live serve(question, role), pull the gate's
own (sufficiency, self_confidence) from its trace, and label whether serve's answer was CORRECT
vs the human gold — deterministic-first (ID/enum/set/abstain matchers), hermes judge (3-trial
majority) ONLY for the 2 prose items. Fit the sufficiency x confidence logistic on those REAL
(signal, signal, correct) rows; report selective accuracy vs the confidence-only baseline; derive
TAU* under the FOUNDER-LOCKED loss ratio C(wrong act):C(missed act) = 10:1 (routine actions;
irreversible/security remain categorically human-gated in gate.py and lease no autonomy).

DOES NOT FLIP CALIBRATED (governance: founder flips, V0 flips nothing). Fitted weights go to the
evidence packet, not abstain.py. N=10 — every number below is a SMOKE-scale measurement.
"""
import argparse
import json
import os
import sys
import numpy as np

# 01-context/src must be on path (mirroring eval_corrective.py convention)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "01-context", "src"))

from golden import read_golden
from serve import serve
from h2b1_calib import fit_logistic, _sigmoid
from judge_adapter import score_match

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLDEN_PATH = os.path.join(HERE, "..", "example_golden.jsonl")
DEFAULT_JUDGE_CKPT = os.path.join(HERE, "cal3_judge.jsonl")
DEFAULT_RESULTS_PATH = os.path.join(HERE, "cal3_fit_results.json")
LOSS_WRONG_ACT, LOSS_MISSED_ACT = 10.0, 1.0          # founder-locked 2026-06-10


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fit the CAL-3 sufficiency×confidence logistic on a golden set.")
    p.add_argument("--golden", default=DEFAULT_GOLDEN_PATH,
                   help="Path to a validated golden JSONL file. Defaults to the public example set.")
    p.add_argument("--judge-ckpt", default=DEFAULT_JUDGE_CKPT,
                   help="Path to the judge checkpoint JSONL file.")
    p.add_argument("--out", default=DEFAULT_RESULTS_PATH,
                   help="Path to write cal3_fit_results.json.")
    return p.parse_args(argv)


def answer_text(r):
    """The full ANSWER surface: primary + presentable facts + the composed evidence channel
    (R1+R2: content + multi-card facts — what a consumer actually reads)."""
    return (f"{r.get('primary', '')} | " + " ; ".join(r.get("presentable_facts", []))
            + " ; " + " ; ".join(r.get("composed_evidence", [])))


def support_nodes(item):
    keys = set()
    for f in item["support_facts"]:
        keys.add(f) if isinstance(f, str) else keys.update((f[0], f[2]))
    return keys


def _is_exact_gold(gold):
    """True when a gold answer is exact-matchable (an entity key like 'agent:cto'/'issue:SPI-3'
    or a status enum like 'todo'), vs free-form prose that needs the judge. Generalizes the old
    hardcoded ('agent:cto','agent:cfo','in_progress') list — which fit only the ACME public
    example — to the full spine namespace. §0: deterministic facts are settled deterministically,
    never judged."""
    g = str(gold).strip()
    if ":" in g:
        pre, post = g.split(":", 1)
        if pre.lower() in {"agent", "issue", "status", "project", "repo", "extsrc"} and " " not in post.strip():
            return True
    return g.lower() in {"todo", "in_progress", "blocked", "done", "open", "closed",
                         "in_review", "cancelled", "backlog"}


def label_correct(item, r, ckpt):
    """Deterministic-first correctness of serve's answer vs the human gold."""
    gold = item["correct_answer"]
    dec = r.get("decision")
    if item["expected_decision"] == "abstain":                       # abstain golds
        return (1 if dec in ("abstain", "escalate") else 0), "deterministic:abstain"
    if dec not in ("pass", "partial"):
        return 0, "deterministic:no-answer"
    text = answer_text(r)
    if isinstance(gold, list):                                       # set golds
        return (1 if all(g in text or g == r.get("primary") for g in gold) else 0), "deterministic:set"
    if _is_exact_gold(gold):                                         # entity-key / status-enum golds
        ok = gold in text and r.get("primary") in support_nodes(item)
        return (1 if ok else 0), "deterministic:id"
    votes = []                                                       # prose golds -> judge, 3 trials
    for t in range(3):
        v, _ = score_match(item["question"], text, gold, key=f"cal3:{item['id']}:t{t}", ckpt=ckpt)
        votes.append(1 if v["match"] else 0)
    return (1 if sum(votes) >= 2 else 0), f"judge:3trial(votes={sum(votes)})"


def selective_accuracy(scores, y, tau):
    act = scores >= tau
    return float(((act & (y == 1)) | (~act & (y == 0))).mean())


def expected_loss(scores, y, tau):
    act = scores >= tau
    return float(LOSS_WRONG_ACT * (act & (y == 0)).sum() + LOSS_MISSED_ACT * (~act & (y == 1)).sum())


def main(argv=None):
    args = parse_args(argv)
    fail = []
    items = read_golden(args.golden)
    ckpt = args.judge_ckpt
    rows = []
    for it in items:
        r = serve(it["question"], it["role"])
        ga = r.get("trace", {}).get("gate_abstain", {})
        suff, conf = float(ga.get("sufficiency", 0.0)), float(ga.get("self_confidence", 0.0))
        correct, how = label_correct(it, r, ckpt)
        rows.append({"id": it["id"], "suff": suff, "conf": conf, "decision": r.get("decision"),
                     "expected": it["expected_decision"],
                     "correct": correct, "how": how, "answer": answer_text(r)[:90]})
        print(f"  {it['id']:11} suff={suff:.2f} conf={conf:.2f} serve={r.get('decision'):8} "
              f"correct={correct} via {how}")

    print(f"[input]   golden={args.golden} judge_ckpt={ckpt}")
    X = np.array([[r["suff"], r["conf"]] for r in rows])
    y = np.array([r["correct"] for r in rows])
    # DECISION-CHANNEL target: the gate should ACT iff acting yields a correct outcome — i.e. the
    # item is pass-expected AND serve answered correctly. Abstain-expected items (and pass-expected
    # items serve got wrong) are SHOULD-WITHHOLD. Optimizing against `correct` alone wrongly rewarded
    # ACTING on correctly-abstained items (they are correct, but acting on them is wrong), which
    # collapsed TAU*. The item-3 decision channel is now carried through the FIT + loss + search,
    # not just the label.
    should_act = np.array([1 if (r["expected"] == "pass" and r["correct"] == 1) else 0 for r in rows])
    w_s, w_c, b = fit_logistic(X, should_act)
    scores = _sigmoid(X @ np.array([w_s, w_c]) + b)
    print(f"\n[fit]     decision-channel logistic: W_SUFFICIENCY={w_s:.3f} W_CONFIDENCE={w_c:.3f} "
          f"BIAS={b:.3f} (n={len(should_act)}, correct base-rate={y.mean():.2f}, "
          f"act-target base-rate={should_act.mean():.2f})")

    taus = np.linspace(0.05, 0.95, 91)
    tau_acc = float(taus[int(np.argmax([selective_accuracy(scores, should_act, t) for t in taus]))])
    comb = selective_accuracy(scores, should_act, tau_acc)
    conf_only = X[:, 1]
    conf_acc = max(selective_accuracy(conf_only, should_act, t) for t in taus)
    gain = round((comb - conf_acc) * 100, 1)
    print(f"[select]  combined acc={comb:.2f} @tau={tau_acc:.2f} | confidence-only acc={conf_acc:.2f} "
          f"| gain={gain:+.1f}pp  [n={len(should_act)}]")

    losses = [expected_loss(scores, should_act, t) for t in taus]
    tau_star = float(taus[int(np.argmin(losses))])
    act = scores >= tau_star
    wrong_act = int((act & (should_act == 0)).sum()); missed = int((~act & (should_act == 1)).sum())
    print(f"[loss10:1] TAU*={tau_star:.2f} -> acts={int(act.sum())}/{len(should_act)} wrong-acts={wrong_act} "
          f"missed-act={missed} expected-loss={min(losses):.0f}")

    import abstain
    # CALIBRATED is now a dict; must-not-flip guard: all namespaces remain False
    all_false = isinstance(abstain.CALIBRATED, dict) and all(v is False for v in abstain.CALIBRATED.values())
    untouched = all_false and abstain.W_SUFFICIENCY == 2.0
    print(f"[gate]    abstain.CALIBRATED={abstain.CALIBRATED} all_false={all_false} untouched={untouched} "
          f"(founder flips, not this)")
    fail += [] if untouched else ["CAL-3 must not mutate abstain.py"]
    fail += [] if wrong_act == 0 else [f"TAU* under 10:1 must zero wrong-acts on this slice (got {wrong_act})"]

    out = {"rows": rows, "fit": {"W_SUFFICIENCY": w_s, "W_CONFIDENCE": w_c, "BIAS": b},
           "selective": {"combined_acc": comb, "tau_acc": tau_acc, "confidence_only_acc": conf_acc,
                         "gain_pp": gain},
           "loss_10_1": {"tau_star": tau_star, "acts": int(act.sum()), "wrong_acts": wrong_act,
                         "missed_act": missed},
           "target": "should_act = (expected=='pass') AND serve_correct (decision channel)",
           "caveat": f"n={len(should_act)}; weights NOT written to abstain.py; CALIBRATED dict all False (untouched)"}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[write]   {args.out}")

    if fail:
        print("CAL3_FAIL:", fail); sys.exit(1)
    print("CAL3_OK")


if __name__ == "__main__":
    main(sys.argv[1:])
