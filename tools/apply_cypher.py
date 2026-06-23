"""Apply one or more Neo4j .cypher schema files via the driver.

The repo shipped raw schema/*.cypher with no apply step, so a clean clone (and CI) had
no way to seed constraints + indexes. This is that step. Usage:

    python tools/apply_cypher.py 01-context/schema/01_constraints.cypher 01-context/schema/03_indexes.cypher

Scope: SCHEMA files only (CREATE CONSTRAINT / CREATE INDEX, IF NOT EXISTS — idempotent,
re-runs safely). The splitter strips `//` line comments and splits on `;`; it does NOT
handle a `;`/`//` embedded inside a string literal, which schema DDL does not contain.
"""
import sys
from neo4j import GraphDatabase

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")  # local/CI dev cred (not a secret)


def statements(text):
    """Split a .cypher file into executable statements (comment-stripped, `;`-delimited)."""
    out, buf = [], []
    for line in text.splitlines():
        code = line.split("//", 1)[0].rstrip()  # drop line comments
        if not code.strip():
            continue
        buf.append(code)
        if code.endswith(";"):
            out.append(" ".join(buf).rstrip(";").strip())
            buf = []
    if buf:
        out.append(" ".join(buf).strip())
    return [s for s in out if s]


def main(paths):
    if not paths:
        sys.exit("usage: apply_cypher.py <file.cypher> [more.cypher ...]")
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            for p in paths:
                stmts = statements(open(p).read())
                for st in stmts:
                    s.run(st)
                print(f"applied {len(stmts)} statement(s) from {p}")
    print("APPLY_CYPHER_OK")


if __name__ == "__main__":
    main(sys.argv[1:])
