"""H2b-3 (beads cb-hjv.3.2): the DEBIASED-judge harness + drift-τ calibration. CODE ONLY, demoed
with a MOCK biased judge (no paid calls). The real sweep (a non-self-family LLM judge over the
validated golden set) is the SPEND GATE H2b-5 (cb-hjv.3.3).

The §0 debiasing mandate (CONTEXT_EVALS §0, arxiv 2506.06331 / 2306.05685): a naive LLM judge is
corrupted by position bias (>30% win-rate swing on order swap), length bias (a 25-token gap swings
win-rate >50% — judges reward verbose), and trial bias (5 trials give contradictory verdicts).
Debiased, LightRAG-vs-NaiveRAG flips 66.70%→39.06%. So EVERY judge-based metric MUST: (a) average
over both answer orders, (b) length-control, (c) run ≥25 trials reporting median+percentiles,
(d) never judge with the generator's own model family.

The demo builds a mock judge with KNOWN position+length biases and proves the harness removes them.
All numbers are MOCK-judge results, labelled as such. drift-τ is calibrated against a mock
staleness-labeled stream (FLARE θ=0.8 as the prior anchor)."""
import sys
import random
import numpy as np

MIN_TRIALS = 25                      # §0: ≥25 trials (5 is shown to give contradictory verdicts)
LENGTH_GAP_TOKENS = 25               # §0: a ~25-token gap on ~200-token answers swings win-rate >50%


def model_family(model):
    """'gpt-5.4' -> 'gpt', 'claude-opus-4-8' -> 'claude'. Used by the self-family guard."""
    return model.split("-", 1)[0].lower()


def assert_no_self_family(judge_model, generator_model):
    """§0(d): the judge must not share the generator's model family (self-preference bias, G-Eval)."""
    if model_family(judge_model) == model_family(generator_model):
        raise ValueError(f"self-family judge forbidden: judge={judge_model} shares family "
                         f"'{model_family(judge_model)}' with generator={generator_model}")
    return True


def _tokens(s):
    return len(s.split())


def length_confounded(a, b, max_gap=LENGTH_GAP_TOKENS):
    """§0(b): flag a comparison whose answers differ enough in length to trigger length bias."""
    return abs(_tokens(a) - _tokens(b)) > max_gap


def position_swapped_trial(query, a, b, judge_fn):
    """One debiased trial: judge BOTH orders, average A's wins. Returns A-score in {0, 0.5, 1}."""
    win_ab = 1.0 if judge_fn(query, a, b) == "first" else 0.0      # A presented first
    win_ba = 1.0 if judge_fn(query, b, a) == "second" else 0.0     # A presented second
    return (win_ab + win_ba) / 2.0


def judge_sweep(query, a, b, judge_fn, judge_model, generator_model, trials=MIN_TRIALS):
    """The full debiased sweep: self-family guard + position-swap + ≥25 trials + length-control flag.
    Returns median + percentiles of A's debiased win-rate. (judge_fn is a MOCK here.)"""
    assert_no_self_family(judge_model, generator_model)
    if trials < MIN_TRIALS:
        raise ValueError(f"trials={trials} < required {MIN_TRIALS}")
    scores = [position_swapped_trial(query, a, b, judge_fn) for _ in range(trials)]
    arr = np.array(scores)
    return {"n": trials, "median": float(np.median(arr)), "mean": float(arr.mean()),
            "p10": float(np.percentile(arr, 10)), "p90": float(np.percentile(arr, 90)),
            "length_confounded": length_confounded(a, b)}


def naive_winrate(query, a, b, judge_fn, trials=MIN_TRIALS):
    """The BIASED baseline: single fixed order (A always first), no swap — what §0 warns against."""
    return float(np.mean([1.0 if judge_fn(query, a, b) == "first" else 0.0 for _ in range(trials)]))


# ---------- drift-τ calibration (FLARE θ=0.8 anchor) ----------
def calibrate_drift_tau(context_scores, stale_labels):
    """Pick τ so that (score < τ) best predicts 'stale'. Returns (τ, accuracy). FLARE prior θ=0.8."""
    cs, ys = np.array(context_scores), np.array(stale_labels)
    cands = np.linspace(0.1, 0.95, 86)
    accs = [(((cs < t).astype(int)) == ys).mean() for t in cands]
    i = int(np.argmax(accs))
    return float(round(cands[i], 3)), float(accs[i])


