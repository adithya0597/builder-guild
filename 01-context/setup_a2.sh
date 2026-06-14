#!/usr/bin/env bash
# A2: dedicated venv + neo4j-graphrag-python + smoke-test write/read.
set -uo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -m pip install -q --upgrade pip >/dev/null 2>&1
echo "== pip install neo4j-graphrag =="
pip install -q neo4j-graphrag 2>&1 | tail -5
python -c "import neo4j, neo4j_graphrag; print('drivers ok: neo4j', neo4j.__version__)" 2>&1
echo "== smoke test (write + read-back against bolt://localhost:7687) =="
python smoke_test.py 2>&1
echo "A2_SETUP_DONE"
