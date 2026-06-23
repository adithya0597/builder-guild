"""CAL-1: the REAL judge adapter — an external judge CLI (env JUDGE_CMD/JUDGE_MODEL).

Wraps one-shot `$JUDGE_CMD -z <prompt> -m $JUDGE_MODEL` as the non-self-family judge for the V0 calibration.
Strict-JSON prompts, parse-with-retry + exponential backoff, EVERY verdict checkpointed to disk
(resume = skip already-judged keys), per-call latency logged (the 19.0/33.1s n=2 baseline needs
re-basing on a real sample). Self-family guard reused from h2b3_judge (judge gpt-5.4 vs generator
claude family). $0 path: Codex OAuth subscription — if the judge CLI ever errors with an auth/payment
prompt, the caller must STOP, not fall back to a paid key."""
import json
import os
import re
import subprocess
import time

from h2b3_judge import assert_no_self_family

JUDGE_CMD = os.path.expanduser(os.environ.get("JUDGE_CMD", "judge-cli"))   # e.g. a codex-style one-shot CLI
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-5.4")
GENERATOR_MODEL = "claude-opus-4-8"          # the Claude family that authored answers/drafts
assert_no_self_family(JUDGE_MODEL, GENERATOR_MODEL)

_JSON_RE = re.compile(r"\{[^{}]*\}")


def _call(prompt, retries=3, timeout=180):
    """One judge CLI call -> (parsed_json, latency_s). Exponential backoff on failure."""
    last = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            p = subprocess.run([JUDGE_CMD, "-z", prompt, "-m", JUDGE_MODEL],
                               capture_output=True, text=True, timeout=timeout)
            out = (p.stdout or "") + (p.stderr or "")
            if re.search(r"payment|api key required|quota exceeded|billing", out, re.I):
                raise RuntimeError(f"AUTH/PAYMENT prompt from the judge CLI — STOP, do not fall back: {out[:200]}")
            for m in reversed(_JSON_RE.findall(out)):       # last JSON object wins
                try:
                    return json.loads(m), round(time.time() - t0, 1)
                except json.JSONDecodeError:
                    continue
            last = f"no parseable JSON in: {out[-200:]}"
        except subprocess.TimeoutExpired:
            last = f"timeout {timeout}s"
        time.sleep((2 ** attempt) * 5)
    raise RuntimeError(f"judge call failed after {retries} attempts: {last}")


def load_checkpoint(path):
    if not os.path.exists(path):
        return {}
    done = {}
    with open(path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                done[rec["key"]] = rec
    return done


def _checkpoint(path, key, verdict, latency):
    with open(path, "a") as f:
        f.write(json.dumps({"key": key, "verdict": verdict, "latency_s": latency}) + "\n")


def score_match(question, candidate, gold, key=None, ckpt=None):
    """Pointwise: does candidate answer match gold for this question? -> {match, confidence}.
    Checkpointed by `key` when ckpt path given (resume-safe)."""
    if ckpt and key:
        done = load_checkpoint(ckpt)
        if key in done:
            return done[key]["verdict"], 0.0
    prompt = (f'You are a strict evaluation judge. Question: "{question}" '
              f'Gold answer: "{gold}". Candidate answer: "{candidate}". '
              f'Does the candidate convey the same answer as the gold (semantically, '
              f'ignoring phrasing)? Reply with ONLY compact JSON: '
              f'{{"match": true|false, "confidence": 0.0-1.0}}')
    verdict, lat = _call(prompt)
    if not isinstance(verdict.get("match"), bool):
        raise RuntimeError(f"malformed verdict: {verdict}")
    if ckpt and key:
        _checkpoint(ckpt, key, verdict, lat)
    return verdict, lat


def judge_pair(question, first, second, key=None, ckpt=None):
    """Pairwise: which of two answers is better for the question? -> {winner: first|second}.
    Position bias is the caller's problem (call both orders, per h2b3.position_swapped_trial)."""
    if ckpt and key:
        done = load_checkpoint(ckpt)
        if key in done:
            return done[key]["verdict"], 0.0
    prompt = (f'You are a strict evaluation judge. Question: "{question}" '
              f'Answer A: "{first}" Answer B: "{second}". '
              f'Which answer is more correct and complete? Reply ONLY compact JSON: '
              f'{{"winner": "first"|"second"}}')
    verdict, lat = _call(prompt)
    if verdict.get("winner") not in ("first", "second"):
        raise RuntimeError(f"malformed pair verdict: {verdict}")
    if ckpt and key:
        _checkpoint(ckpt, key, verdict, lat)
    return verdict, lat


def smoke():
    """CAL-1 acceptance: 1 real call parses + checkpoint round-trips."""
    import sys
    ck = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cal1_smoke.jsonl")
    if os.path.exists(ck):
        os.remove(ck)
    v, lat = score_match("Who is issue SPI-2 assigned to?", "the CTO agent", "agent:cto",
                         key="smoke-1", ckpt=ck)
    print(f"[smoke]   verdict={v} latency={lat}s")
    ok_call = isinstance(v.get("match"), bool) and 0.0 <= v.get("confidence", -1) <= 1.0
    # resume path: same key returns from checkpoint with no second judge call (latency 0)
    v2, lat2 = score_match("Who is issue SPI-2 assigned to?", "the CTO agent", "agent:cto",
                           key="smoke-1", ckpt=ck)
    print(f"[resume]  cached verdict={v2} latency={lat2}s (must be 0.0 = no re-call)")
    ok_resume = v2 == v and lat2 == 0.0
    if ok_call and ok_resume:
        print("CAL1_OK")
    else:
        print(f"CAL1_FAIL: call={ok_call} resume={ok_resume}"); sys.exit(1)


if __name__ == "__main__":
    smoke()
