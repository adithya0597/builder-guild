"""GraphRAG community summaries.

Per-namespace Leiden community detection over the intra-namespace subgraph.
Build-time isolation: Leiden runs WITHIN each namespace only; cross-namespace edges
are EXCLUDED by the Cypher query. Every :Community node and :IN_COMMUNITY edge
carries `namespace`. assert_no_cross_namespace_community() is the structural proof.

$0/local: leidenalg + python-igraph primary; networkx greedy_modularity_communities fallback.
SUMMARY_CMD unset => detection-only (communities written, summaries skipped).
`now` and `run_id` are EXPLICIT args — never wall-clock-ambient (ONTOLOGY §10 guardrail 1).
"""
import os
import sys

NAMESPACES = ["engineering", "product", "finance", "market", "operations", "governance", "shared"]

# --- Leiden / fallback community detection -----------------------------------

def _leiden_partition(node_keys, edges, resolution):
    """leidenalg primary. Returns list of sets of node keys."""
    import igraph as ig
    import leidenalg

    g = ig.Graph()
    idx = {k: i for i, k in enumerate(node_keys)}
    g.add_vertices(len(node_keys))
    g.vs["name"] = list(node_keys)
    edge_list = [(idx[a], idx[b]) for a, b in edges if a in idx and b in idx]
    g.add_edges(edge_list)

    part = leidenalg.find_partition(
        g,
        leidenalg.RBConfigurationVertexPartition,
        resolution_parameter=resolution,
        seed=42,
    )
    result = []
    for community in part:
        members = {g.vs[i]["name"] for i in community}
        result.append(members)
    return result, "leidenalg"


def _nx_partition(node_keys, edges):
    """networkx greedy_modularity_communities fallback."""
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(node_keys)
    g.add_edges_from([(a, b) for a, b in edges if a in node_keys and b in node_keys])
    # greedy_modularity_communities is deterministic (greedy); networkx 3.6 has NO seed kwarg
    # (codex review GraphRAG communities HIGH: seed=42 raised TypeError so the fallback never ran). Enforce a
    # stable order ourselves: by size desc, then sorted members.
    communities = nx.algorithms.community.greedy_modularity_communities(g)
    out = [set(c) for c in communities]
    out.sort(key=lambda s: (-len(s), sorted(s)))
    return out, "networkx_greedy_modularity"


def _detect_communities(node_keys, edges, resolution, algo):
    """Choose algo. Returns (list[set[str]], algo_label)."""
    if algo == "leiden":
        return _leiden_partition(node_keys, edges, resolution)
    if algo == "networkx":
        return _nx_partition(node_keys, edges)
    # algo == "auto"
    try:
        return _leiden_partition(node_keys, edges, resolution)
    except ImportError:
        return _nx_partition(node_keys, edges)


# --- Cypher helpers ----------------------------------------------------------

def _delete_ns_communities(session, ns):
    """Full rebuild: wipe :Community nodes for this namespace BY namespace OR by key-prefix, so a
    stale/orphan community carrying null or a wrong namespace but this ns's key is also swept
    (codex review GraphRAG communities MED: a null-namespace orphan survived a namespace-only delete)."""
    session.run(
        "MATCH (c:Community) WHERE c.namespace = $ns OR c.key STARTS WITH $prefix DETACH DELETE c",
        ns=ns, prefix=f"community:{ns}:",
    )


def _write_community(session, ns, cid, member_keys, now, run_id):
    """Write one :Community node (MERGE on key) + :IN_COMMUNITY edges for each member.

    CYPHER SAFETY:
      - No null in MERGE pattern. Nullable fields (summary etc.) set via SET only.
      - Vars bound in ONE statement each.
      - All values param-bound.
    """
    comm_key = f"community:{ns}:{cid}"
    n = len(member_keys)

    # Write the Community node
    session.run(
        "MERGE (c:Community {key: $key}) "
        "SET c.namespace = $ns, "
        "    c.member_count = $n, "
        "    c.built_at = $now, "
        "    c.run_id = $run_id",
        key=comm_key,
        ns=ns,
        n=n,
        now=now,
        run_id=run_id,
    )

    # Write membership edges: one statement per member
    for mk in member_keys:
        session.run(
            "MATCH (e:Entity {key: $mk}), (c:Community {key: $ck}) "
            "MERGE (e)-[m:IN_COMMUNITY]->(c) "
            "SET m.namespace = $ns",
            mk=mk,
            ck=comm_key,
            ns=ns,
        )


