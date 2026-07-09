"""Agent-facing MCP server (builder-guild-087): bounded read-only planning + suggest-only staging.

Exactly two tools, both bound to this process's role/namespace from the environment (never the
caller):
  - plan_context — the bounded agentic-RAG planner loop (read-only; serve() under the hood).
  - propose_edge — stage ONE low-trust candidate edge into this server's bound staging namespace.

propose_edge is the SUGGEST end of the ingest truth-gate: it can only ever create a pending
:Candidate. Turning a candidate into a real graph edge is a separate, human-only review step run
from the staging module's own CLI — deliberately never surfaced as a tool here. This server imports
no edge-write engine at all, so it is structurally incapable of writing a graph edge.

Role is bound from BG_MCP_ROLE and the staging namespace from BG_STAGE_NS, both validated fail-fast
in __main__ before mcp.run(). No tool accepts a role/namespace argument, so a client-supplied one
has no field to land in and is dropped by FastMCP's generated (pydantic) input schema.

Run under the 01-context venv, e.g.:
    BG_MCP_ROLE=engineering BG_STAGE_NS=engineering \
        01-context/.venv/bin/python 02-agents/src/mcp_stage_server.py
FastMCP.run() defaults to stdio transport.
"""
import os
import sys
# demo_agent.py:10-12 pattern — staging/scope live in 01-context/src, this file in 02-agents/src;
# planner.py lives alongside this file. Two inserts mirror mcp_server.py:17-18.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "01-context", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from neo4j import GraphDatabase
from mcp.server.fastmcp import FastMCP

import staging     # stage_llm (the suggest-only ingest entrypoint) + reuse staging.URI/staging.AUTH
import scope       # ROLE_NAMESPACES / allowed_namespaces — the isolation boundary
import planner     # the bounded agentic-RAG loop; resolves via the second sys.path.insert above

ROLE = os.environ.get("BG_MCP_ROLE")        # unvalidated at import (CI import-smoke globs this file
STAGE_NS = os.environ.get("BG_STAGE_NS")    # with neither var set); both validated in __main__ below
MAX_STEPS_CAP = 8

mcp = FastMCP("builder-guild-context-agent")


@mcp.tool()
def propose_edge(s_key: str, rel: str, o_key: str, evidence: str | None = None,
                 source: str | None = None) -> str:
    """Stage ONE llm-origin candidate edge into this server's bound staging namespace.
    Returns the deterministic cand_id. Can only ever create a pending candidate; moving it to a
    real edge is a separate human review step run from the staging module's own CLI (never exposed
    here). Re-proposing the identical (s_key, rel, o_key) is idempotent and does NOT update
    evidence/source on an already-staged candidate (first-write-wins, same as the underlying gate)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with GraphDatabase.driver(staging.URI, auth=staging.AUTH) as drv, drv.session() as s:
        return staging.stage_llm(
            s, [(s_key, rel, o_key, STAGE_NS, None, evidence, source)], now)[0]


@mcp.tool()
def plan_context(question: str, max_steps: int = 4) -> dict:
    """Bounded agentic-RAG planning loop over this server's bound role. Self-chooses
    id_extract/graph_pattern/neighbor_hop/decompose retrieval probes from each step's serve()
    signal. Returns planner.plan()'s full envelope verbatim (serve fields from the terminating step
    + "planner": {steps[], distinct_retrievals, terminated_on, steps_used, max_steps}) — no
    post-filtering, no gate bypass. max_steps is capped server-side at 8 regardless of the request."""
    # floor at 1: planner.plan uses range(1, max_steps+1), which is EMPTY for max_steps<=0 and would
    # return a malformed/empty envelope over MCP. Clamp both ends at the tool boundary.
    return planner.plan(question, ROLE, max_steps=max(1, min(max_steps, MAX_STEPS_CAP)))


if __name__ == "__main__":
    if ROLE not in scope.ROLE_NAMESPACES:
        sys.exit(f"BG_MCP_ROLE must be set to one of {sorted(scope.ROLE_NAMESPACES)}; got {ROLE!r}. "
                 f"Example: BG_MCP_ROLE=engineering BG_STAGE_NS=engineering "
                 f"01-context/.venv/bin/python 02-agents/src/mcp_stage_server.py")
    if STAGE_NS is None:
        sys.exit("BG_STAGE_NS must be set (the staging namespace propose_edge writes candidates "
                 "into). Example: BG_STAGE_NS=engineering")
    if STAGE_NS not in scope.allowed_namespaces(ROLE):
        sys.exit(f"BG_STAGE_NS={STAGE_NS!r} is not in role {ROLE!r}'s allowed namespaces "
                 f"{scope.allowed_namespaces(ROLE)}")
    mcp.run()
