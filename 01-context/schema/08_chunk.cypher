// 08_chunk.cypher — canonical sample: :Chunk node + :HAS_CHUNK edge, namespace-stamped.
// cf7 — fine-grained retrieval target (rung 2b "which passage"; HYBRID PART 1 §5b, PART 2 ladder 2b).
//
// WHY :Chunk NODES (not a vector-list on :Entity): Neo4j HNSW (db.index.vector.queryNodes) indexes
// exactly ONE vector property per node. Multi-chunk "which passage" recall therefore needs one indexed
// vector PER chunk -> a :Chunk node per chunk, each carrying its own n.embedding. The node-level vector
// (node_embedding on :Entity.embedding, rung 2) stays for coarse "which node" recall; chunk_embedding on
// :Chunk.embedding (rung 2b) is the fine "which passage" recall. (Supersedes the HYBRID §5b "on the node,
// single store" wording, which collided with the one-vector-per-node index reality.)
//
// MATERIALIZATION RULE (embed.py embed_node): :Chunk nodes are created ONLY for MULTI-chunk nodes
// (chunk_count > 1). A single-chunk node needs none — its passage IS its long_context, returned directly
// (HYBRID §3 "a single-chunk node may need none"; this is the bzr surfacing rule).
//
// CYPHER SAFETY (ONTOLOGY §8 §10):
//   - No null property in MERGE pattern (nullable fields set via SET only).
//   - Vars bound in ONE statement.
//   - now is an EXPLICIT param (never wall-clock ambient).
//   - All values param-bound (no f-string interpolation).
//
// Run via neo4j-shell or the Python driver with explicit params.
// This is a SAMPLE; embed.py embed_node() runs the full embed+materialize pipeline.

// Step 1: Write a :Chunk node for the 0th chunk of parent 'issue:ACME-2', namespace 'engineering'.
// The embedding (768-dim EmbeddingGemma vector of THIS chunk's text) is set via SET, not in MERGE.
MERGE (c:Chunk {key: 'issue:ACME-2#0'})
SET c.parent_key = 'issue:ACME-2',
    c.namespace  = 'engineering',
    c.ord        = 0,
    c.text       = $chunk_text,
    c.chunk_kind = 'prose',
    c.embedded_at = $now
//  c.embedding = $vec   // 768-dim; set in the same SET in the real pipeline (omitted here for the sample)

// Step 2 (separate call): Write the :HAS_CHUNK membership edge from the parent :Entity to the chunk.
// Run with params: {parent_key: 'issue:ACME-2', chunk_key: 'issue:ACME-2#0', ord: 0, ns: 'engineering'}
//
//   MATCH (e:Entity {key: $parent_key}), (c:Chunk {key: $chunk_key})
//   MERGE (e)-[h:HAS_CHUNK]->(c)
//   SET h.ord = $ord, h.namespace = $ns
//
// Query to verify isolation (the FULL proof — mirrors embed.assert_chunk_namespace_isolation):
// every :Chunk's own namespace AND its :HAS_CHUNK edge namespace must equal its parent :Entity's
// namespace (and be non-null). A chunk recalled by chunk_embedding is post-filtered on c.namespace,
// so a namespace-mismatched chunk would leak across the role boundary.
//   MATCH (e:Entity)-[h:HAS_CHUNK]->(c:Chunk)
//   WHERE c.namespace IS NULL OR h.namespace IS NULL
//      OR c.namespace <> e.namespace OR h.namespace <> e.namespace
//      OR c.parent_key <> e.key
//   RETURN e.key, e.namespace, c.key, c.namespace, h.namespace
//   // Must return 0 rows (the structural isolation proof).
//
// Orphan check (a :Chunk with no parent edge is dead-stored — same class of bug as cf7/bzr):
//   MATCH (c:Chunk) WHERE NOT ( (:Entity)-[:HAS_CHUNK]->(c) ) RETURN c.key
//   // Must return 0 rows.
