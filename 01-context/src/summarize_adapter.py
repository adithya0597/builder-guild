"""Pluggable $0-or-STOP summary adapter (GraphRAG communities).

Mirrors judge_adapter.py BUT:
  - env read at CALL TIME, not import time (so tests can swap env per-call)
  - uses a broad STOP regex: auth|api[ _-]?key|payment|billing|quota (case-insensitive)
  - SUMMARY_CMD unset => detection-only mode (no call, returns None)
  - input = in-namespace member short_context + intra-community fact names ONLY
    (build-time isolation: adapter never sees another namespace)

SUMMARY_CMD unset => caller runs detection-only (communities written, summaries skipped).
Any output matching the STOP regex raises RuntimeError immediately — no silent pay.
"""
import json
import os
import re
import subprocess
import time

# SUMMARY_CMD / SUMMARY_MODEL are read at CALL TIME inside _cmd(), never at import — so callers and
# tests set them per-call (the sibling adapter's import-time capture was a real bug). There is NO
# module-level model global (codex review GraphRAG communities MED: a `None` global was misread as the active
# model and stamped 'unknown' on every summarized write).

# STOP regex: matches auth, api_key, api-key, api key, payment, billing, quota
_STOP_RE = re.compile(r"auth|api[ _-]?key|payment|billing|quota", re.IGNORECASE)

_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def _cmd():
    """Read SUMMARY_CMD and SUMMARY_MODEL from env at call time."""
    cmd = os.environ.get("SUMMARY_CMD")
    model = os.environ.get("SUMMARY_MODEL", "")
    return cmd, model


def _call(prompt, cmd, model, timeout=120, retries=2):
    """One CLI call -> text output.  Raises RuntimeError on STOP trigger or repeated failure."""
    last = None
    args = [cmd, "-z", prompt]
    if model:
        args += ["-m", model]

    for attempt in range(retries):
        t0 = time.time()
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            out = (p.stdout or "") + (p.stderr or "")

            if _STOP_RE.search(out):
                raise RuntimeError(
                    f"AUTH/PAYMENT/QUOTA keyword in summary CLI output — STOP, do not fall back: {out[:300]}"
                )

            # Accept JSON-fenced or bare text
            m = _JSON_FENCE_RE.search(out)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                    return parsed.get("summary", str(parsed))
                except json.JSONDecodeError:
                    pass
            text = out.strip()
            if text:
                return text
            last = "empty output"
        except subprocess.TimeoutExpired:
            last = f"timeout {timeout}s"
        time.sleep((2 ** attempt) * 3)

    raise RuntimeError(f"summary call failed after {retries} attempts: {last}")


def load_checkpoint(path):
    """Load already-summarized keys from a JSONL checkpoint file."""
    if not os.path.exists(path):
        return {}
    done = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    done[rec["key"]] = rec
                except (json.JSONDecodeError, KeyError):
                    pass
    return done


def _checkpoint(path, key, summary):
    """Append one summary record to the JSONL checkpoint."""
    with open(path, "a") as f:
        f.write(json.dumps({"key": key, "summary": summary}) + "\n")


def summarize(member_texts, fact_lines, *, key=None, ckpt=None):
    """Summarize a community from its in-namespace member texts + intra-community fact names.

    CALL-TIME env read: SUMMARY_CMD / SUMMARY_MODEL are read HERE, not at import.
    SUMMARY_CMD unset => returns None (detection-only mode, no model call).
    Any STOP keyword in CLI output => RuntimeError (no silent pay).

    Args:
        member_texts: list[str] — in-namespace member short_context values
        fact_lines:   list[str] — intra-community fact name strings (e.g. "BLOCKS -> issue:X")
        key:          optional string — checkpoint key (community key)
        ckpt:         optional path — JSONL checkpoint file path

    Returns:
        str summary, or None if SUMMARY_CMD is unset.

    Raises:
        RuntimeError if STOP keyword detected or CLI repeatedly fails.
    """
    cmd, model = _cmd()  # env read at call time

    if not cmd:
        # Detection-only mode
        return None

    # Checkpoint resume
    if ckpt and key:
        done = load_checkpoint(ckpt)
        if key in done:
            return done[key]["summary"]

    # Build prompt from in-namespace data ONLY
    members_section = "\n".join(f"- {t}" for t in member_texts) if member_texts else "(none)"
    facts_section = "\n".join(f"- {f}" for f in fact_lines) if fact_lines else "(none)"
    prompt = (
        "You are a knowledge-graph summarizer. Summarize this knowledge-graph community "
        "in one concise paragraph (≤80 words). Use only the provided members and facts.\n\n"
        f"Members:\n{members_section}\n\nIntra-community facts:\n{facts_section}\n\n"
        'Reply with compact JSON: {"summary": "<text>"}'
    )

    summary = _call(prompt, cmd, model)

    if ckpt and key:
        _checkpoint(ckpt, key, summary)

    return summary
