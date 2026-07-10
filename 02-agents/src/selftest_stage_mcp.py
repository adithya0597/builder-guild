"""Scripted stdio exchange against mcp_stage_server.py: initialize -> tools/list -> tools/call,
against live bg-neo4j. Spawns the server with BG_MCP_ROLE=engineering BG_STAGE_NS=engineering and
asserts the two-tool agent surface + its suggest-only / no-write-leak contract end to end; then
spawns it three more times (missing BG_STAGE_NS, out-of-scope BG_STAGE_NS, missing BG_MCP_ROLE) —
each must fail fast, never serve. Prints STAGE_MCP_OK, exit 0.

Own copies of the _result_value/_call unwrap helpers (not imported from selftest_mcp.py): the pair
is used in exactly 2 places across the two deliberately-separate trust-boundary servers — below the
repo's <3-uses-inline rule — and keeps each server's harness independently runnable.
"""
import asyncio
import json
import os
import re
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "01-context", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scope
import staging
import stamp
from neo4j import GraphDatabase
from serve import node_card

SERVER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_stage_server.py")
EXPECTED_TOOLS = {"plan_context", "propose_edge"}
# Exact per-tool parameter sets — the mechanical proof that no ns/role/_serve/tau leaked in.
EXPECTED_SCHEMA = {
    "propose_edge": {"s_key", "rel", "o_key", "evidence", "source"},
    "plan_context": {"question", "max_steps", "as_of"},
}
# Test-only fixture key-space: cannot collide with demo_seed's ACME-* graph or staging.py's own
# STG-* selftest fixture.
T_SUBJ, T_REL, T_OBJ = "issue:STGMCP-TEST-1", "ASSIGNED_TO", "agent:STGMCP-TEST-BOB"
TERMINATED_LABELS = {"confidence", "escalate", "confident_abstain", "abstain", "max_steps"}

# Distinct fixture key-space for the as_of behavioral probe (bead 3o0) — separate from T_SUBJ/T_REL/T_OBJ
# above and from serve.py's own "asofprobe" self-test fixture, so concurrent selftest runs never collide.
A_ISS, A_REL, A_OLD, A_NEW = ("issue:STGMCP-ASOF-1", "HAS_STATUS",
                              "status:STGMCP-ASOF-OLD", "status:STGMCP-ASOF-NEW")
A_NS = "engineering"                                        # matches the session's bound BG_STAGE_NS
A_T0, A_TB, A_T1 = ("2026-06-04T00:00:00Z", "2026-06-04T00:30:00Z", "2026-06-04T01:00:00Z")  # T0<=TB<T1
A_OLD_FACT, A_NEW_FACT = f"{A_REL} -> {A_OLD}", f"{A_REL} -> {A_NEW}"


def _result_value(result):
    """Unwrap a CallToolResult to its plain Python value. Plain-`dict`-returning tools (plan_context)
    get no structuredContent from FastMCP — only a JSON text block; `str`-returning tools
    (propose_edge) get structuredContent wrapped as {"result": ...} (mcp==1.28.1 behavior, verified
    in selftest_mcp.py's session notes)."""
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


def _grep_gate(fail):
    """(b) no-write-leak SOURCE grep: mcp_stage_server.py's entire source (code + docstrings) must
    match ZERO of staging.(promote|approve|reject) and ZERO of the sanctioned edge-write engine's
    dotted calls — the exact write-leak the write-gateway's lexical import-scan structurally cannot
    catch (it cannot see `import staging; staging.<human-only-verb>(...)`). Pure-python regex,
    mirroring check_write_gateway.py's own IMPORT_CALL_PAT convention — not a shell-out to grep,
    which mis-counts literal parens on this shell."""
    src = open(SERVER_PATH).read()
    for pat in (r"staging\.(?:promote|approve|reject)\b", r"mutate\."):
        m = re.search(pat, src)
        fail += [] if m is None else \
            [f"(b) write-leak: mcp_stage_server.py source matches {pat!r} at {m.group(0)!r}"]


