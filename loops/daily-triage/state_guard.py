#!/usr/bin/env python3
"""State guard for the daily-triage loop: content-hash optimistic lock + attributed writes.

STATE.md is rewritten wholesale each run with no concurrency guard and no attribution
(a human edit or an overlapping run silently clobbers; nobody records who set/cleared the
kill-switch). This tool gives the write path deterministic primitives — the loop still owns
the STATE.md write, this tool never touches it:

  hash     the precondition token: sha256 hex of the file bytes.
  precheck the optimistic lock: exit 0 if the file is unchanged since `hash`, else exit 1
           (STALE to stderr) so a write built on a stale read is rejected, not clobbered.
  stamp    append-only attribution: one JSON line per write (who / when / field / post-hash).

Caller-tracked hash — NOT embedded in STATE.md (no self-reference): the caller records
`hash` at read time and passes it back at `precheck` time. Pure stdlib.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def cmd_hash(args):
    try:
        print(_sha256(args.path))
    except OSError as e:
        print(f"ERROR: cannot hash {args.path}: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_precheck(args):
    try:
        cur = _sha256(args.path)
    except OSError:
        # Missing/unreadable file is stale by definition — reject the write, don't crash.
        print(
            f"STALE: {args.path} changed since read (expected {args.expected[:12]}, got <missing>)",
            file=sys.stderr,
        )
        return 1
    if cur == args.expected:
        return 0
    print(
        f"STALE: {args.path} changed since read (expected {args.expected[:12]}, got {cur[:12]})",
        file=sys.stderr,
    )
    return 1


def cmd_stamp(args):
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "author": args.author,
        "session": args.session,
        "field": args.field,
        "post_hash": args.hash,
    }
    try:
        with open(args.attrib_log, "a") as f:  # append-only; never truncates/rewrites
            f.write(json.dumps(entry) + "\n")
    except OSError as e:  # bad dir / non-writable — clean nonzero, not a traceback (match cmd_hash)
        print(f"ERROR: cannot append to {args.attrib_log}: {e}", file=sys.stderr)
        return 1
    return 0


def _last_post_hash(attrib_log):
    """Return the post_hash of the last non-blank line in the attrib log, or None if the log is
    absent/empty. Raises ValueError if the last line is present but not valid JSON."""
    last = None
    try:
        with open(attrib_log) as f:
            for line in f:
                if line.strip():
                    last = line
    except OSError:
        return None  # no log yet -> bootstrap (nothing stamped)
    if last is None:
        return None
    return json.loads(last).get("post_hash")  # ValueError propagates -> caller treats as unattributed


def cmd_verify(args):
    """Cross-run attribution gate: exit 1 if STATE.md's current hash != the last stamped post_hash
    (a write landed WITHOUT a matching stamp — e.g. a crash/abort after write, before stamp; the
    within-run stamp is an agent step, so this next-run check is what makes a skip DETECTABLE rather
    than a silent, permanent un-attributed mutation). Exit 0 when they match, or when there are no
    stamps yet (bootstrap / first run)."""
    try:
        cur = _sha256(args.state)
    except OSError as e:
        print(f"ERROR: cannot hash {args.state}: {e}", file=sys.stderr)
        return 1
    try:
        last_hash = _last_post_hash(args.attrib_log)
    except ValueError:
        print(f"UNATTRIBUTED: {args.attrib_log} last line is not valid JSON", file=sys.stderr)
        return 1
    if last_hash is None:
        return 0  # bootstrap: no prior stamp to verify against
    if cur == last_hash:
        return 0
    print(
        f"UNATTRIBUTED: {args.state} ({cur[:12]}) != last stamped post_hash "
        f"({(last_hash or '')[:12]}) — a STATE.md write landed without a stamp",
        file=sys.stderr,
    )
    return 1


def _selftest(args=None):
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "STATE.md")
        with open(state, "w") as f:
            f.write("High-Priority: none\n")

        # (d) hash is stable: same bytes -> same hex
        h1, h2 = _sha256(state), _sha256(state)
        assert h1 == h2, "hash not stable across identical bytes"
        print(f"  (d) hash stable: {h1[:12]} == {h2[:12]}  OK")

        # (a) precheck PASSES when file is unchanged since hash
        rc = cmd_precheck(argparse.Namespace(path=state, expected=h1))
        assert rc == 0, f"precheck should pass on unchanged file, got exit {rc}"
        print("  (a) precheck PASS on unchanged file: exit 0  OK")

        # (b) precheck FAILS (exit 1) after content changes — the stale-hash rejection demo
        with open(state, "w") as f:
            f.write("High-Priority: CHANGED by an overlapping writer\n")
        rc = cmd_precheck(argparse.Namespace(path=state, expected=h1))
        assert rc == 1, f"precheck should fail on changed file, got exit {rc}"
        print("  (b) precheck FAIL on changed file: exit 1  OK  (stale-hash rejection)")

        # (b') precheck on a missing file is STALE (exit 1), no traceback
        rc = cmd_precheck(argparse.Namespace(path=os.path.join(d, "gone.md"), expected=h1))
        assert rc == 1, f"precheck on missing file should be stale, got exit {rc}"
        print("  (b') precheck FAIL on missing file: exit 1  OK")

        # (c) stamp appends a valid JSON line; a second stamp APPENDS (2 lines — append-only)
        log = os.path.join(d, "STATE.attrib.jsonl")
        new_hash = _sha256(state)
        cmd_stamp(argparse.Namespace(attrib_log=log, author="loop-triage",
                                     session="run-1", hash=new_hash, field="High-Priority"))
        cmd_stamp(argparse.Namespace(attrib_log=log, author="human",
                                     session="manual", hash=new_hash, field="High-Priority"))
        with open(log) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        assert len(lines) == 2, f"append-only broken: expected 2 lines, got {len(lines)}"
        first = json.loads(lines[0])
        for k in ("ts", "author", "session", "field", "post_hash"):
            assert k in first, f"stamp entry missing field: {k}"
        assert first["author"] == "loop-triage" and first["post_hash"] == new_hash
        print(f"  (c) stamp append-only: 2 lines, fields {sorted(first)}  OK")

        # (e) verify: attribution is a real cross-run check, not skippable prose.
        vlog = os.path.join(d, "verify.attrib.jsonl")
        # bootstrap: no log yet -> verify passes (nothing to attribute against)
        assert cmd_verify(argparse.Namespace(state=state, attrib_log=vlog)) == 0, "bootstrap verify should pass"
        # stamp the current STATE.md, then verify PASSES (write is attributed)
        h_now = _sha256(state)
        cmd_stamp(argparse.Namespace(attrib_log=vlog, author="loop-triage",
                                     session="run-2", hash=h_now, field="STATE.md"))
        assert cmd_verify(argparse.Namespace(state=state, attrib_log=vlog)) == 0, "verify should pass when STATE.md matches last stamp"
        # now mutate STATE.md WITHOUT stamping -> next-run verify DETECTS the unattributed write
        with open(state, "w") as f:
            f.write("High-Priority: edited but NOT stamped\n")
        rc = cmd_verify(argparse.Namespace(state=state, attrib_log=vlog))
        assert rc == 1, f"verify should FAIL on an unstamped write, got exit {rc}"
        print("  (e) verify detects unattributed (unstamped) write: exit 1  OK")

    print("STATE_GUARD_OK")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="STATE.md content-hash guard + attributed writes")
    p.add_argument("--self-test", action="store_true",
                   help="run the self-test demo, print STATE_GUARD_OK, exit 0")
    sub = p.add_subparsers(dest="cmd")

    ph = sub.add_parser("hash", help="print sha256 hex of the file bytes (nothing else)")
    ph.add_argument("path")
    ph.set_defaults(func=cmd_hash)

    pp = sub.add_parser("precheck", help="exit 0 if file sha256 == expected, else exit 1 (STALE)")
    pp.add_argument("path")
    pp.add_argument("expected")
    pp.set_defaults(func=cmd_precheck)

    ps = sub.add_parser("stamp", help="append one attribution JSON line (append-only)")
    ps.add_argument("attrib_log")
    ps.add_argument("--author", required=True)
    ps.add_argument("--session", required=True)
    ps.add_argument("--hash", required=True)
    ps.add_argument("--field", default="STATE.md")
    ps.set_defaults(func=cmd_stamp)

    pv = sub.add_parser("verify", help="exit 1 if STATE.md was written without a matching stamp (unattributed)")
    pv.add_argument("state")
    pv.add_argument("attrib_log")
    pv.set_defaults(func=cmd_verify)

    pt = sub.add_parser("test", help="alias for --self-test")
    pt.set_defaults(func=_selftest)

    args = p.parse_args(argv)
    if args.self_test:
        return _selftest(args)
    if not getattr(args, "func", None):
        p.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
