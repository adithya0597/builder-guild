"""H2b-1 (beads cb-hjv.3.1): the calibration HARNESS — eRAG per-unit source weights + the
sufficiency×confidence logistic fit. CODE ONLY, demoed on a SYNTHETIC fixture.

This builds what H2b-5 (cb-hjv.3.3, the SPEND GATE) will RUN on the real validated golden set with a
real non-self-family judge. Here the judge/answer functions are MOCKS and the labels are synthetic,
so the demo is $0 and deterministic. It proves the two pieces of machinery work:

  1. eRAG (CONTEXT_EVALS §0/§2, arxiv 2404.13781): feed each retrieved unit ALONE, score its answer
     vs ground truth, and THAT score is the unit's downstream-utility weight — aggregated per source
     (graph vs vector) into source weights. Relevance is NOT used (τ 0.505 downstream vs 0.179 human).
  2. The abstain logistic (§0 finding 2, Sufficient Context): fit W_SUFFICIENCY/W_CONFIDENCE/BIAS on
     (sufficiency, self_confidence)->acted-correctly labels; pick TAU; show selective accuracy BEATS
     a confidence-only gate (the validated +5–10% effect). NEVER sufficiency alone.

It does NOT mutate abstain.py and does NOT flip CALIBRATED — that is the human/spend-gated H2b-5.
All numbers printed here are SYNTHETIC-fixture results, labelled as such; they are not claims about
the real graph.
"""
import sys
import numpy as np


# ---------- 1. eRAG per-unit source-weight calibration ----------
def erag_unit_scores(units, answer_fn, score_fn, gt):
    """For each retrieved unit, generate an answer FROM THAT UNIT ALONE and score it vs GT.
    units: [{"key","source","text"}]. answer_fn(unit)->str. score_fn(answer, gt)->[0,1].
    Returns {key: utility}. (Real run: answer_fn=LLM, score_fn=judge — gated to H2b-5.)"""
    return {u["key"]: float(score_fn(answer_fn(u), gt)) for u in units}


def source_weights(unit_scores, source_of):
    """Aggregate per-unit eRAG utility into per-source weights (mean utility, normalized)."""
    by_src = {}
    for k, s in unit_scores.items():
        by_src.setdefault(source_of[k], []).append(s)
    means = {src: float(np.mean(v)) for src, v in by_src.items()}
    tot = sum(means.values()) or 1.0
    return {src: round(m / tot, 4) for src, m in means.items()}, {src: round(m, 4) for src, m in means.items()}


# ---------- 2. sufficiency × confidence logistic fit ----------
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(X, y, lr=0.3, epochs=4000, l2=1e-3):
    """Plain-numpy logistic regression (no sklearn). X: (n,2) [sufficiency, confidence]. y: (n,).
    Returns (w_suff, w_conf, bias). Gradient descent; deterministic init (zeros)."""
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        z = X @ w + b
        p = _sigmoid(z)
        err = p - y
        w -= lr * (X.T @ err / n + l2 * w)
        b -= lr * float(np.mean(err))
    return float(w[0]), float(w[1]), float(b)


def best_threshold(scores, y):
    """Pick TAU maximizing accuracy of (score>=tau)==act-correct over candidate thresholds."""
    cands = np.linspace(0.05, 0.95, 91)
    accs = [((scores >= t).astype(int) == y).mean() for t in cands]
    i = int(np.argmax(accs))
    return float(cands[i]), float(accs[i])


