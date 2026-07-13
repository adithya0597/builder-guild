"""builder-guild-xzw selftest: prove extract.mine stages a valid enum-typed candidate, dead-letters
unknown/malformed LLM output (never staging it), and degrades clean when EXTRACT_CMD is unset — all
in one process, with a THROWAWAY fixture EXTRACT_CMD (a tiny self-written script echoing canned JSON,
NEVER a real LLM). The unconditional STOP-contract guard (extract._selftest_stop) runs first.

Verify: `01-context/.venv/bin/python 01-context/src/selftest_extract.py`
  -> EXTRACT_STOP_OK, EXTRACT_FIXTURE_OK, EXTRACT_DEADLETTER_OK, EXTRACT_SKIP (exit 0),
     with EXTRACT_CMD unset (`env -u EXTRACT_CMD ...`) the same run still reaches EXTRACT_SKIP.
"""
import os
import stat
import sys
import tempfile

from neo4j import GraphDatabase

import extract

TNS = "_extract_selftest"
NOW = "2026-07-09T00:00:00Z"
SUBJ, OBJ, PROSE = "issue:EX-1", "issue:EX-2", "obs:EX-PROSE"


def _fixture(body):
    """Write a throwaway executable that ignores its args and prints `body` to stdout. Returns the
    absolute path (executable, so shutil.which resolves it)."""
    fd, path = tempfile.mkstemp(suffix="_extract_fixture.py")
    with os.fdopen(fd, "w") as f:
        f.write("#!/usr/bin/env python3\nprint(%r)\n" % body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return path


def _seed_prose(session):
    # a plain Observation NODE (no RELATES_TO edge -> write-gateway grep stays green with this file
    # OUTSIDE its allowlist; no mutate import either). long_context is the prose mine() reads.
    session.execute_write(lambda tx: tx.run(
        "MERGE (n:Entity:Observation {key:$k}) SET n.namespace=$ns, n.long_context=$t",
        k=PROSE, ns=TNS, t="EX-1 blocks EX-2 per the standup."))


def _clean(session):
    session.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=TNS))


def main():
    extract._selftest_stop()
    print("EXTRACT_STOP_OK")

    fixtures = []
    dl_fd, dl_path = tempfile.mkstemp(suffix="_extract_deadletter.jsonl")
    os.close(dl_fd)
    extract.DEADLETTER = dl_path                     # keep dead-letters out of the repo tree
    fail = []

    with GraphDatabase.driver(extract.URI, auth=extract.AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            try:
                _clean(s)
                _seed_prose(s)

                # (1) FIXTURE: valid free-form relation "blocks" -> BLOCKS enum -> ONE staged candidate.
                fx = _fixture('[{"subject": "%s", "relation": "blocks", "object": "%s"}]' % (SUBJ, OBJ))
                fixtures.append(fx)
                os.environ["EXTRACT_CMD"] = fx
                staged, dead = extract.mine(s, TNS, NOW)
                cand = s.execute_read(lambda tx: tx.run(
                    "MATCH (c:Candidate {cand_id:$id}) RETURN c.rel AS rel, c.origin AS origin, "
                    "c.status AS status, c.o_key AS o, c.source AS source",
                    id=(staged[0] if staged else "")).single())
                ok_fx = (len(staged) == 1 and dead == 0 and cand is not None
                         and cand["rel"] == "BLOCKS" and cand["origin"] == "llm"
                         and cand["status"] == "pending" and cand["o"] == OBJ and cand["source"] == PROSE)
                fail += [] if ok_fx else [f"fixture: staged={staged} dead={dead} cand={cand}"]
                if ok_fx:
                    print("EXTRACT_FIXTURE_OK")

                # (2) DEAD-LETTER: unknown relation, then malformed output — both -> dead-lettered,
                #     NEVER staged. Count dead-letter lines grow by exactly one each pass.
                def _dl_lines():
                    with open(dl_path) as f:
                        return sum(1 for ln in f if ln.strip())

                _clean(s); _seed_prose(s)            # drop the staged candidate from pass (1)
                n0 = _dl_lines()
                fx_unknown = _fixture('[{"subject": "a", "relation": "frobnicates", "object": "b"}]')
                fixtures.append(fx_unknown)
                os.environ["EXTRACT_CMD"] = fx_unknown
                st1, d1 = extract.mine(s, TNS, NOW)
                fx_bad = _fixture("this is not json at all")
                fixtures.append(fx_bad)
                os.environ["EXTRACT_CMD"] = fx_bad
                st2, d2 = extract.mine(s, TNS, NOW)
                n1 = _dl_lines()
                ok_dl = (st1 == [] and st2 == [] and d1 == 1 and d2 == 1 and n1 - n0 == 2)
                fail += [] if ok_dl else [f"deadletter: st1={st1} st2={st2} d1={d1} d2={d2} lines+={n1 - n0}"]
                if ok_dl:
                    print("EXTRACT_DEADLETTER_OK")

                # (3) SKIP: EXTRACT_CMD unset -> mine is a clean no-op, exit 0.
                os.environ.pop("EXTRACT_CMD", None)
                st3, d3 = extract.mine(s, TNS, NOW)
                ok_skip = (st3 == [] and d3 == 0)
                fail += [] if ok_skip else [f"skip: st3={st3} d3={d3}"]
                if ok_skip:
                    print("EXTRACT_SKIP")
            finally:
                _clean(s)

    for fx in fixtures:
        try:
            os.unlink(fx)
        except OSError:
            pass
    os.unlink(dl_path)

    if fail:
        print("EXTRACT_SELFTEST_FAIL: " + " | ".join(fail))
        sys.exit(1)


if __name__ == "__main__":
    main()