def demo():
    fail = []

    # MOCK judge with KNOWN biases: favors (1) the FIRST-presented answer, (2) the LONGER answer.
    def biased_judge(query, first, second):
        rng = random.Random(hash((query, first, second)) & 0xFFFFFFFF)   # stochastic but reproducible
        s_first = 0.01 * _tokens(first) + 0.30 + rng.gauss(0, 0.05)      # +0.30 position bonus to FIRST
        s_second = 0.01 * _tokens(second) + rng.gauss(0, 0.05)
        return "first" if s_first >= s_second else "second"

    # --- POSITION BIAS: two EQUAL-length, equal-quality answers. Truth = tie (~0.5). ---
    a = "owner is the cto agent"
    b = "owner is the cfo agent"   # equal length/quality for this isolation test
    naive = naive_winrate("who owns it", a, b, biased_judge)
    sweep = judge_sweep("who owns it", a, b, biased_judge, judge_model="gpt-5.4",
                        generator_model="claude-opus-4-8")
    print(f"[position] naive(A-first only) A-winrate={naive:.2f}  ->  debiased median={sweep['median']:.2f} "
          f"(p10={sweep['p10']:.2f} p90={sweep['p90']:.2f}, n={sweep['n']})")
    # naive is inflated by the position bonus; debiased collapses toward 0.5
    fail += [] if (naive >= 0.9 and abs(sweep["median"] - 0.5) <= 0.1) else \
        ["position-swap failed to neutralize the first-position bonus"]

    # --- LENGTH BIAS: short good answer vs long verbose answer; harness must FLAG the confound. ---
    short = "cto"
    long_ = "the assigned owner of this engineering issue is the chief technology officer agent " \
            "operating within the engineering namespace of the live paperclip deployment as recorded " \
            "in the current bi-temporal edge set of the company brain knowledge graph store today"
    lc = length_confounded(short, long_)
    print(f"[length]   tokens short={_tokens(short)} long={_tokens(long_)} gap>{LENGTH_GAP_TOKENS} "
          f"-> length_confounded={lc} (harness flags it; real run length-controls)")
    fail += [] if lc else ["length-control must flag a >25-token gap"]

    # --- TRIAL FLOOR: <25 trials is rejected ---
    try:
        judge_sweep("q", a, b, biased_judge, "gpt-5.4", "claude-opus-4-8", trials=5)
        floor_ok = False
    except ValueError:
        floor_ok = True
    print(f"[trials]   <25-trial sweep rejected={floor_ok} (§0: 5 trials give contradictory verdicts)")
    fail += [] if floor_ok else ["must reject <25 trials"]

    # --- NO SELF-FAMILY: a claude judge for a claude generator is rejected ---
    try:
        assert_no_self_family("claude-opus-4-8", "claude-sonnet-4-6")
        self_ok = False
    except ValueError:
        self_ok = True
    cross_ok = assert_no_self_family("gpt-5.4", "claude-opus-4-8")
    print(f"[family]   self-family(claude judging claude) rejected={self_ok} | cross-family(gpt/claude) allowed={cross_ok}")
    fail += [] if (self_ok and cross_ok) else ["self-family guard wrong"]

    # --- DRIFT-τ: calibrate against a mock staleness stream ---
    fresh = [0.93, 0.88, 0.91, 0.85, 0.90]          # fresh contexts score high
    stale = [0.42, 0.55, 0.38, 0.60, 0.50]          # stale contexts score low
    scores = fresh + stale
    labels = [0] * len(fresh) + [1] * len(stale)
    tau, acc = calibrate_drift_tau(scores, labels)
    print(f"[drift-τ]  calibrated τ={tau} accuracy={acc:.2f} (FLARE prior θ=0.8) [MOCK stream]")
    fail += [] if (acc >= 0.9 and 0.6 <= tau <= 0.85) else ["drift-τ calibration off on the mock stream"]

    if fail:
        print("H2B3_FAIL:", fail); sys.exit(1)
    print("H2B3_OK")


if __name__ == "__main__":
    demo()
