"""Scripted stdio exchange against mcp_server.py: initialize -> tools/list -> tools/call,
against live bg-neo4j. Spawns the server as a subprocess with BG_MCP_ROLE=engineering and
asserts the read-only + role-binding contract end to end; also spawns it again with
BG_MCP_ROLE=governance (role binding is env-driven, not hardcoded) and once more with no
BG_MCP_ROLE at all (must fail fast, never serve with a default). Prints MCP_SERVE_OK, exit 0.
"""
import asyncio
import json
import os
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

SERVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
EXPECTED_TOOLS = {"query_context", "node_card", "health", "list_namespaces"}
WRITE_MARKERS = ("apply_edge", "ingest", "write", "merge", "create", "delete")


def _result_value(result):
    """Unwrap a CallToolResult to its plain Python value. Plain-`dict`-returning tools
    (query_context/health) get no structuredContent from FastMCP - only a JSON text
    block. `dict | None`/`list[str]`-returning tools (node_card/list_namespaces) get
    structuredContent wrapped as {"result": ...} (verified empirically against the
    installed mcp==1.28.1 SDK - see probe in session notes)."""
    sc = result.structuredContent
    if sc is not None:
        return sc["result"] if set(sc) == {"result"} else sc
    for block in result.content:
        if isinstance(block, TextContent):
            return json.loads(block.text)
    return None


async def _call(session, name, arguments, fail):
    result = await session.call_tool(name, arguments)
    if result.isError:
        fail.append(f"{name}{arguments} returned isError: {result.content}")
        return None
    return _result_value(result)


