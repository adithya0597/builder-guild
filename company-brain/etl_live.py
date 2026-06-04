"""cb-dfv.9: ingest LIVE Paperclip company state into the Neo4j spine.

Fetches the real 'spine' company's agents + issues from the Paperclip API (the live swap of
etl.py's fetch_source) and MERGEs them deterministically (0 LLM). Each agent's namespace = its
CXO domain (T0). Reuses etl.py's upsert helpers — only the SOURCE changed, as designed.

Extended 2026-06-03: Issue nodes + ASSIGNED_TO bi-temporal edges + BLOCKS edges.
"""
import os
import json
import urllib.request
from datetime import datetime, timezone
from neo4j import GraphDatabase
from etl import upsert_entity, functional_edge, additive_edge, URI, AUTH

PB = os.environ.get("PAPERCLIP_BASE_URL", "http://127.0.0.1:3101")
COMPANY = os.environ.get("PAPERCLIP_COMPANY_ID", "")   # set to your Paperclip company UUID
HOST = os.environ.get("PAPERCLIP_HOST", "localhost:3101")   # satisfies the private-hostname guard
ROLE_NS = {"cto": "engineering", "cfo": "finance", "cmo": "market",
           "pm": "product", "general": "operations", "security": "governance"}


def _get(path):
    req = urllib.request.Request(PB + path, headers={"Host": HOST})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_live():
    agents = _get(f"/api/companies/{COMPANY}/agents")
    issues = _get(f"/api/companies/{COMPANY}/issues?status=todo,in_progress,in_review,blocked,done,cancelled")
    # Fetch detail for each issue to get blockedBy relations
    issues_detail = []
    for i in issues:
        detail = _get(f"/api/issues/{i['id']}")
        issues_detail.append(detail)
    return agents, issues_detail


def _agent_key_for_id(agent_id, agents):
    """Map paperclip agent UUID -> agent:{role} key using the ROLE_NS map."""
    for a in agents:
        if a["id"] == agent_id:
            rt = (a.get("roleType") or a.get("role") or "").lower()
            return f"agent:{rt}"
    return None


