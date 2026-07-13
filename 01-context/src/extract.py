"""builder-guild-xzw: suggest-only LLM prose-miner + edge-typer (NET-NEW).

Pulls Observation/Source prose already in-graph (etl_history ingest — :Entity:Observation /
:Entity:Source, prose in long_context), asks an external LLM for free-form (subject, relation,
object) triples, maps each free-form relation onto the 16-relation enum in schema/relations.yaml,
and STAGES accepted triples as :Candidate nodes via staging.stage_llm (origin='llm'). Unknown
relation OR malformed LLM output -> DEAD-LETTER JSONL, never staged. The human review CLI stays the
sole edge-write path — nothing here materializes an edge.

The LLM is reached ONLY through a subprocess CLI (env EXTRACT_CMD) — NO vendor SDK, NO network lib
($0 law). The 16-relation enum is read DIRECTLY from schema/relations.yaml (the same source the
mutation engine reads) rather than importing that engine: importing it would trip the write-gateway
import scan and license an edge write, weakening the suggest-only posture.

$0/STOP contract (mirrors 03-evals/src/judge_adapter.py post-c7u — do NOT cross-import the evals
layer): an auth/payment/quota prompt from the CLI is a hard STOP (raise, never fall back to a paid
key), checked FIRST; a present-but-broken CLI (returncode!=0) is a loud malfunction (raise);
EXTRACT_CMD absent degrades clean (mine() is a no-op). _selftest_stop() runs unconditionally so CI
enforces both holes even with no EXTRACT_CMD provisioned.

CI: the selftest is CI-wirable next run (the fixture EXTRACT_CMD must be provisioned to hit the
FIXTURE path — more than a one-line CI edit, out of this run's scope).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from neo4j import GraphDatabase

import staging   # stage_llm — the ONLY ingest write path (origin='llm' -> :Candidate)

URI, AUTH = os.environ.get("NEO4J_URI", "bolt://localhost:7688"), ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))  # local/CI dev cred (not a secret)
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "gpt-5.4")

# 16-relation enum, read DIRECTLY from relations.yaml (the same source the mutation engine reads) —
# NOT an import of that engine (which the write-gateway import scan would flag + license a write).
RELATIONS = set(yaml.safe_load((Path(__file__).parent.parent / "schema" / "relations.yaml").read_text())["relations"])

DEADLETTER = Path(__file__).parent.parent / "extract_deadletter.jsonl"
_DEADLETTER_CAP = 5 * 1024 * 1024   # 5 MB; at cap roll to a single-generation .1 so a runaway/adversarial EXTRACT_CMD can't disk-fill


def _extract_cmd():
    # read at call time (not import time) so a `-u EXTRACT_CMD` run and a mid-process set both take.
    return os.path.expanduser(os.environ.get("EXTRACT_CMD", ""))


def _is_auth_payment_error(out):
    # COPIED VERBATIM from 03-evals/src/judge_adapter.py:29-32 (provenance): mirror the $0-or-STOP
    # guard rather than cross-import the evals layer. "auth" also covers
    # authentication/authorization/unauthorized.
    return bool(re.search(r"auth|api[ _-]?key|payment|billing|quota", out, re.I))


def _last_array(out):
    """Substring of the LAST balanced top-level [...] in `out`, or None. Bracket-depth scan (same
    brackets-in-strings fidelity as the prior greedy regex) — trailing prose after the array, or a
    stray '[' in earlier prose, no longer drags the match across into unparseable text."""
    depth = start = 0
    last = None
    for i, ch in enumerate(out):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]" and depth > 0:
            depth -= 1
            if depth == 0:
                last = out[start:i + 1]
    return last


def _call(prompt, timeout=180):
    """One EXTRACT_CMD call -> raw stdout+stderr. Mirrors judge_adapter._call's STOP discipline:
    auth/payment prompt -> STOP (raise, precedence over returncode); returncode!=0 -> RuntimeError
    malfunction sentinel (don't trust a broken CLI's stdout). Parsing/typing failures are the
    caller's dead-letter problem, NOT a raise."""
    cmd = _extract_cmd()
    try:
        p = subprocess.run([cmd, "-z", prompt, "-m", EXTRACT_MODEL],
                           capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"extract CLI not executable ({cmd}): {e}") from e
    out = (p.stdout or "") + (p.stderr or "")
    if _is_auth_payment_error(out):        # auth/payment STOP takes precedence over returncode
        raise RuntimeError(f"AUTH/PAYMENT prompt from the extract CLI — STOP, do not fall back: {out[:200]}")
    if p.returncode != 0:                  # present-but-broken CLI: don't trust its stdout as output
        raise RuntimeError(f"nonzero returncode {p.returncode}: {out[-200:]}")
    return out


