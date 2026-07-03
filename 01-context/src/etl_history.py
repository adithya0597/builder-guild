"""etl_history.py (builder-guild-22w): session-history deterministic ingest — dogfood corpus #1.

Ingests two REAL local stores into ONE dedicated `history` namespace, ZERO LLM (pure sqlite3/json/re
+ the mutate.py write engine, same convention as etl.py):
  - ~/.engram/engram.db `observations` rows (builder-guild project; env ENGRAM_DB)  -> :Entity:Observation
  - .explore/source-ledger.jsonl records (one per line)                          -> :Entity:Source
Both group under a :Entity:Project node (key=project:<canon_project(name)>), linked PART_OF — the
one relation this module writes, reused as-is from relations.yaml (arity:1, overflow_policy:reject;
a 2nd DIFFERENT parent is refused, not silently re-anchored — matches the historical PART_OF decision
already recorded in engram: "PART_OF kept reject not evict").

Namespace is NEVER derived per-row — always "history" for --real (or "history_test" for --selftest)
— so a casing/spacing variant of the same project name can never trip mutate.resolve_entity's
per-key ownership check (that check raises on a namespace MISMATCH for an already-existing key; a
fixed namespace for every write this module makes means it never mismatches itself).

:Episodic provenance (ep=) is SKIPPED (ep=None everywhere) — no reader consumes it (etl.py's own
decision, rqb 2026-06-22); wiring it here would polish unread code, not ship a read surface.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase
import mutate

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))
REPO_ROOT = Path(__file__).parent.parent.parent
ENGRAM_DB = os.environ.get("ENGRAM_DB", str(Path.home() / ".engram" / "engram.db"))
LEDGER = REPO_ROOT / ".explore" / "source-ledger.jsonl"
NOW_FMT = "%Y-%m-%dT%H:%M:%SZ"


def canon_project(name: str) -> str:
    """Deterministic project-name canonicalization: casing/spacing variants collapse to ONE key.
    canon_project("My-Portfolio") == canon_project("my-portfolio") == "my-portfolio"."""
    return re.sub(r'[\s_]+', '-', name.strip().lower()).strip('-')


# ── real sources (read-only) ─────────────────────────────────────────────────
def _real_engram_rows(project="builder-guild"):
    """engram.db is LIVE — other processes write it. timeout=5.0 sets busy_timeout (sqlite retries
    internally for up to 5s on a lock); one bounded retry beyond that for a lock that outlives it.
    Anything else (or a 2nd 'locked') propagates — fail loud."""
    last_err = None
    for _attempt in range(2):
        try:
            con = sqlite3.connect(f"file:{ENGRAM_DB}?mode=ro", uri=True, timeout=5.0)   # ro URI: never takes a write lock
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT id, type, title, content, project, scope, topic_key, created_at "
                    "FROM observations WHERE project=? ORDER BY id", (project,)).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" not in str(e).lower():
                raise
    raise last_err


def _parse_ledger_lines(lines):
    """Per-line parse: one truncated/corrupt line dead-letters (collected + counted) instead of
    aborting the whole read. Pure function (no I/O) so --selftest can feed it a hermetic fixture
    list without ever touching the real ledger file."""
    records, deadletter = [], []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            deadletter.append({"line": i + 1, "error": f"{type(e).__name__}: {e}"})
    return records, deadletter


def _real_ledger_records():
    if not LEDGER.exists():
        return []
    with LEDGER.open() as f:
        records, deadletter = _parse_ledger_lines(f)
    if deadletter:
        print(f"[deadletter] source-ledger.jsonl: {len(deadletter)} corrupt line(s) skipped: {deadletter}")
    return records


# ── fixtures (hermetic, shaped like the real schemas) ────────────────────────
def _fixture_rows():
    """String ids (not sqlite ints) so a fixture key can never collide with a real obs:<id> key
    regardless of run order between --selftest and --real."""
    return [
        {"id": "fx1", "type": "decision", "title": "Adopt fixture pattern", "content": "Fixture content one.",
         "project": "My-Portfolio", "scope": "project", "topic_key": "fx/one", "created_at": "2026-07-01T00:00:00Z"},
        {"id": "fx2", "type": "feedback", "title": "Casing variant lands on the same project",
         "content": "Fixture content two.", "project": "my-portfolio", "scope": "project",
         "topic_key": "fx/two", "created_at": "2026-07-01T00:05:00Z"},
    ]


def _fixture_ledger():
    return [
        {"type": "run", "run_id": "fixture-run-1", "topic": "fixture topic", "ts": "2026-07-01T00:00:00Z"},
        {"type": "finding", "run_id": "fixture-run-1", "claim": "fixture claim", "sub_q": "q1",
         "ts": "2026-07-01T00:01:00Z"},
    ]


# ── ingest (the only writer: mutate.resolve_entity / mutate.apply_edge) ─────
def ingest(session, rows, ledger, now, ns, ledger_prefix="ledger"):
    """Entities via mutate.resolve_entity (ONE tx — upsert has no reject axis, so it never rolls back
    on a rejected fact). Edges via mutate.apply_edge(PART_OF), ONE TX PER EDGE (mirrors etl.py's
    ingest()): PART_OF is arity:1+overflow:reject, so a single arity collision (e.g. a row's project
    reclassified between runs while its subject already has a current PART_OF elsewhere) raises
    ValueError — per-edge isolation dead-letters THAT fact instead of rolling back the whole corpus.
    Infra errors (neo4j.exceptions.*) are deliberately NOT caught — they propagate and halt, same as
    etl.py. Returns the dead-letter list (empty = every edge applied).
    ZERO LLM. Idempotent: the same rows/ledger/now converges to the identical graph (resolve_entity
    never bumps content_rev; apply_edge's MERGE re-matches the same current edge instead of duplicating).
    ledger_prefix keys each Source node as f'{ledger_prefix}:{line-index}' — default 'ledger' matches
    --real's line-index scheme; --selftest passes a distinct prefix so its fixture records can never
    collide with a real ledger:<i> key regardless of run order between --selftest and --real."""
    def _entities(tx):
        for row in rows:
            mutate.resolve_entity(tx, "Observation", f"obs:{row['id']}", now, ns,
                                  short=row["title"], long_=f"{row['title']}\n\n{row['content']}")
            pkey = f"project:{canon_project(row['project'])}"
            mutate.resolve_entity(tx, "Project", pkey, now, ns, short=row["project"], long_=row["project"])
        for i, rec in enumerate(ledger):
            short = rec.get("claim") or rec.get("topic") or rec["type"]
            mutate.resolve_entity(tx, "Source", f"{ledger_prefix}:{i}", now, ns,
                                  short=short, long_=json.dumps(rec, sort_keys=True))
            pkey = f"project:{canon_project(rec['run_id'])}"
            mutate.resolve_entity(tx, "Project", pkey, now, ns, short=rec["run_id"], long_=rec["run_id"])
    session.execute_write(_entities)

    edges = [(f"obs:{row['id']}", f"project:{canon_project(row['project'])}") for row in rows]
    edges += [(f"{ledger_prefix}:{i}", f"project:{canon_project(rec['run_id'])}")
              for i, rec in enumerate(ledger)]

    deadletter = []
    for s_key, o_key in edges:
        try:
            session.execute_write(
                lambda tx, sk=s_key, ok=o_key: mutate.apply_edge(tx, sk, "PART_OF", ok, now, ns, ep=None))
        except ValueError as e:    # arity:1 overflow:reject collision -> dead-letter, don't roll back the batch
            deadletter.append({"fact": f"{s_key} PART_OF {o_key}", "error": f"{type(e).__name__}: {e}"})
            # infra errors (neo4j.exceptions.*) deliberately NOT caught — they propagate and halt.
    if deadletter:
        print(f"[deadletter] {len(deadletter)} PART_OF edge(s) rejected: {deadletter}")
    return deadletter


def _embed_history_nodes(session, ns, now):
    """Embed every Observation/Source node in `ns` via embed.embed_node directly. resolve_entity
    clears dirty ON CREATE only (never sets it), so a freshly created node never lands in
    sweep.py's dirty queue — embed it directly rather than round-tripping mark_dirty + sweep_once."""
    import embed
    rows = session.execute_read(lambda tx: tx.run(
        "MATCH (n:Entity) WHERE n.namespace=$ns AND (n:Observation OR n:Source) "
        "RETURN n.key AS k, n.long_context AS c", ns=ns).data())
    for r in rows:
        session.execute_write(lambda tx, r=r: embed.embed_node(tx, r["k"], r["c"], "prose", now))
    return len(rows)


# ── --selftest: hermetic fixtures, throwaway namespace, self-cleaning ────────
TNS = "history_test"
T0 = "2026-07-02T00:00:00Z"
T1 = "2026-07-02T00:10:00Z"   # later clock for the reclassify-between-runs dead-letter check


def _selftest():
    fail = []
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=TNS))

            rows, ledger = _fixture_rows(), _fixture_ledger()
            dl1 = ingest(s, rows, ledger, T0, TNS, ledger_prefix="ledgerfx")
            rev1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:fx1'}) RETURN n.content_rev AS r").single()["r"])
            edges1 = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=TNS).single()["c"])

            dl2 = ingest(s, rows, ledger, T0, TNS, ledger_prefix="ledgerfx")   # re-run: SAME fixtures + SAME now -> must be a no-op
            rev2 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:fx1'}) RETURN n.content_rev AS r").single()["r"])
            edges2 = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=TNS).single()["c"])
            print(f"[idempotent] content_rev {rev1} -> {rev2} | current PART_OF edges {edges1} -> {edges2}")
            fail += [] if rev1 == rev2 else ["content_rev changed across an identical re-ingest"]
            fail += [] if edges1 == edges2 else ["current PART_OF edge count changed across re-ingest"]
            fail += [] if not (dl1 or dl2) else [f"unexpected dead-letter on the clean fixture corpus: {dl1 or dl2}"]

            n_proj = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity:Project {key:'project:my-portfolio'}) WHERE n.namespace=$ns "
                "RETURN count(n) AS c", ns=TNS).single()["c"])
            print(f"[canon]      project:my-portfolio node count={n_proj} "
                  f"(expect 1, from 'My-Portfolio' + 'my-portfolio')")
            fail += [] if n_proj == 1 else [f"canon_project did not collapse casing variants: {n_proj} nodes"]

            # FIX bc7/22w: a row's project reclassified between runs while its subject already has a
            # current PART_OF elsewhere -> arity:1 overflow:reject collision. Must dead-letter THAT
            # fact only — fx2's edge (unchanged project) still applies, batch doesn't roll back/crash.
            reclassified = [dict(rows[0], project="Fixture-Project-Reclassified"), rows[1]]
            dl3 = ingest(s, reclassified, [], T1, TNS, ledger_prefix="ledgerfx")
            part_fx1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:fx1'})-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->(o) "
                "WHERE r.invalid_at > datetime() RETURN o.key AS k", ns=TNS).single()["k"])
            print(f"[deadletter] reclassified obs:fx1 -> dead-lettered={dl3} | current PART_OF still={part_fx1}")
            fail += [] if len(dl3) == 1 else [f"expected exactly 1 dead-letter from the arity reject, got {dl3}"]
            fail += [] if part_fx1 == "project:my-portfolio" else \
                [f"arity:1 overflow:reject did not hold: current PART_OF re-anchored to {part_fx1}"]

            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=TNS))

    # FIX bc7/22w: one corrupt jsonl line must dead-letter, not abort the whole ledger read. Pure
    # function, zero file I/O — no real ledger file touched, nothing to clean up.
    fixture_lines = ['{"type": "run", "run_id": "fixture-run-2"}',
                     'not valid json{',
                     '{"type": "run", "run_id": "fixture-run-3"}']
    records, ledger_dl = _parse_ledger_lines(fixture_lines)
    print(f"[deadletter] jsonl parse: {len(records)} record(s) parsed, dead-lettered={ledger_dl}")
    fail += [] if (len(records) == 2 and len(ledger_dl) == 1) else \
        [f"corrupt-line handling wrong: records={len(records)} deadletter={ledger_dl}"]

    print("LLM calls in path: 0 (module imports sqlite3/json/re/neo4j/mutate only — no subprocess/model CLI)")

    gw = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "check_write_gateway.py")],
                        capture_output=True, text=True, cwd=REPO_ROOT)
    print(gw.stdout.strip())
    fail += [] if (gw.returncode == 0 and "WRITE_GATEWAY_OK" in gw.stdout) \
        else [f"check_write_gateway.py did not pass: rc={gw.returncode} {gw.stdout} {gw.stderr}"]

    if fail:
        print("HISTORY_INGEST_FAIL:", fail); sys.exit(1)
    print("HISTORY_INGEST_OK")