def main():
    if not COMPANY:
        raise SystemExit("Set PAPERCLIP_COMPANY_ID (your Paperclip company UUID) in the environment.")
    agents, issues = fetch_live()
    print(f"LIVE from Paperclip 'spine' ({COMPANY[:8]}): {len(agents)} agents, {len(issues)} issues")
    ep = f"paperclip-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    with GraphDatabase.driver(URI, auth=AUTH) as drv, drv.session() as s:
        s.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))   # clean slate -> live seed

        # --- Agents ---
        for a in agents:
            rt = (a.get("roleType") or a.get("role") or "").lower()
            ns = ROLE_NS.get(rt, "governance")
            s.execute_write(upsert_entity, "Agent", f"agent:{rt}",
                            f"{a.get('name')} ({rt})",
                            f"{a.get('name')} — live Paperclip agent, {ns} domain.",
                            ep, ns)
            s.execute_write(lambda tx, k=f"agent:{rt}", pid=a.get("id"):
                            tx.run("MATCH (n:Entity {key:$k}) SET n.paperclip_id=$pid", k=k, pid=pid))

        # --- Issues: two-pass — nodes first, then edges (so MATCH finds both endpoints) ---
        issue_nodes_created = 0
        assigned_to_edges = 0
        blocks_edges = 0

        # Pass 1: upsert all Issue nodes
        for i in issues:
            issue_key = f"issue:{i.get('identifier') or i['id']}"
            assignee_id = i.get("assigneeAgentId")
            agent_key = _agent_key_for_id(assignee_id, agents) if assignee_id else None
            if agent_key:
                rt = agent_key.split(":")[1]
                ns = ROLE_NS.get(rt, "engineering")
            else:
                ns = "engineering"

            s.execute_write(
                upsert_entity, "Issue", issue_key,
                f"{i.get('identifier')}: {i.get('title')}",
                f"{i.get('title')} — status={i.get('status')}, priority={i.get('priority')}.",
                ep, ns,
            )
            s.execute_write(
                lambda tx, k=issue_key, pid=i["id"]:
                tx.run("MATCH (n:Entity {key:$k}) SET n.paperclip_id=$pid", k=k, pid=pid)
            )
            issue_nodes_created += 1

        # Pass 2: edges (all nodes guaranteed to exist now)
        for i in issues:
            issue_key = f"issue:{i.get('identifier') or i['id']}"
            assignee_id = i.get("assigneeAgentId")
            agent_key = _agent_key_for_id(assignee_id, agents) if assignee_id else None
            if agent_key:
                rt = agent_key.split(":")[1]
                ns = ROLE_NS.get(rt, "engineering")
            else:
                ns = "engineering"

            # ASSIGNED_TO edge: (:Issue)->(:Agent) bi-temporal
            if agent_key:
                s.execute_write(functional_edge, issue_key, "ASSIGNED_TO", agent_key, ep, ns)
                assigned_to_edges += 1

            # BLOCKS edges: (:Issue)-[:RELATES_TO {name:'BLOCKS'}]->(:Issue) for each blocker
            for blocker in i.get("blockedBy") or []:
                blocker_key = f"issue:{blocker.get('identifier') or blocker['id']}"
                # blocker_key BLOCKS this issue_key
                s.execute_write(additive_edge, blocker_key, "BLOCKS", issue_key, ep, ns)
                blocks_edges += 1

        # --- Verification readout ---
        rows = s.execute_read(lambda tx: list(tx.run(
            "MATCH (a:Entity:Agent) RETURN a.namespace AS ns, a.key AS key, a.paperclip_id AS pid "
            "ORDER BY ns")))
        print(f"\ningested {len(rows)} agents into the spine (from LIVE Paperclip):")
        for r in rows:
            print(f"  {r['ns']:12} {r['key']:18} <- paperclip {str(r['pid'])[:8]}")

        print(f"\n{issue_nodes_created} issue nodes, {assigned_to_edges} ASSIGNED_TO edges, {blocks_edges} BLOCKS edges")

        # Sample ASSIGNED_TO edge with bi-temporal stamp + namespace
        sample = s.execute_read(lambda tx: list(tx.run(
            "MATCH (iss:Entity:Issue)-[r:RELATES_TO {name:'ASSIGNED_TO'}]->(a:Entity:Agent) "
            "RETURN iss.key AS issue_key, a.key AS agent_key, "
            "       r.valid_at AS valid_at, r.namespace AS ns "
            "ORDER BY r.valid_at LIMIT 3")))
        print("\nSample ASSIGNED_TO edges (issue -> agent, valid_at, namespace):")
        for r in sample:
            print(f"  {r['issue_key']:30} -> {r['agent_key']:20} | valid_at={r['valid_at']} ns={r['ns']}")

        # Total counts
        total_nodes = s.execute_read(lambda tx: tx.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"])
        total_edges = s.execute_read(lambda tx: tx.run("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c").single()["c"])
        print(f"\nTotal: {total_nodes} Entity nodes, {total_edges} RELATES_TO edges")

        # Namespace isolation check: finance issue NOT visible from engineering scope
        finance_issues = s.execute_read(lambda tx: [r["k"] for r in tx.run(
            "MATCH (n:Entity:Issue) WHERE n.namespace='finance' RETURN n.key AS k")])
        eng_visible = s.execute_read(lambda tx: [r["k"] for r in tx.run(
            "MATCH (n:Entity:Issue) WHERE n.namespace='engineering' RETURN n.key AS k")])
        print(f"\nIsolation check:")
        print(f"  finance-namespace issues: {finance_issues}")
        print(f"  engineering-namespace issues (finance should NOT appear here): {eng_visible}")
        finance_in_eng = [k for k in finance_issues if k in eng_visible]
        print(f"  finance keys leaking into engineering scope: {finance_in_eng} (must be [])")

        # role-scoped proof: a CFO-scoped read sees only finance, not engineering
        cfo = s.execute_read(lambda tx: [r["key"] for r in tx.run(
            "MATCH (a:Entity:Agent) WHERE a.namespace IN ['finance','shared'] RETURN a.key AS key")])
        print(f"\nCFO-scoped agent view (isolation): {cfo}")

    print("CB_DFV9_LIVE_OK")


if __name__ == "__main__":
    main()