async def _session_cases(fail):
    """(a) exact tool-set + inputSchema; (c) propose_edge stages an invisible, self-cleaned
    candidate; (d) plan_context returns a bounded envelope — all under one engineering session."""
    params = StdioServerParameters(command=sys.executable, args=[SERVER_PATH],
                                    env={**os.environ, "BG_MCP_ROLE": "engineering",
                                         "BG_STAGE_NS": "engineering"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # (a) EXACT tool set + EXACT per-tool inputSchema property-sets.
            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            print(f"[list]    tools = {sorted(names)}")
            fail += [] if names == EXPECTED_TOOLS else [f"(a) tool set mismatch: {sorted(names)}"]
            schema = {t.name: set((t.inputSchema or {}).get("properties", {})) for t in tools}
            for tname, want in EXPECTED_SCHEMA.items():
                got = schema.get(tname)
                fail += [] if got == want else [f"(a) {tname} params {got} != expected {want}"]

            # (c) propose_edge -> cand_id; :Candidate count==1 (non-vacuous: a fabricated-id/no-write
            # propose would fail here); pending candidate INVISIBLE to a node_card read; self-clean.
            cand_id = await _call(session, "propose_edge", {
                "s_key": T_SUBJ, "rel": T_REL, "o_key": T_OBJ,
                "evidence": "stgmcp-evidence", "source": "stgmcp-source"}, fail)
            print(f"[propose] cand_id = {cand_id!r}")
            fail += [] if isinstance(cand_id, str) and cand_id else \
                [f"(c) propose_edge did not return a cand_id: {cand_id!r}"]
            if isinstance(cand_id, str) and cand_id:
                try:
                    with GraphDatabase.driver(staging.URI, auth=staging.AUTH) as drv, drv.session() as s:
                        cnt = s.execute_read(lambda tx: tx.run(
                            "MATCH (c:Candidate {cand_id:$id}) RETURN count(c) AS c",
                            id=cand_id).single()["c"])
                        card = node_card(T_SUBJ, scope.allowed_namespaces("engineering"))
                    fact = f"{T_REL} -> {T_OBJ}"
                    leaked = card is not None and any(
                        f.get("fact") == fact for f in (card.get("facts") or []))
                    print(f"[invis]   candidate_count={cnt} node_card({T_SUBJ})={card!r} leaked={leaked}")
                    fail += [] if cnt == 1 else [f"(c) propose_edge wrote {cnt} candidates, expected 1"]
                    fail += [] if not leaked else \
                        [f"(c) pending candidate visible in node_card facts: {card}"]
                finally:
                    with GraphDatabase.driver(staging.URI, auth=staging.AUTH) as drv, drv.session() as s:
                        s.execute_write(lambda tx: tx.run(
                            "MATCH (c:Candidate {cand_id:$id}) DETACH DELETE c", id=cand_id))

            # (d) plan_context -> bounded, well-formed planner envelope (shape/keys/bound, NOT a
            # specific decision). Same query selftest_mcp.py:63 uses against the live fixture.
            envelope = await _call(session, "plan_context", {
                "question": "Who is issue ACME-2 assigned to?"}, fail) or {}
            pl = envelope.get("planner") or {}
            print(f"[plan]    terminated_on={pl.get('terminated_on')} steps_used={pl.get('steps_used')} "
                  f"max_steps={pl.get('max_steps')} distinct={pl.get('distinct_retrievals')}")
            want_keys = {"steps", "distinct_retrievals", "terminated_on", "steps_used", "max_steps"}
            fail += [] if want_keys <= set(pl) else [f"(d) planner envelope missing keys: {sorted(pl)}"]
            fail += [] if isinstance(pl.get("steps"), list) else \
                [f"(d) planner.steps not a list: {pl.get('steps')!r}"]
            su, ms = pl.get("steps_used"), pl.get("max_steps")
            fail += [] if isinstance(su, int) and isinstance(ms, int) and su <= ms else \
                [f"(d) steps_used {su!r} !<= max_steps {ms!r}"]
            fail += [] if pl.get("terminated_on") in TERMINATED_LABELS else \
                [f"(d) terminated_on not a known label: {pl.get('terminated_on')!r}"]

            # (d2) max_steps<=0 must be floored at 1 at the tool boundary, not passed through to
            # planner's range(1, max_steps+1) (empty -> malformed/empty envelope). Regression guard.
            env0 = await _call(session, "plan_context", {
                "question": "Who is issue ACME-2 assigned to?", "max_steps": 0}, fail) or {}
            pl0 = env0.get("planner") or {}
            print(f"[plan0]   steps_used={pl0.get('steps_used')} max_steps={pl0.get('max_steps')}")
            su0 = pl0.get("steps_used")
            fail += [] if isinstance(su0, int) and su0 >= 1 else \
                [f"(d2) max_steps=0 gave malformed envelope: steps_used={su0!r} planner={pl0!r}"]

            # (h) BEHAVIORAL as_of forwarding (bead 3o0): plant a real bi-temporal supersession via
            # stamp.plant_supersession (the sanctioned mutate-engine fixture serve.py's own self-test
            # uses), then prove as_of reaches serve() THROUGH plan_context THROUGH the MCP tool
            # boundary — not just that the param is schema-accepted. max_steps=1 forces the planner's
            # first (and only) probe to be serve(question, role, as_of=as_of) with no re-aim, so the
            # terminating result is deterministically the point-in-time query, mirroring serve.py's
            # own as_of self-test (serve.py:797-825) one layer up through planner.plan + the tool.
            stamp.plant_supersession(A_ISS, A_REL, A_OLD, A_NEW, A_NS, A_T0, A_T1)
            try:
                env_before = await _call(session, "plan_context", {
                    "question": "STGMCP-ASOF-1", "max_steps": 1, "as_of": A_TB}, fail) or {}
                env_now = await _call(session, "plan_context", {
                    "question": "STGMCP-ASOF-1", "max_steps": 1}, fail) or {}
                pf_b = env_before.get("presentable_facts") or []
                pf_n = env_now.get("presentable_facts") or []
                print(f"[asof]    as_of={A_TB} -> {pf_b} | as_of=None(now) -> {pf_n}")
                fail += [] if (A_OLD_FACT in pf_b and A_NEW_FACT not in pf_b) else \
                    [f"(h) as_of={A_TB} must surface OLD value only via plan_context: {pf_b}"]
                fail += [] if (A_NEW_FACT in pf_n and A_OLD_FACT not in pf_n) else \
                    [f"(h) as_of=None must surface NEW (current) value only via plan_context: {pf_n}"]
            finally:
                with GraphDatabase.driver(staging.URI, auth=staging.AUTH) as drv, drv.session() as s:
                    s.run("MATCH (n) WHERE n.key IN $k DETACH DELETE n", k=[A_ISS, A_OLD, A_NEW])


def _startup_fail(env_overrides, strip_keys, must_mention, label, fail):
    """Spawn the server with a broken env and assert it fails fast (nonzero exit + a stderr message
    naming the offending var), never serving. Strips inherited values first so the test is
    deterministic regardless of the caller's shell env."""
    env = {k: v for k, v in os.environ.items() if k not in strip_keys}
    env.update(env_overrides)
    proc = subprocess.run([sys.executable, SERVER_PATH], env=env, capture_output=True,
                          text=True, timeout=20)
    print(f"[startup] ({label}) -> exit={proc.returncode} stderr={proc.stderr.strip()!r}")
    fail += [] if proc.returncode != 0 else \
        [f"({label}) server served instead of failing fast"]
    fail += [] if must_mention in proc.stderr else \
        [f"({label}) fail-fast message didn't mention {must_mention}: {proc.stderr!r}"]


async def main():
    fail = []
    _grep_gate(fail)                                     # (b) — static, cheapest, no subprocess
    await _session_cases(fail)                           # (a)/(c)/(d) — one engineering session
    # (e) missing BG_STAGE_NS; (f) BG_STAGE_NS outside engineering's slice; (g) missing BG_MCP_ROLE.
    _startup_fail({"BG_MCP_ROLE": "engineering"}, {"BG_STAGE_NS"}, "BG_STAGE_NS", "e", fail)
    _startup_fail({"BG_MCP_ROLE": "engineering", "BG_STAGE_NS": "finance"}, set(), "BG_STAGE_NS", "f", fail)
    _startup_fail({"BG_STAGE_NS": "engineering"}, {"BG_MCP_ROLE"}, "BG_MCP_ROLE", "g", fail)

    if fail:
        print("STAGE_MCP_FAIL:", fail)
        sys.exit(1)
    print("ASOF_MCP_OK")
    print("STAGE_MCP_OK")


if __name__ == "__main__":
    asyncio.run(main())
