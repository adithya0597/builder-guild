// 03_indexes.cypher — B3-idx. Label LOOKUP index is built-in (SHOW INDEXES lists it).
// RANGE on bi-temporal edge fields (the as-of validity filter, PART 3)
CREATE RANGE INDEX rel_valid_at IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.valid_at);
CREATE RANGE INDEX rel_created_at IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.created_at);
// SENTINEL contract: current = (invalid_at > now); as-of-T = (valid_at <= T AND invalid_at > T). Index the read path.
CREATE RANGE INDEX rel_invalid_at IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.invalid_at);
// namespace (isolation filter) on node AND edge — the deterministic scope filter (FIX-NS)
CREATE RANGE INDEX node_namespace IF NOT EXISTS FOR (n:Entity) ON (n.namespace);
CREATE RANGE INDEX rel_namespace IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.namespace);
// full-text on node descriptions (graph-index keyword path)
CREATE FULLTEXT INDEX node_text IF NOT EXISTS FOR (n:Entity) ON EACH [n.short_context, n.long_context];
// vector on intrinsic-content embedding (EmbeddingGemma-300M = 768 dims, cosine; PART 1 §5)
CREATE VECTOR INDEX node_embedding IF NOT EXISTS FOR (n:Entity) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};
