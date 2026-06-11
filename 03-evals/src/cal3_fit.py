"""CAL-3 (beads cb-hjv.3.3.3): REAL logistic fit — serve() traces x human golden labels.

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
import json
import os
import sys
import numpy as np
from golden import read_golden
from serve import serve
from h2b1_calib import fit_logistic, _sigmoid
from judge_hermes import score_match

HERE = os.path.dirname(os.path.abspath(__file__))
LOSS_WRONG_ACT, LOSS_MISSED_ACT = 10.0, 1.0          # founder-locked 2026-06-10


def answer_text(r):
    """The full ANSWER surface: primary + presentable facts + the composed evidence channel
    (R1+R2 cb-s36: content + multi-card facts — what a consumer actually reads)."""
    return (f"{r.get('primary', '')} | " + " ; ".join(r.get("presentable_facts", []))
            + " ; " + " ; ".join(r.get("composed_evidence", [])))


def support_nodes(item):
    keys = set()
    for f in item["support_facts"]:
        keys.add(f) if isinstance(f, str) else keys.update((f[0], f[2]))
    return keys


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
    if gold in ("agent:cto", "agent:cfo", "in_progress"):            # ID/enum golds
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


def main():
    fail = []
    items = read_golden(os.path.join(HERE, "example_golden.jsonl"))
    ckpt = os.path.join(HERE, "cal3_judge.jsonl")
    rows = []
    for it in items:
        r = serve(it["question"], it["role"])
        ga = r.get("trace", {}).get("gate_abstain", {})
        suff, conf = float(ga.get("sufficiency", 0.0)), float(ga.get("self_confidence", 0.0))
        correct, how = label_correct(it, r, ckpt)
        rows.append({"id": it["id"], "suff": suff, "conf": conf, "decision": r.get("decision"),
                     "correct": correct, "how": how, "answer": answer_text(r)[:90]})
        print(f"  {it['id']:11} suff={suff:.2f} conf={conf:.2f} serve={r.get('decision'):8} "
              f"correct={correct} via {how}")

    X = np.array([[r["suff"], r["conf"]] for r in rows])
    y = np.array([r["correct"] for r in rows])
    w_s, w_c, b = fit_logistic(X, y)
    scores = _sigmoid(X @ np.array([w_s, w_c]) + b)
    print(f"\n[fit]     REAL-trace logistic: W_SUFFICIENCY={w_s:.3f} W_CONFIDENCE={w_c:.3f} "
          f"BIAS={b:.3f} (n={len(y)}, base-rate correct={y.mean():.2f})")

    taus = np.linspace(0.05, 0.95, 91)
    tau_acc = float(taus[int(np.argmax([selective_accuracy(scores, y, t) for t in taus]))])
    comb = selective_accuracy(scores, y, tau_acc)
    conf_only = X[:, 1]
    conf_acc = max(selective_accuracy(conf_only, y, t) for t in taus)
    gain = round((comb - conf_acc) * 100, 1)
    print(f"[select]  combined acc={comb:.2f} @tau={tau_acc:.2f} | confidence-only acc={conf_acc:.2f} "
          f"| gain={gain:+.1f}pp  [N=10 SMOKE]")

    losses = [expected_loss(scores, y, t) for t in taus]
    tau_star = float(taus[int(np.argmin(losses))])
    act = scores >= tau_star
    wrong_act = int((act & (y == 0)).sum()); missed = int((~act & (y == 1)).sum())
    print(f"[loss10:1] TAU*={tau_star:.2f} -> acts={int(act.sum())}/{len(y)} wrong-acts={wrong_act} "
          f"missed-correct={missed} expected-loss={min(losses):.0f}")

    import abstain
    untouched = abstain.CALIBRATED is False and abstain.W_SUFFICIENCY == 2.0
    print(f"[gate]    abstain.CALIBRATED={abstain.CALIBRATED} untouched={untouched} (founder flips, not this)")
    fail += [] if untouched else ["CAL-3 must not mutate abstain.py"]
    fail += [] if wrong_act == 0 else [f"TAU* under 10:1 must zero wrong-acts on this slice (got {wrong_act})"]

    out = {"rows": rows, "fit": {"W_SUFFICIENCY": w_s, "W_CONFIDENCE": w_c, "BIAS": b},
           "selective": {"combined_acc": comb, "tau_acc": tau_acc, "confidence_only_acc": conf_acc,
                         "gain_pp": gain},
           "loss_10_1": {"tau_star": tau_star, "acts": int(act.sum()), "wrong_acts": wrong_act,
                         "missed_correct": missed},
           "caveat": "N=10 smoke; weights NOT written to abstain.py; CALIBRATED untouched"}
    with open(os.path.join(HERE, "cal3_fit_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("[write]   cal3_fit_results.json")

    if fail:
        print("CAL3_FAIL:", fail); sys.exit(1)
    print("CAL3_OK")


if __name__ == "__main__":
    main()