# --- Optional summarize step -------------------------------------------------

def _summarize_community(session, ns, cid, member_keys, ckpt):
    """Summarize one community via summarize_adapter. Returns summary text or None."""
    import summarize_adapter

    # Gather member short_context lines
    member_texts = []
    for mk in member_keys:
        rec = session.run(
            "MATCH (e:Entity {key: $k}) RETURN coalesce(e.short_context, e.key) AS sc",
            k=mk,
        ).single()
        if rec:
            member_texts.append(rec["sc"])

    # Gather intra-community fact names
    fact_lines = []
    for mk in member_keys:
        rows = session.run(
            "MATCH (a:Entity {key: $mk})-[r:RELATES_TO]->(b:Entity) "
            "WHERE b.key IN $members AND r.namespace = $ns AND r.invalid_at > datetime() "
            "RETURN r.name AS name, b.key AS target",
            mk=mk,
            members=list(member_keys),
            ns=ns,
        ).data()
        for row in rows:
            fact_lines.append(f"{row['name']} -> {row['target']}")

    ck_key = f"community:{ns}:{cid}"
    return summarize_adapter.summarize(member_texts, fact_lines, key=ck_key, ckpt=ckpt)


# --- Main public function ----------------------------------------------------

def build_communities(
    session,
    *,
    namespaces=None,
    resolution=1.0,
    algo="auto",
    summarize=False,
    run_id="manual",
    now=None,
    min_size=1,
    ckpt=None,
):
    """Per-namespace Leiden + write :Community (+membership) + optional summaries.

    `now` REQUIRED-explicit when summarize/stamp matters (ONTOLOGY §10 guardrail 1 —
    no wall-clock default in the logic path). Callers should pass now=datetime.utcnow().isoformat()
    or a fixed string for reproducible tests.

    Returns {ns: {"n_nodes": int, "n_edges": int, "n_communities": int,
                  "n_summarized": int, "algo": str}}.
    """
    if namespaces is None:
        namespaces = NAMESPACES

    # Explicit clock — REQUIRED on the write path (ONTOLOGY §10 guardrail 1). Raise rather than
    # silently stamp a sentinel (codex review GraphRAG communities MED: 'unset' permitted non-reproducible writes).
    if now is None:
        raise ValueError("build_communities: `now` is required (explicit clock) — pass a fixed/ISO "
                         "timestamp string; no wall-clock-ambient or sentinel writes")

    results = {}

    for ns in namespaces:
        # --- Step 1: pull intra-namespace subgraph ---
        rows = session.run(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            "WHERE a.namespace = $ns "
            "  AND r.namespace = $ns "
            "  AND b.namespace = $ns "
            "  AND r.invalid_at > datetime() "
            "RETURN a.key AS src, b.key AS dst",
            ns=ns,
        ).data()

        edges = [(r["src"], r["dst"]) for r in rows]
        node_set = set()
        for r in rows:
            node_set.add(r["src"])
            node_set.add(r["dst"])

        # Also include isolated nodes (have no edges) so they form singleton communities
        iso_rows = session.run(
            "MATCH (n:Entity {namespace: $ns}) RETURN n.key AS k",
            ns=ns,
        ).data()
        for r in iso_rows:
            node_set.add(r["k"])

        node_keys = sorted(node_set)  # deterministic ordering
        n_nodes = len(node_keys)
        n_edges = len(edges)

        # --- Step 2: detect communities ---
        if n_nodes == 0:
            results[ns] = {"n_nodes": 0, "n_edges": 0, "n_communities": 0, "n_summarized": 0, "algo": algo}
            continue

        communities, algo_used = _detect_communities(node_keys, edges, resolution, algo)
        communities = [c for c in communities if len(c) >= min_size]

        # --- Step 3: full rebuild (idempotent) ---
        _delete_ns_communities(session, ns)

        n_summarized = 0
        for i, member_set in enumerate(communities):
            cid = str(i)
            _write_community(session, ns, cid, member_set, now, run_id)

            # --- Step 4: optional summarize ---
            if summarize:
                summary = _summarize_community(session, ns, cid, member_set, ckpt)
                if summary is not None:
                    comm_key = f"community:{ns}:{cid}"
                    # Read the model from env at write time — there is no module model global
                    # (codex review GraphRAG communities MED: summarized_by stamped 'unknown' even when set).
                    session.run(
                        "MATCH (c:Community {key: $key}) "
                        "SET c.summary = $summary, "
                        "    c.summary_at = $now, "
                        "    c.summarized_by = $model",
                        key=comm_key,
                        summary=summary,
                        now=now,
                        model=os.environ.get("SUMMARY_MODEL") or "unknown",
                    )
                    n_summarized += 1

        results[ns] = {
            "n_nodes": n_nodes,
            "n_edges": n_edges,
            "n_communities": len(communities),
            "n_summarized": n_summarized,
            "algo": algo_used,
        }

    return results


