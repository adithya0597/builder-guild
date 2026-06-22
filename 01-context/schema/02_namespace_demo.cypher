// FIX-NS demo: namespace on node AND edge enforces role isolation.
// ONE statement (no intermediate ;) so node vars stay bound for the edge MERGEs.
MERGE (b:Entity:Agent {key:'agent:cto'})            SET b.namespace='engineering'
MERGE (a:Entity:Repo {key:'repo:acme/api'})         SET a.namespace='engineering'
MERGE (d:Entity:Agent {key:'agent:cfo'})            SET d.namespace='finance'
MERGE (c:Entity:Project {key:'project:budget-2026'}) SET c.namespace='finance'
MERGE (b)-[r1:RELATES_TO {name:'OWNS', namespace:'engineering'}]->(a)
  SET r1.valid_at=datetime(), r1.created_at=datetime(), r1.invalid_at=datetime('9999-12-31T00:00:00Z')
MERGE (d)-[r2:RELATES_TO {name:'OWNS', namespace:'finance'}]->(c)
  SET r2.valid_at=datetime(), r2.created_at=datetime(), r2.invalid_at=datetime('9999-12-31T00:00:00Z');
