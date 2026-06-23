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
Allowlisted files: mutate.py (the engine) + the invariant_check / cycle_check / run_guard self-test
fixtures (which inject violations on purpose) + this gate itself (it carries the patterns as literals).

Exit 0 + WRITE_GATEWAY_OK if clean; exit 1 + the offending file:line(s) otherwise.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
SCAN_DIRS = ["01-context/src", "02-agents/src", "03-evals/src", "tools"]
# engine + adversarial self-test fixtures (invariant_check / cycle_check / run_guard inject violations
# on purpose) + this gate itself (it carries the RELATES_TO patterns as string literals).
ALLOWLIST = {"mutate.py", "invariant_check.py", "cycle_check.py", "run_guard.py", "check_write_gateway.py"}

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


if __name__ == "__main__":
    main()
