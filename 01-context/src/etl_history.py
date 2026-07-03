"""etl_history.py (builder-guild-22w): session-history deterministic ingest — dogfood corpus #1.

Ingests THREE REAL local stores into ONE dedicated `history` namespace, ZERO LLM (pure sqlite3/json/re
+ the mutate.py write engine, same convention as etl.py):
  - ~/.engram/engram.db `observations` rows (builder-guild project; env ENGRAM_DB)        -> :Entity:Observation, key obs:<id>
  - ~/.claude-mem/claude-mem.db `observations` rows (buffalo project; env CLAUDE_MEM_DB;
    builder-guild-br7 adapter, 2026-07-03)                                               -> :Entity:Observation, key cmobs:<id>
  - .explore/source-ledger.jsonl records (one per line)                                  -> :Entity:Source
All three group under a :Entity:Project node (key=project:<canon_project(name)>), linked PART_OF — the
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
CLAUDE_MEM_DB = os.environ.get("CLAUDE_MEM_DB", str(Path.home() / ".claude-mem" / "claude-mem.db"))
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


def _real_claude_mem_rows(project="buffalo"):
    """claude-mem.db is LIVE (background worker) — same lock exposure as engram.db, same mitigation:
    ro URI (never takes a write lock) + timeout=5.0 (busy_timeout) + one bounded retry on 'locked'.
    narrative is renamed to content in the returned dict so rows match ingest()'s existing
    row['content'] access unmodified (builder-guild-br7 — no new row shape for ingest() to learn).
    Schema permits NULL title/narrative; a NULL row would ingest the literal 'None' string into
    long_context rather than dead-letter (deliberate: mirrors engram's no-fallback posture; all
    rows non-blank as of the 2026-07-03 checks, but the row count drifts live — 432→459→488)."""
    last_err = None
    for _attempt in range(2):
        try:
            con = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True, timeout=5.0)   # ro URI: never takes a write lock
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT id, project, title, narrative FROM observations WHERE project=? ORDER BY id",
                    (project,)).fetchall()
                return [{"id": r["id"], "project": r["project"], "title": r["title"], "content": r["narrative"]}
                        for r in rows]
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


def _fixture_claude_mem_rows():
    """String ids + fixture-only project name — mirrors _fixture_rows(); a fixture key can never
    collide with a real cmobs:<id> key regardless of run order between --selftest and --real.
    id="1" doubles as the collision-proof fixture in _selftest(): same numeric id as the
    engram-shaped collision row there, disambiguated only by obs_prefix — the ONE deliberately
    numeric fixture id (spec-mandated); every other fixture id stays non-numeric (cmfx*) so it can
    never look like a real sqlite autoincrement id on a fresh/low-count claude-mem.db."""
    return [
        {"id": "1", "title": "Claude-mem collision fixture", "content": "Claude-mem fixture content one.",
         "project": "Fixture-Claude-Mem-Project"},
        {"id": "cmfx2", "title": "Second claude-mem fixture", "content": "Claude-mem fixture content two.",
         "project": "Fixture-Claude-Mem-Project"},
    ]


def _fixture_ledger():
    return [
        {"type": "run", "run_id": "fixture-run-1", "topic": "fixture topic", "ts": "2026-07-01T00:00:00Z"},
        {"type": "finding", "run_id": "fixture-run-1", "claim": "fixture claim", "sub_q": "q1",
         "ts": "2026-07-01T00:01:00Z"},
    ]


# ── ingest (the only writer: mutate.resolve_entity / mutate.apply_edge) ─────
def _resolve_embeddable(tx, label, key, now, ns, short, long_):
    """Observation/Source resolve, PLUS content-change detection for the embed-resume filter (698).
    mutate.resolve_entity's ON-MATCH branch blindly overwrites long_context without touching
    dirty/content_rev (afh's race-fix: a resolve must never clobber a concurrent mark_dirty) — so a
    row whose real content changed between two --real runs would go unnoticed by a dirty-only resume
    filter. Read the PRIOR long_context, resolve, then mark_dirty ONLY if the text actually changed.
    A fresh create is skipped (old is None) — it has no embedding yet, so the resume filter's
    `embedding IS NULL` arm already catches it; marking it dirty too would be redundant, not wrong."""
    old = tx.run("MATCH (n:Entity {key:$key}) RETURN n.long_context AS c", key=key).single()
    old_long = old["c"] if old else None
    mutate.resolve_entity(tx, label, key, now, ns, short=short, long_=long_)
    if old_long is not None and old_long != long_:
        mutate.mark_dirty(tx, key, now)


def ingest(session, rows, ledger, now, ns, ledger_prefix="ledger", obs_prefix="obs"):
    """Entities via mutate.resolve_entity (ONE tx — upsert has no reject axis, so it never rolls back
    on a rejected fact). Edges via mutate.apply_edge(PART_OF), ONE TX PER EDGE (mirrors etl.py's
    ingest()): PART_OF is arity:1+overflow:reject, so a single arity collision (e.g. a row's project
    reclassified between runs while its subject already has a current PART_OF elsewhere) raises
    ValueError — per-edge isolation dead-letters THAT fact instead of rolling back the whole corpus.
    Infra errors (neo4j.exceptions.*) are deliberately NOT caught — they propagate and halt, same as
    etl.py. Returns the dead-letter list (empty = every edge applied).
    ZERO LLM. Idempotent: the same rows/ledger/now converges to the identical graph (resolve_entity
    never bumps content_rev on its own; apply_edge's MERGE re-matches the same current edge instead
    of duplicating; _resolve_embeddable only flips dirty when text actually differs).
    ledger_prefix keys each Source node as f'{ledger_prefix}:{line-index}' — default 'ledger' matches
    --real's line-index scheme; --selftest passes a distinct prefix so its fixture records can never
    collide with a real ledger:<i> key regardless of run order between --selftest and --real.
    obs_prefix keys each Observation node as f'{obs_prefix}:{row["id"]}' — default 'obs' (engram);
    claude-mem rows pass 'cmobs' (builder-guild-br7) so a claude-mem id can never collide with an
    engram id of the same numeric value in the same namespace."""
    def _entities(tx):
        for row in rows:
            _resolve_embeddable(tx, "Observation", f"{obs_prefix}:{row['id']}", now, ns,
                                row["title"], f"{row['title']}\n\n{row['content']}")
            pkey = f"project:{canon_project(row['project'])}"
            mutate.resolve_entity(tx, "Project", pkey, now, ns, short=row["project"], long_=row["project"])
        for i, rec in enumerate(ledger):
            short = rec.get("claim") or rec.get("topic") or rec["type"]
            _resolve_embeddable(tx, "Source", f"{ledger_prefix}:{i}", now, ns,
                                short, json.dumps(rec, sort_keys=True))
            pkey = f"project:{canon_project(rec['run_id'])}"
            mutate.resolve_entity(tx, "Project", pkey, now, ns, short=rec["run_id"], long_=rec["run_id"])
    session.execute_write(_entities)

    edges = [(f"{obs_prefix}:{row['id']}", f"project:{canon_project(row['project'])}") for row in rows]
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


def _embed_history_nodes(session, ns, now, reembed_all=False):
    """Embed Observation/Source nodes in `ns` via embed.embed_node directly. resolve_entity clears
    dirty ON CREATE only (never sets it), so a freshly created node never lands in sweep.py's dirty
    queue — embed it directly rather than round-tripping mark_dirty + sweep_once.

    Resume filter (698, default): only nodes with no embedding yet OR flagged dirty — mirrors
    sweep.sweep_once's `n.dirty=true` selection, plus `embedding IS NULL` for first-time nodes
    (which are never dirty, per the comment above). dirty is now accurate for content edits too:
    _resolve_embeddable (in ingest()) sets it when a row's text actually changes between runs.
    --reembed-all bypasses the filter entirely — use after an embedding-model swap or a chunking/
    text-format change, where every existing vector is stale but embedding/dirty say otherwise."""
    import embed
    resume = "" if reembed_all else " AND (n.embedding IS NULL OR n.dirty=true)"
    rows = session.execute_read(lambda tx: tx.run(
        f"MATCH (n:Entity) WHERE n.namespace=$ns AND (n:Observation OR n:Source){resume} "
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

            # FIX 698: the embed-resume filter trusts dirty to be accurate for content edits, not just
            # sweep.mark_dirty calls. An identical re-ingest (dl2 above) must NOT flip it (no false
            # positive -> no needless re-embed); a REAL content edit on the same key MUST flip it (else
            # the resume filter would silently skip a changed node forever).
            dirty_noop = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:fx1'}) RETURN n.dirty AS d").single()["d"])
            edited = [dict(rows[0], content="Fixture content one, EDITED."), rows[1]]
            ingest(s, edited, ledger, T1, TNS, ledger_prefix="ledgerfx")
            dirty_edit = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:fx1'}) RETURN n.dirty AS d").single()["d"])
            print(f"[dirty]      obs:fx1 dirty: after identical re-ingest={dirty_noop} "
                  f"-> after real content edit={dirty_edit}")
            fail += [] if dirty_noop is False else ["identical re-ingest false-positived dirty=true"]
            fail += [] if dirty_edit is True else \
                ["content edit did not mark dirty — embed-resume filter would silently skip it"]

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

            # ── claude-mem ingest path (builder-guild-br7): same idempotent-re-run shape as the
            # engram block above, exercised through the NEW obs_prefix param. ledger=[] throughout —
            # claude-mem rows carry no ledger records of their own.
            cm_rows = _fixture_claude_mem_rows()
            cm_dl1 = ingest(s, cm_rows, [], T0, TNS, obs_prefix="cmobs")
            cm_rev1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'cmobs:1'}) RETURN n.content_rev AS r").single()["r"])
            cm_edges1 = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=TNS).single()["c"])

            cm_dl2 = ingest(s, cm_rows, [], T0, TNS, obs_prefix="cmobs")   # re-run: SAME fixtures + SAME now -> must be a no-op
            cm_rev2 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'cmobs:1'}) RETURN n.content_rev AS r").single()["r"])
            cm_edges2 = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=TNS).single()["c"])
            print(f"[cm idempotent] content_rev {cm_rev1} -> {cm_rev2} | current PART_OF edges {cm_edges1} -> {cm_edges2}")
            fail += [] if cm_rev1 == cm_rev2 else ["claude-mem content_rev changed across an identical re-ingest"]
            fail += [] if cm_edges1 == cm_edges2 else ["claude-mem current PART_OF edge count changed across re-ingest"]
            fail += [] if not (cm_dl1 or cm_dl2) else \
                [f"unexpected dead-letter on the clean claude-mem fixture corpus: {cm_dl1 or cm_dl2}"]

            # collision proof (clause a): an engram-shaped row and a claude-mem-shaped row (cm_rows[0]
            # above) sharing the SAME numeric id "1" must resolve to two DISTINCT entities (obs:1 vs
            # cmobs:1), each keeping its own fixture's title — proves the key scheme, not just "no crash".
            engram_one = [{"id": "1", "type": "decision", "title": "Engram collision fixture",
                           "content": "Engram collision content.", "project": "Fixture-Collision-Project",
                           "scope": "project", "topic_key": "fx/collision", "created_at": T0}]
            ingest(s, engram_one, [], T0, TNS, obs_prefix="obs")
            obs1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'obs:1'}) RETURN n.short_context AS t").single())
            cmobs1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'cmobs:1'}) RETURN n.short_context AS t").single())
            print(f"[collision] obs:1 title={obs1['t'] if obs1 else None} | "
                  f"cmobs:1 title={cmobs1['t'] if cmobs1 else None}")
            fail += [] if (obs1 and obs1["t"] == "Engram collision fixture") else \
                ["obs:1 missing or wrong title (collision on cmobs?)"]
            fail += [] if (cmobs1 and cmobs1["t"] == "Claude-mem collision fixture") else \
                ["cmobs:1 missing or wrong title (collision on obs?)"]
            fail += [] if (obs1 and cmobs1 and obs1["t"] != cmobs1["t"]) else \
                ["obs:1/cmobs:1 collapsed to one node — key scheme did not disambiguate"]

            # per-row dead-letter on the cmobs path (orchestrator directive): reclassify cmobs:1's
            # project -> PART_OF arity:1 overflow:reject collision must dead-letter, not raise;
            # cm_rows[1]'s edge (unchanged project) still applies — same class as the engram reclassify
            # proof above, run THROUGH obs_prefix="cmobs" to prove it at runtime, not by shared-code argument.
            cm_reclassified = [dict(cm_rows[0], project="Fixture-Claude-Mem-Reclassified"), cm_rows[1]]
            cm_dl3 = ingest(s, cm_reclassified, [], T1, TNS, obs_prefix="cmobs")
            cm_part1 = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity {key:'cmobs:1'})-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->(o) "
                "WHERE r.invalid_at > datetime() RETURN o.key AS k", ns=TNS).single()["k"])
            print(f"[deadletter] reclassified cmobs:1 -> dead-lettered={cm_dl3} | current PART_OF still={cm_part1}")
            fail += [] if len(cm_dl3) == 1 else \
                [f"expected exactly 1 claude-mem dead-letter from the arity reject, got {cm_dl3}"]
            fail += [] if cm_part1 == "project:fixture-claude-mem-project" else \
                [f"claude-mem arity:1 overflow:reject did not hold: current PART_OF re-anchored to {cm_part1}"]

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
    reembed_all = "--reembed-all" in sys.argv

    rows = _real_engram_rows()
    ledger = _real_ledger_records()
    cm_rows = _real_claude_mem_rows()
    print(f"[read] engram.db builder-guild rows={len(rows)} | source-ledger.jsonl records={len(ledger)} "
          f"| claude-mem.db buffalo rows={len(cm_rows)}")

    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            ingest(s, rows, ledger, now, ns)
            ingest(s, cm_rows, [], now, ns, obs_prefix="cmobs")
            n_embedded = _embed_history_nodes(s, ns, now, reembed_all=reembed_all)
            counts = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity) WHERE n.namespace=$ns RETURN labels(n) AS labels", ns=ns).data())
            n_edges = s.execute_read(lambda tx: tx.run(
                "MATCH ()-[r:RELATES_TO {name:'PART_OF', namespace:$ns}]->() "
                "WHERE r.invalid_at > datetime() RETURN count(r) AS c", ns=ns).single()["c"])
            n_cm = s.execute_read(lambda tx: tx.run(
                "MATCH (n:Entity) WHERE n.namespace=$ns AND n.key STARTS WITH 'cmobs:' "
                "RETURN count(n) AS c", ns=ns).single()["c"])

    n_obs = sum(1 for c in counts if "Observation" in c["labels"])
    n_src = sum(1 for c in counts if "Source" in c["labels"])
    n_proj = sum(1 for c in counts if "Project" in c["labels"])
    print(f"[embed]  embedded {n_embedded} Observation/Source nodes in ns={ns} "
          f"(mode={'reembed-all' if reembed_all else 'resume'})")
    print(f"[counts] history ns nodes: Observation={n_obs} Source={n_src} Project={n_proj} "
          f"total={len(counts)} | current PART_OF edges={n_edges} | claude-mem nodes ingested={n_cm}")

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

    # claude-mem retrieval proof (builder-guild-br7 clause e): same free-text-by-real-title proof,
    # over a cmobs:-keyed node this time — one ingest() call, one obs_prefix, same serve() path.
    cm_target = next((r for r in cm_rows if r["title"]), None)
    if cm_target is None:
        print("HISTORY_SERVE_FAIL: no real claude-mem row has a non-empty title"); sys.exit(1)
    cm_target_key = f"cmobs:{cm_target['id']}"
    cm_result = serve_mod.serve(query_text=cm_target["title"], role="history")
    cm_in_evidence = (cm_result["primary"] == cm_target_key
                      or any(cm_target_key in line for line in cm_result["composed_evidence"]))
    print(f"[serve] query={cm_target['title']!r} role=history -> primary={cm_result['primary']} "
          f"decision={cm_result['decision']} | {cm_target_key} in evidence={cm_in_evidence}")
    fail += [] if cm_in_evidence else [f"serve() did not surface {cm_target_key} for a query on its own real title"]

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
        print("usage: etl_history.py --selftest | --real [--reembed-all]\n"
              "  --reembed-all: force full re-embed of every Observation/Source node (default: "
              "resume — only nodes with no embedding yet or flagged dirty). Use after an "
              "embedding-model swap or a chunking/text-format change.")
        sys.exit(2)


if __name__ == "__main__":
    main()
