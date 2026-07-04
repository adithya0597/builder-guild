"""Write-gateway gate (builder-guild-crk): a static, READ-ONLY check that FAILS if any module
hand-writes a CURRENT RELATES_TO edge outside the single sanctioned engine (mutate.apply_edge).

WHY: "single writer" is APPLICATION-enforced, not DB-enforced (Neo4j community cannot constrain
"exactly one current edge" — a predicate, not a key). The enforcement is: every RELATES_TO mutation
goes through mutate.apply_edge, and THIS gate continuously rejects any handwritten current-edge write
that bypasses it. Pure source scan — no DB — so it runs in the CI smoke job + as a pre-commit check.

Heuristic (NOT a parser): flags a RELATES_TO relationship pattern (`-[:RELATES_TO` / `-[r:RELATES_TO`)
that has a CREATE/MERGE verb on the SAME line OR within the 2 concatenated string-lines above it (the
verb-then-pattern idiom a per-line check would miss). Plain MATCH reads have no nearby write verb, so
they pass. This is a cheap STATIC backstop, NOT the authoritative one: a write split across >3 source
lines, or an ad-hoc cypher-shell session, can still evade it — the AUTHORITATIVE net is the RUNTIME
detection sweeps (invariant_check.py >1-current, cycle_check.py cycles) gated in CI + run as ops sweeps.
Allowlisted files: mutate.py (the engine) + the invariant_check / cycle_check / run_guard / retention_sweep
self-test fixtures (which inject violations on purpose) + this gate itself (it carries the patterns as literals).

Exit 0 + WRITE_GATEWAY_OK if clean; exit 1 + the offending file:line(s) otherwise.
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent.parent
SCAN_DIRS = ["01-context/src", "02-agents/src", "03-evals/src", "tools"]
# engine + adversarial self-test fixtures (invariant_check / cycle_check / run_guard inject violations
# on purpose; retention_sweep._selftest seeds raw historical+current edges to prove the prune keeps
# current + in-window history) + this gate itself (it carries the RELATES_TO patterns as string literals).
ALLOWLIST = {"mutate.py", "invariant_check.py", "cycle_check.py", "run_guard.py", "retention_sweep.py", "check_write_gateway.py"}

WRITE_WINDOW = 3   # a CREATE/MERGE up to WRITE_WINDOW-1 concatenated string-lines ABOVE the pattern counts
EDGE_PAT = re.compile(r"-\[\s*r?\s*:RELATES_TO")   # a RELATES_TO relationship pattern (write side)
WRITE_PAT = re.compile(r"\b(CREATE|MERGE)\b")       # ...in a CREATE/MERGE clause (a write, not a MATCH read)


def violations():
    hits = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.py")):
            if p.name in ALLOWLIST:
                continue
            lines = p.read_text().splitlines()
            for i, line in enumerate(lines):
                if not EDGE_PAT.search(line):
                    continue
                # WRITE verb on the same line OR within the WRITE_WINDOW-1 concatenated lines above
                # (the verb-then-pattern idiom); a plain MATCH read has no write verb in that window.
                window = " ".join(lines[max(0, i - WRITE_WINDOW + 1): i + 1])
                if WRITE_PAT.search(window):
                    hits.append((p.relative_to(ROOT), i + 1, line.strip()))
    return hits


# builder-guild-62f: second static scan — call-sites of mutate.apply_edge / mutate.resolve_entity
# (or the bare import itself) in modules OUTSIDE this allowlist. Catches the bypass EDGE_PAT can't
# see: a module that imports mutate and calls apply_edge writes no RELATES_TO literal at all.
# 12 real callers (grepped 01-context/src 02-agents/src 03-evals/src tools) + 3 prose-only files
# that only mention the pattern in a docstring/print (check_write_gateway.py, invariant_check.py,
# retention_sweep.py) + mutate.py itself (0 hits, kept for parity with ALLOWLIST above).
CALL_ALLOWLIST = {
    "mutate.py", "check_write_gateway.py", "invariant_check.py", "retention_sweep.py",
    "race_test.py", "etl.py", "embed.py", "etl_history.py", "staging_race_test.py",
    "stamp.py", "sweep.py", "staging.py", "demo_seed.py", "eval_planner.py",
    "gt2_draft.py", "rollback.py",
}
IMPORT_CALL_PAT = re.compile(r"mutate\.apply_edge|mutate\.resolve_entity|from mutate import|import mutate")


def import_violations():
    # identical loop shape to violations(): same SCAN_DIRS, CALL_ALLOWLIST not ALLOWLIST,
    # IMPORT_CALL_PAT.search(line) instead of the EDGE_PAT+WRITE_PAT window logic.
    hits = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.py")):
            if p.name in CALL_ALLOWLIST:
                continue
            try:
                lines = p.read_text().splitlines()
            except FileNotFoundError:
                continue  # vanished mid-scan (e.g. a concurrent --selftest's own temp file)
            for i, line in enumerate(lines):
                if IMPORT_CALL_PAT.search(line):
                    hits.append((p.relative_to(ROOT), i + 1, line.strip()))
    return hits


def _selftest():
    # clause (a): plant a violation under a scanned dir, assert it's flagged at that file:line,
    # clean up in finally — zero residue even if the assert raises.
    # mkstemp, not a fixed path + write_text: O_EXCL refuses a pre-planted symlink (CWE-59) and
    # the unique name means two concurrent --selftest runs can't collide on the same file.
    root_abs = ROOT.resolve()
    fd, path_str = tempfile.mkstemp(dir=str(root_abs / "tools"), suffix="_wg_selftest_violation.py")
    target = pathlib.Path(path_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("import mutate\nmutate.apply_edge(1, 2, 3)\n")
        rel = target.relative_to(root_abs)
        flagged = {(p, ln) for p, ln, _ in import_violations() if p == rel}
        assert (rel, 2) in flagged, f"selftest violation not flagged: {flagged}"
    finally:
        target.unlink(missing_ok=True)
    print("WRITE_IMPORTS_SELFTEST_OK")


def main():
    hits = violations()
    if hits:
        print(f"WRITE_GATEWAY VIOLATION — {len(hits)} handwritten current-edge write(s) bypassing "
              f"mutate.apply_edge (route them through apply_edge, or allowlist a proven self-test):")
        for path, ln, text in hits:
            print(f"  {path}:{ln}: {text}")
        sys.exit(1)
    print(f"scanned {SCAN_DIRS} (allowlist: {sorted(ALLOWLIST)})")
    print("WRITE_GATEWAY_OK")
    import_hits = import_violations()
    if import_hits:
        print(f"WRITE_IMPORTS VIOLATION — {len(import_hits)} mutate call-site(s)/import(s) outside "
              f"CALL_ALLOWLIST:")
        for path, ln, text in import_hits:
            print(f"  {path}:{ln}: {text}")
        sys.exit(1)
    print("WRITE_IMPORTS_OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    main()