def _parse(out):
    """Last balanced JSON array in the CLI output -> list, or None (unparseable -> dead-letter,
    never staged)."""
    arr = _last_array(out)
    if arr is None:
        return None
    try:
        v = json.loads(arr)
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, list) else None


def _normalize_rel(raw):
    """Free-form relation string -> canonical enum member, or None if unknown (-> dead-letter)."""
    if not isinstance(raw, str):
        return None
    key = re.sub(r"[\s-]+", "_", raw.strip()).upper()
    return key if key in RELATIONS else None


def _deadletter(record, reason):
    p = Path(DEADLETTER)   # DEADLETTER may be reassigned to a str (selftest tempfile); normalize
    try:
        if p.stat().st_size >= _DEADLETTER_CAP:
            p.replace(p.with_suffix(".1"))   # single-generation roll; any prior .1 is overwritten
    except FileNotFoundError:
        pass
    with open(p, "a") as f:
        f.write(json.dumps({"reason": reason, "record": record}, ensure_ascii=True) + "\n")


def _prose_nodes(session, ns):
    """Observation/Source prose already in-graph (etl_history ingest): (key, long_context text)."""
    return session.execute_read(lambda tx: [
        (r["key"], r["text"]) for r in tx.run(
            "MATCH (n:Entity) WHERE n.namespace=$ns AND (n:Observation OR n:Source) "
            "RETURN n.key AS key, n.long_context AS text ORDER BY n.key", ns=ns)])


def mine(session, ns, now):
    """Mine prose in namespace `ns`: LLM -> free-form triples -> enum-typed candidates staged via
    stage_llm (origin='llm'). Unknown relation / malformed output -> dead-letter, never staged.
    Returns (staged_cand_ids, deadletter_count). Raises on the STOP contract (auth/payment), a
    broken CLI, or a SET-but-unresolvable EXTRACT_CMD — never a silent fallback. EXTRACT_CMD absent
    -> clean no-op ([], 0)."""
    cmd = _extract_cmd()
    if not cmd:
        return [], 0                       # EXTRACT_CMD unset -> clean no-op (the `env -u` contract)
    if shutil.which(cmd) is None:          # SET but unresolvable -> loud misconfig, NOT a silent disable
        raise RuntimeError(f"EXTRACT_CMD set but not resolvable to an executable: {cmd!r} — point it "
                           "at a single binary (a multi-word command string won't resolve via PATH)")
    staged, dead = [], 0
    for s_key, text in _prose_nodes(session, ns):
        prompt = ('Extract factual relationships from the text as compact JSON. Reply ONLY a JSON '
                  'array of {"subject": "...", "relation": "...", "object": "..."} objects (empty '
                  f'array if none). Text: "{text or ""}"')
        triples = _parse(_call(prompt))          # STOP / malfunction raise inside _call
        if triples is None:
            _deadletter({"s_key": s_key}, "malformed_llm_output"); dead += 1; continue
        edges = []
        for t in triples:
            rel = _normalize_rel(t.get("relation")) if isinstance(t, dict) else None
            subj = t.get("subject") if isinstance(t, dict) else None
            obj = t.get("object") if isinstance(t, dict) else None
            if not (rel and subj and obj):
                _deadletter({"s_key": s_key, "triple": t}, "unknown_relation_or_malformed"); dead += 1; continue
            edges.append((subj, rel, obj, ns, None, None, s_key))   # source=s_key: originating prose
        if edges:
            staged.extend(staging.stage_llm(session, edges, now))    # stage per prose-node: a mid-loop
            #   failure keeps earlier nodes' candidates instead of discarding all mined-but-unstaged work
    return staged, dead


