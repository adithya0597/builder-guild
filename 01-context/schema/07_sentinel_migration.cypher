// 07_sentinel_migration.cypher — SENTINEL cutover backfill + guard.
//
// Run ONCE against an existing graph that predates the sentinel contract (i.e. a graph where a
// current edge was represented by an ABSENT invalid_at). Idempotent: only edges with a NULL
// invalid_at are touched, so re-running on a clean graph is a no-op.
//
// SENTINEL contract: a current edge carries invalid_at = datetime('9999-12-31T00:00:00Z') (never
// NULL); a superseded/removed edge carries invalid_at = now. Therefore current = (invalid_at > now)
// and as-of-T = (valid_at <= T AND invalid_at > T). See ONTOLOGY_SCHEMA.md §8 and audits/SENTINEL_CUTOVER_SPEC.md.

// 1) Backfill: every current (absent-invalid_at) edge gets the sentinel.
MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at IS NULL
SET r.invalid_at = datetime('9999-12-31T00:00:00Z');

// 2) Guard — MUST return 0. After the backfill no current-view edge may have a NULL invalid_at
//    (a NULL would silently vanish from `invalid_at > now`, the "null>now trap").
MATCH ()-[r:RELATES_TO]->() WHERE r.invalid_at IS NULL RETURN count(r) AS must_be_zero;
