// 06_community.cypher — canonical sample: :Community node + :IN_COMMUNITY edge, namespace-stamped.
// Per GraphRAG community summaries. Derived artifact — per-namespace only (ONTOLOGY §7 §12).
//
// CYPHER SAFETY (ONTOLOGY §8 §10):
//   - No null property in MERGE pattern (nullable fields set via SET only).
//   - Vars bound in ONE statement.
//   - now and run_id are EXPLICIT params (never wall-clock ambient).
//   - All values param-bound (no f-string interpolation).
//
// Run via neo4j-shell or the Python driver with explicit params.
// This is a SAMPLE; communities.py builds_communities() runs the full pipeline.

// Step 1: Write a :Community node for namespace 'engineering', community index 0.
MERGE (c:Community {key: 'community:engineering:0'})
SET c.namespace       = 'engineering',
    c.member_count    = 2,
    c.built_at        = $now,
    c.run_id          = $run_id

// Step 2 (separate call): Write an :IN_COMMUNITY membership edge from an :Entity to the community.
// Run with params: {member_key: 'issue:SPI-1', comm_key: 'community:engineering:0', ns: 'engineering'}
//
//   MATCH (e:Entity {key: $member_key}), (c:Community {key: $comm_key})
//   MERGE (e)-[m:IN_COMMUNITY]->(c)
//   SET m.namespace = $ns
//
// Query to verify isolation (the FULL proof — mirrors communities.assert_no_cross_namespace_community):
// every community must have >=1 member, and ALL member namespaces AND ALL membership-edge namespaces
// must equal the community's own namespace (which must be non-null).
//   MATCH (c:Community)
//   OPTIONAL MATCH (e:Entity)-[m:IN_COMMUNITY]->(c)
//   WITH c, collect(DISTINCT e.namespace) AS member_ns,
//           count(m) AS n_edges, count(m.namespace) AS n_edges_with_ns,  // count() ignores nulls
//           collect(DISTINCT m.namespace) AS edge_ns
//   WHERE c.namespace IS NULL OR size(member_ns) = 0 OR size(member_ns) > 1
//      OR member_ns[0] <> c.namespace
//      OR n_edges_with_ns < n_edges                      // a membership edge has a NULL namespace
//      OR any(x IN edge_ns WHERE x <> c.namespace)
//   RETURN c.key, c.namespace, member_ns, edge_ns
//   // Must return 0 rows (the structural isolation proof).
//
// Role-scoped read example (CTO role: allowed = ['engineering','shared']):
//   MATCH (e:Entity {key: $node_key})-[:IN_COMMUNITY]->(c:Community)
//   WHERE c.namespace IN $allowed
//   RETURN c.key, c.namespace, c.summary, c.member_count
