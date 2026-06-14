"""Corrective-RAG web fallback adapter (Corrective-RAG §5).

Pluggable $0-or-STOP web branch. OFF by default. Mirrors judge_adapter.py.

Environment:
    CORRECTIVE_WEB_ENABLED   default "false" — must be "true" to activate
    CORRECTIVE_WEB_CMD       the one-shot CLI (e.g. a hermes/codex-style CLI)
    CORRECTIVE_WEB_MODEL     model to pass to the CLI

One-shot: $CMD -z <prompt> -m $MODEL
Expected stdout: strict JSON list [{"fact": ..., "source": ...}, ...]

$0-or-STOP: if stdout/stderr matches payment|api key required|quota exceeded|billing
    -> raise RuntimeError (STOP; do NOT fall back to a paid path)

Default path ($0/local): web OFF -> after local tactics exhaust -> return abstain
result annotated resolved_at="exhausted". This is the normal flow when this adapter
is not explicitly enabled.

Returned facts become claims with provenance="web", lower authority than graph/keyword.
Only invoked when web_fallback=True in corrective_serve() AND CORRECTIVE_WEB_ENABLED=true.
"""
import json
import os
import re
import subprocess
import time

# Broadened to fail-closed on ANY auth/key/payment/billing/quota signal — better to STOP
# too eagerly than to silently pay (codex review Corrective-RAG: missed "authentication required",
# "quota reached"). "auth" also covers authentication/authorization/unauthorized.
_AUTH_RE = re.compile(r"auth|api[ _-]?key|payment|billing|quota", re.I)

# Env (CORRECTIVE_WEB_CMD / CORRECTIVE_WEB_MODEL) is read at CALL TIME inside _call(), never at
# import — the adapter is documented as env-driven, so import-time capture would freeze it stale
# and force tests to importlib.reload() (codex review Corrective-RAG HIGH-2).


def is_enabled():
    """Returns True only when CORRECTIVE_WEB_ENABLED=true (case-insensitive).
    OFF by default; must be explicitly enabled.
    """
    return os.environ.get("CORRECTIVE_WEB_ENABLED", "false").lower() == "true"


def _call(prompt, retries=3, timeout=60):
    """One-shot CLI call -> list[dict]. Exponential backoff on failure.
    $0-or-STOP: auth/payment prompt raises RuntimeError immediately.
    """
    web_cmd = os.environ.get("CORRECTIVE_WEB_CMD", "")      # read at call time, not import
    web_model = os.environ.get("CORRECTIVE_WEB_MODEL", "")
    if not web_cmd:
        raise RuntimeError(
            "CORRECTIVE_WEB_CMD not set; cannot run web fallback"
        )

    cmd = [web_cmd, "-z", prompt, "-m", web_model]
    last = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = (p.stdout or "") + (p.stderr or "")
            # $0-or-STOP guard: any auth/payment signal -> hard stop, never continue
            if _AUTH_RE.search(out):
                raise RuntimeError(
                    f"AUTH/PAYMENT prompt from web CLI — STOP, do not fall back to paid path: "
                    f"{out[:300]}"
                )
            # Parse strict JSON list
            try:
                parsed = json.loads(out.strip())
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            # Try to find a JSON array anywhere in output
            m = re.search(r"\[.*\]", out, re.S)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            last = f"no parseable JSON list in: {out[-200:]}"
        except subprocess.TimeoutExpired:
            last = f"timeout {timeout}s"
        except RuntimeError:
            raise  # propagate auth/payment errors immediately
        time.sleep((2 ** attempt) * 2)
    raise RuntimeError(f"web fallback CLI failed after {retries} attempts: {last}")


def fetch(query_text, role):
    """Fetch web facts for query_text scoped to role.
    Returns list[dict] with provenance="web" on each item.

    $0-or-STOP: raises RuntimeError on any auth/payment signal.
    Only call when is_enabled() is True.
    """
    if not is_enabled():
        raise RuntimeError(
            "web fallback is disabled (CORRECTIVE_WEB_ENABLED != true); "
            "should not have been called"
        )
    prompt = (
        f"You are a web researcher. Role scope: {role}. "
        f"Find facts answering: {query_text!r}. "
        f"Reply ONLY with compact JSON list: "
        f'[{{"fact": "...", "source": "..."}}]'
    )
    facts = _call(prompt)
    # Attach provenance=web, lower authority than graph/keyword
    return [{"provenance": "web", **f} for f in facts]
