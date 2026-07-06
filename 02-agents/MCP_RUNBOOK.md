# MCP Server Runbook

Read-only MCP (stdio) server over `serve()`/`node_card()` from `01-context/src`. Zero
write-capable tools. Role is bound **server-side** from `BG_MCP_ROLE` at process start — no
tool accepts a role/namespace parameter; a client-supplied one is silently dropped by
FastMCP's generated schema and always ignored.

## Prereqs
- `bg-neo4j` container up (bolt `7688`, healthy)
- `mcp==1.28.1` installed in `01-context/.venv` (pinned in `requirements.txt`)
- Embeddings seeded for the vector rung: `etl.py` then `demo_seed.py` (adds `n.embedding`)

## Run standalone
```bash
BG_MCP_ROLE=engineering 01-context/.venv/bin/python 02-agents/src/mcp_server.py
```
Missing/invalid `BG_MCP_ROLE` fails fast (non-zero exit, clear stderr) — never a default role.

## Add to a client
```bash
claude mcp add builder-guild-context -e BG_MCP_ROLE=engineering -- \
  <REPO>/01-context/.venv/bin/python <REPO>/02-agents/src/mcp_server.py
```
(`<REPO>` = your absolute checkout path; both paths must be absolute.)
```bash
```
`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "builder-guild-context": {
      "command": "<REPO>/01-context/.venv/bin/python",
      "args": ["<REPO>/02-agents/src/mcp_server.py"],
      "env": { "BG_MCP_ROLE": "engineering" }
    }
  }
}
```

## Role -> namespace slice (`01-context/src/scope.py`, verbatim)
| Role | Allowed namespaces |
|---|---|
| engineering | engineering, shared |
| finance | finance, shared |
| operations | operations, shared |
| product | product, shared |
| market | market, shared |
| history | history, shared |
| governance | engineering, finance, operations, product, market, history, governance, shared |

## Tools
- `query_context(query_text, pattern=None, deep_serve=False, rerank=False, include_communities=False)` — fused graph+vector query, returns the `serve()` envelope verbatim.
- `node_card(key, as_of=None)` — role-scoped node card; `as_of` for point-in-time.
- `health()` — connectivity check against `bg-neo4j` (no write).
- `list_namespaces()` — this server's bound-role namespace slice.

Worked example:
```python
query_context(query_text="Who is issue ACME-2 assigned to?",
               pattern={"rel": "BLOCKS", "obj": "issue:ACME-1"})
# -> {"decision", "mode", "presentable_facts", "provenance",
#     "trace": {"gate_abstain": {...}, "retrieve": {"graph": ["issue:ACME-2"], ...}}}
```
