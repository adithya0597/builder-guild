"""Read-only MCP server over serve() (builder-guild-9fe).

Role is bound server-side from BG_MCP_ROLE at process start; no tool below accepts a
role/namespace parameter, so a client-supplied one has no field to land in and is
silently dropped by FastMCP's generated (pydantic) input schema. This is the
confidentiality bright line from serve.py:129-130 — role must never come from the
caller. Zero write-capable tools: every tool below only ever reads.

Run under the 01-context venv, e.g.:
    BG_MCP_ROLE=engineering 01-context/.venv/bin/python 02-agents/src/mcp_server.py
FastMCP.run() defaults to stdio transport.
"""
import json
import os
import sys
# demo_agent.py:10-12 pattern — serve/scope live in 01-context/src, this file in 02-agents/src.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "01-context", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neo4j import GraphDatabase
from mcp.server.fastmcp import FastMCP

from serve import serve as _serve, node_card as _node_card
import scope

ROLE = os.environ.get("BG_MCP_ROLE")  # resolved lazily so import stays side-effect-free (CI's
# import-all-modules smoke check); validated fail-fast in __main__ below, before mcp.run() — never client-supplied
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))

mcp = FastMCP("builder-guild-context")


@mcp.tool()
def query_context(query_text: str, pattern: dict[str, str] | None = None, deep_serve: bool = False,
                   rerank: bool = False, include_communities: bool = False) -> dict:
    """Read-only fused graph+vector query. `pattern`, if given, is the structural graph-rung
    filter ladder.graph_rung consumes: a mapping with string keys "rel" (edge name) and "obj"
    (target entity key), e.g. {"rel": "BLOCKS", "obj": "issue:ACME-1"}. Returns the serve()
    envelope verbatim (decision/mode/presentable_facts/provenance/trace, incl.
    trace.gate_abstain) — no post-filtering, no gate bypass. Always runs as this server's
    bound role."""
    if isinstance(pattern, str):          # tolerate a JSON-encoded object from lenient clients
        try:
            pattern = json.loads(pattern)
        except json.JSONDecodeError:
            raise ValueError("pattern must be a JSON object with 'rel' and 'obj' string keys, "
                              "not a plain string")
    if pattern is not None and not ({"rel", "obj"} <= pattern.keys()):
        raise ValueError(f"pattern must have 'rel' and 'obj' keys, got: {sorted(pattern)}")
    return _serve(query_text, ROLE, pattern=pattern, deep_serve=deep_serve, rerank=rerank,
                  include_communities=include_communities)


@mcp.tool()
def node_card(key: str, as_of: str | None = None) -> dict | None:
    """Role-scoped node card: stable long_context + live bi-temporal edges.
    as_of=None -> current view; as_of=<ISO timestamp> -> point-in-time view."""
    return _node_card(key, scope.allowed_namespaces(ROLE), as_of=as_of)


@mcp.tool()
def health() -> dict:
    """Read-only connectivity check against bg-neo4j (no MERGE/write)."""
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
    return {"ok": True, "role": ROLE, "uri": URI}


@mcp.tool()
def list_namespaces() -> list[str]:
    """The namespace slice this server's bound role may read."""
    return scope.allowed_namespaces(ROLE)


if __name__ == "__main__":
    if ROLE not in scope.ROLE_NAMESPACES:
        sys.exit(f"BG_MCP_ROLE must be set to one of {sorted(scope.ROLE_NAMESPACES)}; got {ROLE!r}. "
                  f"Example: BG_MCP_ROLE=engineering 01-context/.venv/bin/python 02-agents/src/mcp_server.py")
    mcp.run()
