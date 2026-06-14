#!/usr/bin/env bash
# A1: stand up Neo4j Community + confirm range/fulltext/vector index types available.
set -uo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"
echo "== recreate cb-neo4j with fixed config =="
docker compose down --remove-orphans 2>&1 | tail -3
docker compose up -d 2>&1 | tail -10
echo "== wait for neo4j to accept cypher (<=180s) =="
ok=0
for i in $(seq 1 36); do
  if docker exec cb-neo4j cypher-shell -u neo4j -p companybrain "RETURN 1;" >/dev/null 2>&1; then
    echo "NEO4J_READY after $((i*5))s"; ok=1; break
  fi
  sleep 5
done
if [ "$ok" != 1 ]; then echo "NEO4J_NOT_READY in 180s"; docker compose logs --tail 25 neo4j 2>&1 | tail -25; exit 1; fi

echo "== edition =="
docker exec -i cb-neo4j cypher-shell -u neo4j -p companybrain --format plain <<'CYPHER' 2>&1
CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition;
CYPHER

echo "== create one of each index type (proves all three available in Community) =="
docker exec -i cb-neo4j cypher-shell -u neo4j -p companybrain <<'CYPHER' 2>&1 | tail -6
CREATE RANGE INDEX cb_probe_range IF NOT EXISTS FOR (n:CBProbe) ON (n.k);
CREATE FULLTEXT INDEX cb_probe_ft IF NOT EXISTS FOR (n:CBProbe) ON EACH [n.txt];
CREATE VECTOR INDEX cb_probe_vec IF NOT EXISTS FOR (n:CBProbe) ON (n.emb) OPTIONS {indexConfig: {`vector.dimensions`: 8, `vector.similarity_function`: 'cosine'}};
CYPHER

echo "== SHOW INDEXES (probe rows; want types RANGE, FULLTEXT, VECTOR) =="
docker exec -i cb-neo4j cypher-shell -u neo4j -p companybrain --format plain <<'CYPHER' 2>&1
SHOW INDEXES YIELD name, type, state WHERE name STARTS WITH 'cb_probe' RETURN name, type, state ORDER BY type;
CYPHER

echo "== cleanup probe indexes =="
docker exec -i cb-neo4j cypher-shell -u neo4j -p companybrain <<'CYPHER' 2>&1 | tail -2
DROP INDEX cb_probe_range IF EXISTS;
DROP INDEX cb_probe_ft IF EXISTS;
DROP INDEX cb_probe_vec IF EXISTS;
CYPHER

echo "== container state (volume-persisted) =="
docker ps --filter name=cb-neo4j --format '{{.Names}} | {{.Status}} | {{.Image}}'
docker volume ls --filter name=cb_neo4j --format '{{.Name}}'
echo "A1_VERIFY_DONE"
