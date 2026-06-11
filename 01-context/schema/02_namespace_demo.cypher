// FIX-NS (cb-6a1.5) demo: namespace on node AND edge enforces role isolation.
// ONE statement (no intermediate ;) so node vars stay bound for the edge MERGEs.
MERGE (b:Entity:Agent {key:'agent:cto'})            SET b.namespace='engineering'
MERGE (a:Entity:Repo {key:'repo:acme/api'})         SET a.namespace='engineering'
MERGE (d:Entity:Agent {key:'agent:cfo'})            SET d.namespace='finance'
MERGE (c:Entity:Project {key:'project:budget-2026'}) SET c.namespace='finance'
MERGE (b)-[:RELATES_TO {name:'OWNS', namespace:'engineering'}]->(a)
MERGE (d)-[:RELATES_TO {name:'OWNS', namespace:'finance'}]->(c);
