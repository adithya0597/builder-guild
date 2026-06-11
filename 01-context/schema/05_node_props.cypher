// 05_node_props.cypher — C2-props (cb-6a1.8). A well-formed structured node (no pageindex_ref)
// and a long-doc node (with pageindex_ref). One statement; nulls absent, not in MERGE pattern.
MERGE (i:Entity:Issue {key:'issue:cb:42'})
  SET i.uuid='u-issue-42', i.namespace='engineering',
      i.short_context='Issue 42: bolt client timeout',
      i.long_context='An engineering issue describing a connection timeout in the bolt client for the API repo.',
      i.chunks=['<full issue body text>'], i.chunk_count=1,
      i.embedded_at=datetime(), i.embedding_model='embeddinggemma-300m', i.content_rev=1, i.dirty=false
MERGE (d:Entity:ExternalSource {key:'extsrc:runbook-001'})
  SET d.uuid='u-doc-001', d.namespace='engineering',
      d.short_context='Runbook: incident response',
      d.long_context='A long operational runbook covering incident response procedures and escalation.',
      d.chunks=['<sec1>','<sec2>','<sec3>'], d.chunk_count=3,
      d.pageindex_ref='tree:runbook-001', d.tree_built_at=datetime(),
      d.embedded_at=datetime(), d.embedding_model='embeddinggemma-300m', d.content_rev=1, d.dirty=false;

// ── Recall-layer provenance contract (FORWARD SPEC — NOT applied; no vectors exist yet) ──
// Locks the quarantine boundary BEFORE index-side hypothetical-question (HyDE-style) vectors are
// added, so an LLM-generated search vector can never be confused with a canonical fact. See §9.
//
// Every search/recall vector carries:
//   provenance   : 'content' | 'hyde' | 'hypothetical_q'
//   llm_generated: boolean
// Canonical content vector  = the node's `embedding` of `long_context` (provenance:'content',
//   llm_generated:false) — already specified above; it stays the only fact-bearing vector.
// HyDE / hypothetical-question vectors = llm_generated:true, stored DISTINCTLY on a separate
//   :SearchProxy node, never on the :Entity:
//
//   MERGE (e:Entity:Issue {key:'issue:cb:42'})
//   MERGE (p:SearchProxy {key:'issue:cb:42#hq'})
//     SET p.provenance='hypothetical_q', p.llm_generated=true,
//         p.embedding=$hq_vector,                       // vector index target for recall
//         p.generated_from=['short_context','long_context'],
//         p.generated_at=datetime(), p.model='<gen-llm>', p.source_content_rev=e.content_rev
//   MERGE (p)-[:SEARCH_PROXY_FOR]->(e);                 // proxy points back to the entity it indexes
//
// Rationale for :SearchProxy over a same-node vector-namespace property (minimal option chosen):
//   a separate labelled node is the structural quarantine — D4 fact-extraction and the bi-temporal
//   MATCH engine only ever read :Entity, so a generated vector is OUT of the fact path by construction,
//   not by a filter someone must remember to apply. A 2nd embedding property on :Entity would sit
//   one forgotten WHERE-clause away from leaking into a fact. Recall hits :SearchProxy then hops
//   SEARCH_PROXY_FOR to the real node. (Do NOT also build a parallel vector-index namespace — one
//   mechanism, not two.)
//
// QUARANTINE INVARIANTS (forward contract): a :SearchProxy embedding is NEVER persisted as
// long_context, NEVER fed to D4 extraction, NEVER round-trips into a fact edge. Regenerated on the
// G1-sweep dirty-flag; eval-gated (kept only if recall@k lift is proven — gain is corpus-dependent
// and unmeasured here).