def _selftest_stop():
    """Pure-function STOP-contract guard — runs even when EXTRACT_CMD is unset (the EXTRACT_SKIP
    path), so CI enforces both holes for free. Mirrors judge_adapter._selftest_stop (post-c7u)."""
    for s in ("authentication required", "unauthorized 401", "api key required",
              "payment", "quota exceeded", "billing"):
        assert _is_auth_payment_error(s), f"auth-STOP regex missed {s!r} — would silently fall back"
    assert not _is_auth_payment_error('[{"relation": "BLOCKS"}]'), "auth-STOP false-positive on clean output"

    orig_run = subprocess.run
    try:
        # a present-but-broken CLI (returncode!=0) with parseable stdout must NOT be trusted.
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(
            a, 1, '[{"subject":"x","relation":"BLOCKS","object":"y"}]', "")
        broke = False
        try:
            _call("x")
        except RuntimeError:
            broke = True
        assert broke, "broken CLI (returncode=1) accepted as real output"

        # auth/payment STOP takes precedence over returncode (checked FIRST, never a fallback).
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, "unauthorized 401", "")
        stopped = False
        try:
            _call("x")
        except RuntimeError as e:
            stopped = str(e).startswith("AUTH/PAYMENT")
        assert stopped, "auth/payment output did not hard-STOP"
    finally:
        subprocess.run = orig_run


def _selftest_roll():
    """Prove _deadletter rolls to a single-generation .1 at the size cap (disk-fill guard against a
    runaway EXTRACT_CMD) — pure file I/O, no graph. Uses a throwaway tempfile + tiny cap; leaves no
    stray dead-letter in the repo."""
    global DEADLETTER, _DEADLETTER_CAP
    orig_dl, orig_cap = DEADLETTER, _DEADLETTER_CAP
    fd, tmp = tempfile.mkstemp(suffix="_extract_roll.jsonl")
    os.close(fd)
    rolled = Path(tmp).with_suffix(".1")
    try:
        DEADLETTER, _DEADLETTER_CAP = tmp, 200      # tiny cap so a few writes trip the roll
        for _ in range(20):
            _deadletter({"pad": "x" * 30}, "roll_test")
        assert rolled.exists(), "dead-letter did not roll to .1 at cap"
        assert Path(tmp).stat().st_size < _DEADLETTER_CAP, "active dead-letter not rolled (still over cap)"
    finally:
        DEADLETTER, _DEADLETTER_CAP = orig_dl, orig_cap
        for p in (tmp, rolled):
            try:
                os.unlink(p)
            except OSError:
                pass


def _selftest_badcmd():
    """A SET-but-unresolvable EXTRACT_CMD must fail LOUD (not silently disable). Unset stays a clean
    skip — proven separately by the `env -u` run + selftest_extract's EXTRACT_SKIP. mine() gates on
    the command before any graph access, so session=None never gets touched here."""
    orig = os.environ.get("EXTRACT_CMD")
    try:
        os.environ["EXTRACT_CMD"] = "/no/such/extract-cmd-xyzzy --with-a-flag"
        raised = False
        try:
            mine(None, "_never", "_never")
        except RuntimeError as e:
            raised = "EXTRACT_CMD" in str(e)
        assert raised, "set-but-unresolvable EXTRACT_CMD silently disabled instead of raising"
    finally:
        if orig is None:
            os.environ.pop("EXTRACT_CMD", None)
        else:
            os.environ["EXTRACT_CMD"] = orig


if __name__ == "__main__":
    _selftest_stop()
    print("EXTRACT_STOP_OK")
    _selftest_roll()
    print("EXTRACT_ROLL_OK")
    _selftest_badcmd()
    print("EXTRACT_BADCMD_OK")