# ── --real: real engram.db + real source-ledger.jsonl -> history ns ─────────
def _real():
    import scope
    import serve as serve_mod
    fail = []
    now = datetime.now(timezone.utc).strftime(NOW_FMT)
    ns = "history"

    rows = _real_engram_rows()
    ledger = _real_ledger_records()
    print(f"[read] engram.db builder-guild rows={len(rows)} | source-ledger.jsonl records={len(ledger)}")

    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            ingest(s, rows, ledger, now, ns)
            n_embedded = _embed_history_nodes(s, ns, now)
            counts = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity) WHERE n.namespace=$ns RETURN labels(n) AS labels", ns=ns).data())
            n_edges = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=ns).single()["c"])

    n_obs = sum(1 for c in counts if "Observation" in c["labels"])
    n_src = sum(1 for c in counts if "Source" in c["labels"])
    n_proj = sum(1 for c in counts if "Project" in c["labels"])
    print(f"[embed]  embedded {n_embedded} Observation/Source nodes in ns={ns}")
    print(f"[counts] history ns nodes: Observation={n_obs} Source={n_src} Project={n_proj} "
          f"total={len(counts)} | current PART_OF edges={n_edges}")

    # pick the first real row with a NON-empty title (~1/3 of builder-guild rows have title='') —
    # a blank-title query would not be a meaningful "retrieve by real title" proof.
    target = next((r for r in rows if r["title"]), None)
    if target is None:
        print("HISTORY_SERVE_FAIL: no real engram row has a non-empty title"); sys.exit(1)
    target_key = f"obs:{target['id']}"

    # secondary assert (spec's original proof): direct key lookup -> existence + role-scoped visibility.
    allowed = scope.allowed_namespaces("history")
    card = serve_mod.node_card(target_key, allowed)
    print(f"[node_card] key={target_key} -> node={card and card.get('node')}")
    expect_long = f"{target['title']}\n\n{target['content']}"
    fail += [] if (card and card["node"] == target_key and card["long_context"] == expect_long) \
        else [f"node_card did not round-trip {target_key}"]

    # primary assert (orchestrator directive): an actual RETRIEVAL by the observation's real title —
    # a free-text query, not a key lookup — is what node_card structurally cannot prove.
    result = serve_mod.serve(query_text=target["title"], role="history")
    in_evidence = (result["primary"] == target_key
                   or any(target_key in line for line in result["composed_evidence"]))
    print(f"[serve] query={target['title']!r} role=history -> primary={result['primary']} "
          f"decision={result['decision']} | {target_key} in evidence={in_evidence}")
    fail += [] if in_evidence else [f"serve() did not surface {target_key} for a query on its own real title"]

    print("LLM calls in path: 0 (sqlite3/json read + mutate.py write engine + local EmbeddingGemma embed)")
    if fail:
        print("HISTORY_SERVE_FAIL:", fail); sys.exit(1)
    print("HISTORY_SERVE_OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
    elif "--real" in sys.argv:
        _real()
    else:
        print("usage: etl_history.py --selftest | --real"); sys.exit(2)


if __name__ == "__main__":
    main()
