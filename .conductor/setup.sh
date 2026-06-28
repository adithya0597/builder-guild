#!/usr/bin/env bash
# Conductor workspace bootstrap for builder-guild.
# Starts the shared local Neo4j instance, then creates a per-worktree venv and installs deps.
# Environment-ready, NOT demo-seeded: does not run etl.py / demo_seed.py — seed explicitly when needed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Shared Neo4j for local development. The compose file uses a fixed container name (cb-neo4j) and
# fixed host ports (7474/7687), so Conductor worktrees share one local DB instance. -p is for
# consistency, not isolation. --wait blocks until the compose healthcheck reports healthy.
(
  cd 01-context
  docker compose -p builder-guild up -d --wait
)

# Per-worktree venv + neo4j driver + write/read smoke test against localhost:7687.
bash 01-context/setup_a2.sh

# Project dependencies for this worktree's venv.
./01-context/.venv/bin/python -m pip install -q -r requirements.txt -r requirements-dev.txt

echo "CONDUCTOR_SETUP_DONE"
