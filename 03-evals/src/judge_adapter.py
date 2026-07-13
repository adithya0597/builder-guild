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
import shutil
import subprocess
import sys
import time

from h2b3_judge import assert_no_self_family

JUDGE_CMD = os.path.expanduser(os.environ.get("JUDGE_CMD", "judge-cli"))   # e.g. a codex-style one-shot CLI
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-5.4")
GENERATOR_MODEL = "claude-opus-4-8"          # the Claude family that authored answers/drafts
assert_no_self_family(JUDGE_MODEL, GENERATOR_MODEL)


def judge_available():
    return shutil.which(JUDGE_CMD) is not None


def _is_auth_payment_error(out):
    # Match the sibling $0-or-STOP guards (ocr_adapter.py:32, web_fallback_adapter.py:32) so all
    # three fire on the same signals — "auth" also covers authentication/authorization/unauthorized.
    return bool(re.search(r"auth|api[ _-]?key|payment|billing|quota", out, re.I))


_sentinel_warned = False


def _unscored(kind, reason):
    rec = {"unscored": True, "reason": reason}
    if kind == "match":
        rec["match"] = None
    elif kind == "winner":
        rec["winner"] = None
    return rec


def is_unscored(verdict):
    return (isinstance(verdict, dict)
            and (verdict.get("unscored") is True
                 or ("match" in verdict and verdict["match"] is None)
                 or ("winner" in verdict and verdict["winner"] is None)))


def _warn_sentinel_once(reason):
    global _sentinel_warned
    if not _sentinel_warned:
        print(f"[judge_adapter] JUDGE_CMD={JUDGE_CMD!r} unavailable/malformed — degrading to an "
              f"unscored sentinel ({reason}; no crash, but this item is NOT judged)",
              file=sys.stderr)
        _sentinel_warned = True


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
            if _is_auth_payment_error(out):     # auth/payment STOP takes precedence over returncode
                raise RuntimeError(f"AUTH/PAYMENT prompt from the judge CLI — STOP, do not fall back: {out[:200]}")
            if p.returncode != 0:               # present-but-broken judge: don't trust its stdout as a verdict
                last = f"nonzero returncode {p.returncode}: {out[-200:]}"
            else:
                for m in reversed(_JSON_RE.findall(out)):   # last JSON object wins
                    try:
                        return json.loads(m), round(time.time() - t0, 1)
                    except json.JSONDecodeError:
                        continue
                last = f"no parseable JSON in: {out[-200:]}"
        except subprocess.TimeoutExpired:
            last = f"timeout {timeout}s"
        except (FileNotFoundError, OSError) as e:
            raise RuntimeError(f"judge CLI not executable ({JUDGE_CMD}): {e}") from e
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
    if not judge_available():
        reason = "judge_cmd_not_found"
        _warn_sentinel_once(reason)
        return _unscored("match", reason), 0.0
    prompt = (f'You are a strict evaluation judge. Question: "{question}" '
              f'Gold answer: "{gold}". Candidate answer: "{candidate}". '
              f'Does the candidate convey the same answer as the gold (semantically, '
              f'ignoring phrasing)? Reply with ONLY compact JSON: '
              f'{{"match": true|false, "confidence": 0.0-1.0}}')
    try:
        verdict, lat = _call(prompt)
    except RuntimeError as e:
        if str(e).startswith("AUTH/PAYMENT"):
            raise
        reason = f"judge_malfunction:{e}"
        _warn_sentinel_once(reason)
        return _unscored("match", reason), 0.0
    if not isinstance(verdict.get("match"), bool):
        reason = f"malformed_match_verdict:{verdict}"
        _warn_sentinel_once(reason)
        return _unscored("match", reason), 0.0
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
    if not judge_available():
        reason = "judge_cmd_not_found"
        _warn_sentinel_once(reason)
        return _unscored("winner", reason), 0.0
    prompt = (f'You are a strict evaluation judge. Question: "{question}" '
              f'Answer A: "{first}" Answer B: "{second}". '
              f'Which answer is more correct and complete? Reply ONLY compact JSON: '
              f'{{"winner": "first"|"second"}}')
    try:
        verdict, lat = _call(prompt)
    except RuntimeError as e:
        if str(e).startswith("AUTH/PAYMENT"):
            raise
        reason = f"judge_malfunction:{e}"
        _warn_sentinel_once(reason)
        return _unscored("winner", reason), 0.0
    if verdict.get("winner") not in ("first", "second"):
        reason = f"malformed_pair_verdict:{verdict}"
        _warn_sentinel_once(reason)
        return _unscored("winner", reason), 0.0
    if ckpt and key:
        _checkpoint(ckpt, key, verdict, lat)
    return verdict, lat


def smoke():
    """CAL-1 acceptance: 1 real call parses + checkpoint round-trips.
    Degrades to CAL1_SKIP (exit 0) when the judge CLI isn't installed — no crash."""
    if not judge_available():
        print(f"[smoke]   JUDGE_CMD={JUDGE_CMD!r} not found — skipping the real judge call")
        print("CAL1_SKIP")
        return
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


def _selftest_stop():
    """Pure-function STOP-contract guard — runs even on the CAL1_SKIP path (judge absent), so CI's
    `JUDGE_CMD=/nonexistent ... judge_adapter.py` smoke job enforces both holes for free.
    (bead 9if only tested the 4 phrasings the old regex already matched, never the contract.)"""
    for s in ("authentication required", "unauthorized 401", "api key required",
              "payment", "quota exceeded", "billing"):
        assert _is_auth_payment_error(s), f"auth-STOP regex missed {s!r} — would degrade to a sentinel"
    assert not _is_auth_payment_error('{"match": true}'), "auth-STOP regex false-positive on a clean verdict"

    # defect 2: a present-but-broken judge (returncode!=0) with parseable stdout must NOT be trusted.
    orig_run, orig_sleep = subprocess.run, time.sleep
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, '{"match": true}', "")
    time.sleep = lambda *a, **k: None
    try:
        broke = False
        try:
            _call("x", retries=1)
        except RuntimeError:
            broke = True
        assert broke, "broken judge (returncode=1) accepted as a real verdict"
    finally:
        subprocess.run, time.sleep = orig_run, orig_sleep


if __name__ == "__main__":
    _selftest_stop()
    smoke()