# --- Role-scoped read --------------------------------------------------------

def community_summary(session, node_key, allowed):
    """Role-scoped read.

    Returns {"community": key, "namespace": ns, "summary": text|None, "member_count": int}
    when the node's community namespace is in `allowed`, else None.

    Defense-in-depth: the WHERE c.namespace IN $allowed filter enforces read-side isolation
    atop the build-time guarantee (every :Community carries exactly its build namespace).
    """
    rec = session.run(
        "MATCH (e:Entity {key: $k})-[:IN_COMMUNITY]->(c:Community) "
        "WHERE c.namespace IN $allowed "
        "RETURN c.key AS community, c.namespace AS namespace, "
        "       c.summary AS summary, c.member_count AS member_count",
        k=node_key,
        allowed=list(allowed),
    ).single()

    if rec is None:
        return None
    return dict(rec)


# --- Isolation proof ---------------------------------------------------------

def assert_no_cross_namespace_community(session) -> list:
    """Structural isolation proof.

    Returns [] iff every :Community has single-namespace membership.
    A non-empty list contains community keys that have members from >1 namespace
    — the cardinal bug (cross-namespace community formed at build).

    Checks that for every :Community node, all :Entity nodes that hold
    :IN_COMMUNITY edges into it share exactly one namespace value, AND that
    namespace equals the community's own namespace field.
    """
    # Start from ALL :Community (OPTIONAL MATCH members) so memberless ghosts are caught, and check
    # the membership EDGE namespace too — not just the node namespace (codex review GraphRAG communities HIGH:
    # the prior query required a member edge and ignored m.namespace, so it was a hollow proof).
    rows = session.run(
        "MATCH (c:Community) "
        "OPTIONAL MATCH (e:Entity)-[m:IN_COMMUNITY]->(c) "
        "WITH c, collect(DISTINCT e.namespace) AS member_ns, "
        "        count(m) AS n_edges, count(m.namespace) AS n_edges_with_ns, "  # count() ignores nulls
        "        collect(DISTINCT m.namespace) AS edge_ns "
        "WHERE c.namespace IS NULL "                            # community missing its namespace
        "   OR size(member_ns) = 0 "                            # orphan: no members
        "   OR size(member_ns) > 1 "                            # members span >1 namespace
        "   OR member_ns[0] <> c.namespace "                    # member ns != community ns
        "   OR n_edges_with_ns < n_edges "                       # some membership edge has a NULL namespace (codex iter2 HIGH)
        "   OR any(x IN edge_ns WHERE x <> c.namespace) "       # some membership-edge ns != community ns
        "RETURN c.key AS community_key, c.namespace AS community_ns, "
        "       member_ns AS member_namespaces, edge_ns AS edge_namespaces"
    ).data()
    return rows