async def main():
    fail = []
    params = StdioServerParameters(command=sys.executable, args=[SERVER_PATH],
                                    env={**os.environ, "BG_MCP_ROLE": "engineering"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # (a) tools/list: EXACT set equality, zero write-capable tools
            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            print(f"[list]    tools = {sorted(names)}")
            fail += [] if names == EXPECTED_TOOLS else [f"(a) tool set mismatch: {sorted(names)}"]
            leaky = [t.name for t in tools if any(m in t.name.lower() for m in WRITE_MARKERS)]
            fail += [] if not leaky else [f"(a) write-shaped tool name(s) exposed: {leaky}"]

            # (b) NEGATIVE ROLE TEST: client-supplied role must be ignored; env role wins
            envelope = await _call(session, "query_context", {
                "query_text": "Who is issue ACME-2 assigned to?", "role": "governance"}, fail) or {}
            print(f"[role]    envelope.role = {envelope.get('role')!r} (client asked for governance)")
            fail += [] if envelope.get("role") == "engineering" else \
                [f"(b) role override leaked: {envelope.get('role')!r}"]

            namespaces = await _call(session, "list_namespaces", {}, fail)
            print(f"[ns]      list_namespaces = {namespaces} (must NOT be governance's 7 slices)")
            fail += [] if namespaces == ["engineering", "shared"] else \
                [f"(b) list_namespaces leaked governance's slice: {namespaces}"]

            # (c) full gated envelope present - no filtering, no gate bypass
            has_keys = all(k in envelope for k in ("decision", "mode", "presentable_facts", "provenance"))
            gate = (envelope.get("trace") or {}).get("gate_abstain", {})
            print(f"[gate]    keys_ok={has_keys} sufficiency={gate.get('sufficiency')} "
                  f"self_confidence={gate.get('self_confidence')}")
            fail += [] if has_keys else [f"(c) envelope missing gated keys: {sorted(envelope)}"]
            fail += [] if {"sufficiency", "self_confidence"} <= set(gate) else \
                [f"(c) trace.gate_abstain missing sufficiency/self_confidence: {gate}"]

            # (d) live bg-neo4j: health must actually connect
            health = await _call(session, "health", {}, fail) or {}
            print(f"[health]  {health}")
            fail += [] if health.get("ok") is True else [f"(d) health not ok: {health}"]

            # (e) STRUCTURAL PATTERN (bead 9fe): pattern is a MAPPING {"rel","obj"} — the shape
            # ladder.graph_rung actually consumes (etl.py fixture: issue:ACME-2 BLOCKS
            # issue:ACME-1, engineering ns). query_text="" isolates the graph rung (keyword/vector
            # skip on empty text), so a hit here is unambiguous proof the structural rung fires
            # through the MCP surface.
            pat_envelope = await _call(session, "query_context", {
                "query_text": "", "pattern": {"rel": "BLOCKS", "obj": "issue:ACME-1"}}, fail) or {}
            graph_hits = (pat_envelope.get("trace") or {}).get("retrieve", {}).get("graph")
            print(f"[pattern] structural query -> trace.retrieve.graph = {graph_hits}")
            fail += [] if graph_hits == ["issue:ACME-2"] else \
                [f"(e) structural pattern rung missed the ACME-2 BLOCKS ACME-1 fixture: {graph_hits}"]

            # (f) MALFORMED PATTERN: missing the required "obj" key must surface as a clean tool
            # error (isError=True with our message), never an unhandled KeyError/traceback, and the
            # server must stay alive for the next call.
            bad = await session.call_tool("query_context", {
                "query_text": "", "pattern": {"rel": "BLOCKS"}})
            msg = bad.content[0].text if bad.content else ""
            print(f"[pattern] malformed pattern (missing obj) -> isError={bad.isError} msg={msg!r}")
            fail += [] if bad.isError else ["(f) malformed pattern did not surface as a tool error"]
            fail += [] if ("pattern must have" in msg and "Traceback" not in msg) else \
                [f"(f) malformed pattern error wasn't the clean validation message: {msg!r}"]
            revived = await _call(session, "query_context", {
                "query_text": "", "pattern": {"rel": "BLOCKS", "obj": "issue:ACME-1"}}, fail) or {}
            revived_hits = (revived.get("trace") or {}).get("retrieve", {}).get("graph")
            print(f"[pattern] server survived malformed call -> next graph hit = {revived_hits}")
            fail += [] if revived_hits == ["issue:ACME-2"] else \
                [f"(f) server did not survive the malformed call for a subsequent request: {revived_hits}"]

    # (g) SECOND-ROLE VARIANT (role binding is env-driven, not hardcoded): the SAME server code,
    # started with BG_MCP_ROLE=governance, must report governance's full (wider, cross-cutting) slice.
    gov_params = StdioServerParameters(command=sys.executable, args=[SERVER_PATH],
                                       env={**os.environ, "BG_MCP_ROLE": "governance"})
    async with stdio_client(gov_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            gov_namespaces = await _call(session, "list_namespaces", {}, fail)
            print(f"[role2]   governance list_namespaces = {gov_namespaces}")
            fail += [] if gov_namespaces == ["engineering", "finance", "operations", "product",
                                             "market", "history", "governance", "shared"] else \
                [f"(g) governance namespace list wrong: {gov_namespaces}"]

    # (h) NEGATIVE STARTUP TEST: no BG_MCP_ROLE at all must fail fast with a clear stderr message
    # and non-zero exit — never silently serve with a default role. Strip any inherited value so
    # the test is deterministic regardless of the caller's shell env.
    env_no_role = {k: v for k, v in os.environ.items() if k != "BG_MCP_ROLE"}
    proc = subprocess.run([sys.executable, SERVER_PATH], env=env_no_role, capture_output=True,
                          text=True, timeout=15)
    print(f"[startup] no BG_MCP_ROLE -> exit={proc.returncode} stderr={proc.stderr.strip()!r}")
    fail += [] if proc.returncode != 0 else \
        ["(h) server served without BG_MCP_ROLE instead of failing fast"]
    fail += [] if "BG_MCP_ROLE" in proc.stderr else \
        [f"(h) fail-fast message didn't mention BG_MCP_ROLE: {proc.stderr!r}"]

    if fail:
        print("MCP_SERVE_FAIL:", fail)
        sys.exit(1)
    print("MCP_SERVE_OK")


if __name__ == "__main__":
    asyncio.run(main())