def synthetic_fixture():
    """Deterministic fixture reproducing the §0 phenomenon: 'should-act' depends MORE on sufficiency
    than confidence, and there is an overconfident low-sufficiency band (LLMs answer 35–62% correct on
    insufficient context). A confidence-only gate cannot separate that band; the combined gate can.
    No RNG — a fixed (suff,conf) grid with a deterministic labeling rule + a fixed overconfident band."""
    suff_grid = [0.1, 0.3, 0.5, 0.7, 0.9]
    conf_grid = [0.1, 0.3, 0.5, 0.7, 0.9]
    X, y = [], []
    for s in suff_grid:
        for c in conf_grid:
            reps = 8
            # true P(acting is correct): sufficiency-dominant
            p = _sigmoid(3.0 * s + 1.0 * c - 1.8)
            n_pos = int(round(p * reps))
            # overconfident band: low sufficiency (<=0.3) + high confidence (>=0.7) => acting usually WRONG
            if s <= 0.3 and c >= 0.7:
                n_pos = 1   # confidence says "act"; truth says mostly don't
            for r in range(reps):
                X.append([s, c]); y.append(1 if r < n_pos else 0)
    return np.array(X, dtype=float), np.array(y, dtype=int)


def demo():
    fail = []

    # ---- eRAG: mock answer/judge, deterministic. graph units answer better than vector units. ----
    units = [{"key": "issue:SPI-2", "source": "graph", "text": "rate-limit backoff; ASSIGNED_TO cto"},
             {"key": "issue:SPI-3", "source": "graph", "text": "node-card prepared cypher"},
             {"key": "issue:SPI-6", "source": "vector", "text": "positioning launch messaging"},
             {"key": "issue:SPI-7", "source": "vector", "text": "retrieval-ladder UX"}]
    gt = "cto"
    answer_fn = lambda u: ("cto" if "cto" in u["text"] else "unknown")      # mock generator
    score_fn = lambda a, g: 1.0 if a == g else 0.2                          # mock judge
    us = erag_unit_scores(units, answer_fn, score_fn, gt)
    source_of = {u["key"]: u["source"] for u in units}
    wts, means = source_weights(us, source_of)
    print(f"[eRAG]    per-unit utility={us}")
    print(f"[eRAG]    source means={means} -> normalized weights={wts}")
    fail += [] if (wts.get("graph", 0) > wts.get("vector", 0)) else ["eRAG should weight graph(fact) > vector(recall) on this fixture"]

    # ---- logistic fit on the synthetic fixture ----
    X, y = synthetic_fixture()
    w_s, w_c, b = fit_logistic(X, y)
    print(f"[fit]     W_SUFFICIENCY={w_s:.3f} W_CONFIDENCE={w_c:.3f} BIAS={b:.3f}  (n={len(y)})")
    fail += [] if (w_s > w_c) else ["fit should learn sufficiency-dominant weights on this fixture"]

    # combined selective gate
    combined = _sigmoid(X @ np.array([w_s, w_c]) + b)
    tau, comb_acc = best_threshold(combined, y)
    # confidence-only gate (best threshold on confidence alone) — the baseline §0 says we must beat
    conf_only = X[:, 1]
    _, conf_acc = best_threshold(conf_only, y)
    gain_pp = round((comb_acc - conf_acc) * 100, 2)
    print(f"[select]  TAU={tau:.3f}  combined_acc={comb_acc:.3f}  confidence_only_acc={conf_acc:.3f}  "
          f"gain=+{gain_pp}pp  [SYNTHETIC fixture]")
    # §0 validated effect is +5–10pp; assert the mechanism reproduces a POSITIVE gain (not the exact magnitude)
    fail += [] if gain_pp > 0 else ["combined gate must beat confidence-only (the §0 selective-accuracy effect)"]

    # ---- guardrails: did NOT touch abstain.py's calibration state ----
    import abstain
    untouched = (abstain.CALIBRATED is False and abstain.W_SUFFICIENCY == 2.0 and abstain.TAU == 0.5)
    print(f"[gate]    abstain.CALIBRATED={abstain.CALIBRATED} (untouched={untouched}) — flip is H2b-5, not here")
    fail += [] if untouched else ["H2b-1 must NOT flip CALIBRATED or mutate abstain weights"]

    if fail:
        print("H2B1_FAIL:", fail); sys.exit(1)
    print("H2B1_OK")


if __name__ == "__main__":
    demo()
