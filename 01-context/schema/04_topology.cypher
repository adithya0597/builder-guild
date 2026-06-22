// 04_topology.cypher — C1-topo. Canonical sample exercising all 5 elements.
// ONE statement so vars stay bound. NOTE: never put a null prop in a MERGE pattern (Neo4j rejects it);
// SENTINEL contract: "current fact" => invalid_at = datetime('9999-12-31T00:00:00Z') (never null);
// expired_at ABSENT. Never put a literal null in a MERGE pattern; set fields via SET.
MERGE (e1:Episodic {uuid:'ep-001'}) SET e1.created_at=datetime(), e1.valid_at=datetime(), e1.namespace='engineering'
MERGE (e2:Episodic {uuid:'ep-002'}) SET e2.created_at=datetime(), e2.valid_at=datetime(), e2.namespace='engineering'
MERGE (cto:Entity:Agent {key:'agent:cto'}) SET cto.namespace='engineering', cto.created_at=datetime()
MERGE (repo:Entity:Repo {key:'repo:acme/api'}) SET repo.namespace='engineering', repo.created_at=datetime()
MERGE (e1)-[:NEXT_EPISODE]->(e2)
MERGE (e1)-[:MENTIONS]->(cto)
MERGE (e1)-[:MENTIONS]->(repo)
MERGE (cto)-[r:RELATES_TO {name:'OWNS', namespace:'engineering'}]->(repo)
  SET r.episodes=['ep-001'], r.valid_at=datetime(), r.created_at=datetime(), r.invalid_at=datetime('9999-12-31T00:00:00Z');
