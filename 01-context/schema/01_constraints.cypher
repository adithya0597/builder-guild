// 01_constraints.cypher — B1-onto: node-key uniqueness.
// Neo4j Community: REQUIRE ... IS UNIQUE only (IS NODE KEY + existence are Enterprise).
// Internal identities
CREATE CONSTRAINT entity_uuid IF NOT EXISTS FOR (n:Entity) REQUIRE n.uuid IS UNIQUE;
CREATE CONSTRAINT episodic_uuid IF NOT EXISTS FOR (n:Episodic) REQUIRE n.uuid IS UNIQUE;
// Tier nodes
CREATE CONSTRAINT domain_key IF NOT EXISTS FOR (n:Domain) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT subdomain_key IF NOT EXISTS FOR (n:SubDomain) REQUIRE n.key IS UNIQUE;
// T2 entity types — canonical business key = the MERGE target (PART 3-D)
CREATE CONSTRAINT project_key IF NOT EXISTS FOR (n:Project) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT repo_key IF NOT EXISTS FOR (n:Repo) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT decision_key IF NOT EXISTS FOR (n:Decision) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT issue_key IF NOT EXISTS FOR (n:Issue) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT task_key IF NOT EXISTS FOR (n:Task) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT capability_key IF NOT EXISTS FOR (n:Capability) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT agent_key IF NOT EXISTS FOR (n:Agent) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT policy_key IF NOT EXISTS FOR (n:Policy) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT externalsource_key IF NOT EXISTS FOR (n:ExternalSource) REQUIRE n.key IS UNIQUE;
// Governance types (APC-borrowed)
CREATE CONSTRAINT vote_key IF NOT EXISTS FOR (n:Vote) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT decisionrecord_key IF NOT EXISTS FOR (n:DecisionRecord) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT forceentry_key IF NOT EXISTS FOR (n:ForceEntryCondition) REQUIRE n.key IS UNIQUE;
// Chunk passages (cf7 — fine-grained retrieval target; key = '<parent_key>#<ord>')
CREATE CONSTRAINT chunk_key IF NOT EXISTS FOR (c:Chunk) REQUIRE c.key IS UNIQUE;