# --- Demo (T1–T7 acceptance tests) ------------------------------------------

def demo():
    """Run T1–T7 acceptance tests against the local Neo4j graph.
    Prints COMMUNITIES_OK on all-pass; exits 1 on any failure.
    cwd must be 01-context/src when running (sibling imports).
    """
    import os
    from neo4j import GraphDatabase

    URI = "bolt://localhost:7687"
    AUTH = ("neo4j", "companybrain")
    FIXED_NOW = "2026-06-14T00:00:00"
    FIXED_RUN = "demo-run-1"

    failures = []

    def fail(tag, msg):
        print(f"  FAIL [{tag}]: {msg}")
        failures.append(tag)

    def ok(tag, msg=""):
        print(f"  OK   [{tag}]{': ' + msg if msg else ''}")

    print("[demo] Connecting to Neo4j...")
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:

        # --- T5: detection-only ($0, SUMMARY_CMD unset) ---
        print("[T5] SUMMARY_CMD unset => no model call, communities written...")
        orig_cmd = os.environ.pop("SUMMARY_CMD", None)
        try:
            result = build_communities(
                s,
                namespaces=NAMESPACES,
                resolution=1.0,
                algo="auto",
                summarize=False,
                run_id=FIXED_RUN,
                now=FIXED_NOW,
            )
        finally:
            if orig_cmd is not None:
                os.environ["SUMMARY_CMD"] = orig_cmd

        total_summarized = sum(v["n_summarized"] for v in result.values())
        if total_summarized == 0:
            ok("T5", f"n_summarized={total_summarized} (no model call)")
        else:
            fail("T5", f"expected n_summarized==0, got {total_summarized}")

        print("[demo] Per-namespace community counts:")
        for ns, info in result.items():
            print(f"  {ns}: nodes={info['n_nodes']} edges={info['n_edges']} "
                  f"communities={info['n_communities']} algo={info['algo']}")

        # --- T1: assert_no_cross_namespace_community == [] ---
        print("[T1] Checking cross-namespace isolation...")
        violations = assert_no_cross_namespace_community(s)
        if violations == []:
            ok("T1", "no cross-namespace communities")
        else:
            fail("T1", f"violations found: {violations}")

        # --- T2: total n_communities > 0 ---
        print("[T2] Checking communities exist...")
        total_communities = sum(v["n_communities"] for v in result.values())
        if total_communities > 0:
            ok("T2", f"total n_communities={total_communities}")
        else:
            fail("T2", "no communities formed (expected > 0 on seeded graph)")

        # --- T3: role-scoped read ---
        print("[T3] Role-scoped read...")
        eng_node = "issue:SPI-1"  # known engineering node from seeded ACME graph
        r_allowed = community_summary(s, eng_node, ["engineering", "shared"])
        r_denied = community_summary(s, eng_node, ["finance", "shared"])

        if r_allowed is not None:
            ok("T3a", f"eng node readable with engineering role: community={r_allowed['community']}")
        else:
            fail("T3a", f"expected result for eng node with ['engineering','shared'], got None")

        if r_denied is None:
            ok("T3b", "eng node not readable with finance-only role")
        else:
            fail("T3b", f"expected None for eng node with ['finance','shared'], got {r_denied}")

        # --- T4: adapter $0-or-STOP on PROVIDER-originated auth/payment output ---
        # Stub subprocess.run so the stop phrase comes from the (fake) PROVIDER, not echoed input
        # (codex review GraphRAG communities MED: echoing the input back was circular, not adversarial).
        print("[T4] Adapter STOP on provider auth/payment output (stubbed subprocess)...")
        import summarize_adapter

        class _FakeProc:
            def __init__(self, out):
                self.stdout, self.stderr = out, ""

        stop_phrases = ["payment required", "billing issue", "quota reached",
                        "authentication required", "api key required"]
        os.environ["SUMMARY_CMD"] = "/bin/echo"
        os.environ.pop("SUMMARY_MODEL", None)
        orig_run = summarize_adapter.subprocess.run
        t4_ok = True
        try:
            for phrase in stop_phrases:
                summarize_adapter.subprocess.run = lambda *a, _p=phrase, **k: _FakeProc(_p)
                raised = False
                try:
                    summarize_adapter.summarize(["a member"], ["FACT -> issue:x"], key="t4", ckpt=None)
                except RuntimeError:
                    raised = True
                if not raised:
                    fail("T4", f"no RuntimeError for provider stop phrase {phrase!r}")
                    t4_ok = False
        finally:
            summarize_adapter.subprocess.run = orig_run
            os.environ.pop("SUMMARY_CMD", None)
        if t4_ok:
            ok("T4", f"all {len(stop_phrases)} provider stop-phrases raised RuntimeError")

        # --- T6: idempotent (re-run yields same n_communities, no duplicates) ---
        print("[T6] Idempotency check (re-run)...")
        result2 = build_communities(
            s,
            namespaces=NAMESPACES,
            resolution=1.0,
            algo="auto",
            summarize=False,
            run_id=FIXED_RUN,
            now=FIXED_NOW,
        )
        ok_idem = True
        for ns in NAMESPACES:
            n1 = result[ns]["n_communities"]
            n2 = result2[ns]["n_communities"]
            if n1 != n2:
                fail("T6", f"ns={ns}: first={n1} second={n2} (not idempotent)")
                ok_idem = False

        # Check no duplicate Community nodes
        dup_rows = s.run(
            "MATCH (c:Community) "
            "WITH c.key AS k, count(c) AS cnt "
            "WHERE cnt > 1 "
            "RETURN k, cnt"
        ).data()
        if dup_rows:
            fail("T6", f"duplicate Community nodes: {dup_rows}")
            ok_idem = False

        # No null-namespace orphan communities should survive a full rebuild (codex review GraphRAG communities MED)
        null_ns = s.run("MATCH (c:Community) WHERE c.namespace IS NULL RETURN count(c) AS n").single()["n"]
        if null_ns > 0:
            fail("T6", f"{null_ns} orphan :Community with null namespace survived rebuild")
            ok_idem = False

        if ok_idem:
            ok("T6", "idempotent — same counts, no duplicates, no null-ns orphans")

        # --- T7: clock explicit ---
        print("[T7] Explicit clock check...")
        built_at_rows = s.run(
            "MATCH (c:Community) WHERE c.built_at IS NOT NULL "
            "RETURN distinct c.built_at AS bat LIMIT 5"
        ).data()
        if built_at_rows:
            bat = built_at_rows[0]["bat"]
            if bat == FIXED_NOW:
                ok("T7", f"built_at={bat} matches FIXED_NOW")
            else:
                fail("T7", f"built_at={bat!r} != FIXED_NOW={FIXED_NOW!r}")
        else:
            fail("T7", "no Community nodes with built_at found")

        # --- T8: summarize=True write path (stubbed provider returns a summary) ---
        print("[T8] summarize=True write path (stubbed provider)...")
        import tempfile
        os.environ["SUMMARY_CMD"] = "/bin/echo"
        os.environ["SUMMARY_MODEL"] = "stub-model-v1"
        orig_run8 = summarize_adapter.subprocess.run
        summarize_adapter.subprocess.run = lambda *a, **k: _FakeProc("a concise community summary")
        ck8 = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        try:
            build_communities(s, namespaces=["finance"], algo="auto", summarize=True,
                              run_id=FIXED_RUN, now=FIXED_NOW, ckpt=ck8)
            srec = s.run("MATCH (c:Community {namespace:'finance'}) WHERE c.summary IS NOT NULL "
                         "RETURN c.summary AS summ, c.summarized_by AS by, c.summary_at AS at "
                         "LIMIT 1").single()
        finally:
            summarize_adapter.subprocess.run = orig_run8
            os.environ.pop("SUMMARY_CMD", None)
            os.environ.pop("SUMMARY_MODEL", None)
        if srec and srec["summ"] and srec["by"] == "stub-model-v1" and srec["at"] == FIXED_NOW:
            ok("T8", f"summary written; summarized_by={srec['by']!r} (env model, not 'unknown'); "
                     f"summary_at={srec['at']}")
        else:
            fail("T8", f"summarize write wrong: {dict(srec) if srec else None}")

        # --- T9: networkx fallback path actually RUNS (codex HIGH: seed kwarg broke it) ---
        print("[T9] networkx fallback runs + isolates...")
        os.environ.pop("SUMMARY_CMD", None)
        res9 = build_communities(s, namespaces=["engineering"], algo="networkx",
                                summarize=False, run_id=FIXED_RUN, now=FIXED_NOW)
        nx_viol = assert_no_cross_namespace_community(s)
        if (res9["engineering"]["algo"] == "networkx_greedy_modularity"
                and res9["engineering"]["n_communities"] > 0 and nx_viol == []):
            ok("T9", f"networkx fallback: {res9['engineering']['n_communities']} communities, no cross-ns")
        else:
            fail("T9", f"networkx fallback broken: {res9['engineering']}, violations={nx_viol}")

        # --- T10: the isolation proof actually CATCHES planted violations (codex HIGH-2: the prior
        # proof was hollow). Plant each violation type, assert detection, then clean up. ---
        print("[T10] isolation proof catches planted violations...")
        t10_ok = True

        def _caught(key):
            return any(v["community_key"] == key for v in assert_no_cross_namespace_community(s))

        # (a) memberless ghost community
        s.run("CREATE (:Community {key:'community:engineering:GHOST', namespace:'engineering'})")
        if not _caught("community:engineering:GHOST"):
            fail("T10a", "memberless ghost community NOT caught"); t10_ok = False
        s.run("MATCH (c:Community {key:'community:engineering:GHOST'}) DETACH DELETE c")

        # (b) membership edge stamped with the WRONG namespace (member node ns matches, edge ns doesn't)
        s.run("MATCH (e:Entity {key:'issue:SPI-1'}) "
              "CREATE (e)-[:IN_COMMUNITY {namespace:'finance'}]->"
              "(:Community {key:'community:engineering:BADEDGE', namespace:'engineering'})")
        if not _caught("community:engineering:BADEDGE"):
            fail("T10b", "wrong-namespace membership edge NOT caught"); t10_ok = False
        s.run("MATCH (c:Community {key:'community:engineering:BADEDGE'}) DETACH DELETE c")

        # (c) community with NULL namespace
        s.run("MATCH (e:Entity {key:'issue:SPI-1'}) "
              "CREATE (e)-[:IN_COMMUNITY {namespace:'engineering'}]->(:Community {key:'community:NULLNS'})")
        if not _caught("community:NULLNS"):
            fail("T10c", "null-namespace community NOT caught"); t10_ok = False
        s.run("MATCH (c:Community {key:'community:NULLNS'}) DETACH DELETE c")

        # (d) membership edge with NO namespace property at all — collect(DISTINCT) drops null,
        # so the proof must catch it via the count(m) vs count(m.namespace) check (codex iter2 HIGH).
        s.run("MATCH (e:Entity {key:'issue:SPI-1'}) "
              "CREATE (e)-[:IN_COMMUNITY]->(:Community {key:'community:engineering:NULLEDGE', namespace:'engineering'})")
        if not _caught("community:engineering:NULLEDGE"):
            fail("T10d", "null-namespace membership edge NOT caught"); t10_ok = False
        s.run("MATCH (c:Community {key:'community:engineering:NULLEDGE'}) DETACH DELETE c")

        # after cleanup the proof must be clean again
        residual = assert_no_cross_namespace_community(s)
        if residual:
            fail("T10", f"residual violations after cleanup: {residual}"); t10_ok = False
        if t10_ok:
            ok("T10", "ghost + wrong-edge-ns + null-ns all caught, then cleaned (proof is real)")

    # --- Final verdict ---
    print()
    if not failures:
        print("COMMUNITIES_OK")
    else:
        print(f"COMMUNITIES_FAIL: {failures}")
        sys.exit(1)


if __name__ == "__main__":
    demo()
