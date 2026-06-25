"""D3-embed (the Context-Engineering epic): embed intrinsic node content with local EmbeddingGemma-300M ($0,
768-dim, matches the node_embedding vector index) and dual-chunk by content kind:
  prose -> contextual windows (overlapping sentence groups)
  code  -> AST chunks (one per top-level def / class)
Writes n.embedding (768 node-level vector) + n.chunks[] (text) + n.chunk_count + freshness stamps
(embedded_at, embedding_model, embedded_content_rev, dirty=false). The node vector is searchable via the
node_embedding HNSW index (rung 2, "which node").

cf7 — CHUNK-LEVEL VECTOR (rung 2b, "which passage"): when a node splits into >1 chunk, each chunk is
ALSO embedded and materialized as a :Chunk node (one indexed vector each) linked (:Entity)-[:HAS_CHUNK]->
(:Chunk), searchable via the chunk_embedding HNSW index. Neo4j HNSW indexes ONE vector per node, so
multi-chunk recall lives on :Chunk nodes, NOT a vector-list on :Entity (supersedes HYBRID §5b wording).
A SINGLE-chunk node gets NO :Chunk node — its passage is long_context, returned directly (HYBRID §3; bzr).
ZERO external API — the model runs locally.
"""
import ast
import sys
from functools import lru_cache
from neo4j import GraphDatabase

URI, AUTH = "bolt://localhost:7687", ("neo4j", "companybrain")
MODEL = "google/embeddinggemma-300m"


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL)


def chunk_prose(text, size=2, overlap=1):
    """Contextual chunking: overlapping windows of `size` sentences (stride size-overlap)."""
    sents = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
    if not sents:
        return [text]
    stride = max(1, size - overlap)
    return [". ".join(sents[i:i + size]) for i in range(0, len(sents), stride)]


def chunk_code(src):
    """AST chunking: one chunk per top-level function / class, labelled by kind:name."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [src]
    lines = src.splitlines()
    chunks = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seg = "\n".join(lines[node.lineno - 1:node.end_lineno])
            chunks.append(f"{type(node).__name__}:{node.name}\n{seg}")
    return chunks or [src]


def detect_kind(content):
    """Prose-vs-code classifier for the real seeding path (5iz). Content is 'code' iff it parses as
    Python AND defines >=1 top-level function/class — exactly the unit chunk_code splits on, so the
    classifier and the chunker agree by construction. Anything that fails to parse, OR parses but is
    a bare script / prose that happens to be valid Python (e.g. 'status=open'), is 'prose'. This stops
    embed_all from AST-vs-sentence mis-chunking: a real code blob now routes to chunk_code, while every
    existing prose node still classifies prose (no behavior change on the current seed)."""
    if not content:                               # None/empty -> prose (ast.parse(None) would TypeError)
        return "prose"
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return "prose"
    return "code" if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                         for n in tree.body) else "prose"


def embed(text):
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_node(tx, key, content, kind, now):
    """kind in {prose, code}. Chunk by kind, embed the whole content (node-level vector), write vector +
    chunks[] + chunk_count. When the node splits into >1 chunk, ALSO embed each chunk and materialize a
    :Chunk node per chunk for rung-2b recall (cf7). Single-chunk -> no :Chunk node (bzr returns directly).
    Returns (vector_dim, chunks, n_chunk_nodes)."""
    chunks = chunk_prose(content) if kind == "prose" else chunk_code(content)
    vec = embed(content)
    tx.run("MATCH (n:Entity {key:$key}) "
           "SET n.embedding=$vec, n.chunks=$chunks, n.chunk_kind=$kind, n.chunk_count=$ccount, "
           "    n.embedding_model=$model, n.embedded_at=datetime($now), "
           "    n.embedded_content_rev=coalesce(n.content_rev,0), n.dirty=false",
           key=key, vec=vec, chunks=chunks, kind=kind, ccount=len(chunks), model=MODEL, now=now)
    # Idempotent re-embed: drop any prior :Chunk children before (re)materializing, so a content edit that
    # changes the chunk split never leaves orphaned stale chunks behind.
    tx.run("MATCH (:Entity {key:$key})-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c", key=key)
    n_chunk_nodes = _materialize_chunks(tx, key, chunks, kind, now) if len(chunks) > 1 else 0
    return len(vec), chunks, n_chunk_nodes


def _materialize_chunks(tx, key, chunks, kind, now):
    """Create one :Chunk node per chunk (each with its OWN 768-dim embedding) linked HAS_CHUNK {ord},
    carrying the parent's namespace so chunk recall is namespace-post-filterable like node recall.
    Key convention = '<parent_key>#<ord>'. Returns the count materialized. Multi-chunk callers only."""
    rec = tx.run("MATCH (n:Entity {key:$key}) RETURN n.namespace AS ns", key=key).single()
    ns = rec["ns"] if rec else None
    for ord_, ctext in enumerate(chunks):
        cvec = embed(ctext)
        tx.run("MATCH (e:Entity {key:$pkey}) "
               "MERGE (c:Chunk {key:$ckey}) "
               "SET c.parent_key=$pkey, c.namespace=$ns, c.ord=$ord, c.text=$text, "
               "    c.chunk_kind=$kind, c.embedding=$vec, c.embedded_at=datetime($now) "
               "MERGE (e)-[h:HAS_CHUNK]->(c) "
               "SET h.ord=$ord, h.namespace=$ns",
               pkey=key, ckey=f"{key}#{ord_}", ns=ns, ord=ord_, text=ctext, kind=kind, vec=cvec, now=now)
    return len(chunks)


def assert_chunk_namespace_isolation(s):
    """Structural isolation proof (mirrors communities.assert_no_cross_namespace_community): every :Chunk's
    own namespace AND its :HAS_CHUNK edge namespace must equal its parent :Entity's namespace (non-null),
    and parent_key must match — else a chunk recalled by chunk_embedding could leak across a role boundary.
    Also flags orphan chunks (no parent edge = dead-stored, the cf7/bzr bug class). Raises on violation."""
    leak = s.run(
        "MATCH (e:Entity)-[h:HAS_CHUNK]->(c:Chunk) "
        "WHERE c.namespace IS NULL OR h.namespace IS NULL "
        "   OR c.namespace <> e.namespace OR h.namespace <> e.namespace OR c.parent_key <> e.key "
        "RETURN c.key AS k, c.namespace AS cns, e.namespace AS ens LIMIT 5").data()
    orphan = s.run("MATCH (c:Chunk) WHERE NOT ( (:Entity)-[:HAS_CHUNK]->(c) ) RETURN c.key AS k LIMIT 5").data()
    if leak or orphan:
        raise AssertionError(f"chunk isolation violated: leak={leak} orphan={orphan}")


def demo():
    from mutate import resolve_entity
    NS, NOW = "embed_test", "2026-06-04T00:00:00Z"
    fail = []
    prose = ("The bolt driver connection pool exhausts under sustained load. "
             "Idle connections are not reclaimed. The fix raises max-pool-size and adds a reaper.")
    code = ("def connect(uri, auth):\n    return GraphDatabase.driver(uri, auth=auth)\n\n"
            "class Pool:\n    def acquire(self):\n        return self._free.pop()\n")
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))
            s.execute_write(lambda tx: resolve_entity(tx, "Episodic", "emb:doc", NOW, NS, short="doc", long_=prose))
            s.execute_write(lambda tx: resolve_entity(tx, "Repo", "emb:code", NOW, NS, short="code", long_=code))
            dlen, dchunks, dcn = s.execute_write(lambda tx: embed_node(tx, "emb:doc", prose, "prose", NOW))
            clen, cchunks, ccn = s.execute_write(lambda tx: embed_node(tx, "emb:code", code, "code", NOW))

            rec = s.run("MATCH (n:Entity {key:'emb:doc'}) "
                        "RETURN size(n.embedding) AS dim, n.chunk_kind AS kind, size(n.chunks) AS nchunks, "
                        "n.chunk_count AS ccount, n.embedding_model AS model").single()
            crec = s.run("MATCH (n:Entity {key:'emb:code'}) "
                         "RETURN size(n.embedding) AS dim, n.chunk_kind AS kind, size(n.chunks) AS nchunks").single()
            # :Chunk materialization (cf7) — each multi-chunk node gets one indexed :Chunk per chunk
            dchk = s.run("MATCH (:Entity {key:'emb:doc'})-[:HAS_CHUNK]->(c:Chunk) "
                         "RETURN count(c) AS n, size(collect(c.embedding)[0]) AS dim").single()
            # rung 2 — node-level vector search: prove the written NODE vector is retrievable
            qvec = embed("database connection pool timeout")
            hits = s.run("CALL db.index.vector.queryNodes('node_embedding', 5, $q) "
                         "YIELD node, score WHERE node.namespace=$ns "
                         "RETURN node.key AS k, score ORDER BY score DESC", q=qvec, ns=NS).data()
            # rung 2b — chunk-level vector search (cf7): a PASSAGE-specific query retrieves the matching
            # :Chunk, resolving to its parent node; namespace post-filtered like node recall
            cqvec = embed("a reaper that reclaims idle pooled connections")
            chits = s.run("CALL db.index.vector.queryNodes('chunk_embedding', 5, $q) "
                          "YIELD node, score WHERE node.namespace=$ns "
                          "RETURN node.parent_key AS parent, node.text AS text, score ORDER BY score DESC",
                          q=cqvec, ns=NS).data()
            assert_chunk_namespace_isolation(s)            # raises on leak/orphan BEFORE cleanup
            # cleanup: (n) with no label matches :Entity AND :Chunk (both carry namespace=$ns)
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))

    print(f"[prose] emb:doc  dim={rec['dim']} model={rec['model']} kind={rec['kind']} chunks={rec['nchunks']} chunk_nodes={dcn}")
    for c in dchunks:
        print(f"          - {c[:70]}")
    print(f"[code]  emb:code dim={crec['dim']} kind={crec['kind']} chunks={crec['nchunks']} chunk_nodes={ccn}")
    for c in cchunks:
        print(f"          - {c.splitlines()[0]}")
    print(f"[vsearch node]  query 'database connection pool timeout' -> {[(h['k'], round(h['score'],4)) for h in hits]}")
    print(f"[vsearch chunk] query 'a reaper that reclaims idle pooled connections' ->")
    for h in chits[:3]:
        print(f"          - parent={h['parent']} score={round(h['score'],4)} :: {h['text'][:60]}")

    fail += [] if rec["dim"] == 768 and crec["dim"] == 768 else ["embedding not 768-dim"]
    fail += [] if rec["kind"] == "prose" and rec["nchunks"] >= 1 else ["prose chunks missing"]
    fail += [] if crec["kind"] == "code" and crec["nchunks"] == 2 else ["code AST chunks wrong (expect 2: connect, Pool)"]
    fail += [] if hits and hits[0]["k"] == "emb:doc" else ["node vector search did not retrieve the content vector"]
    # cf7 chunk-path gates
    fail += [] if dcn == rec["ccount"] and dcn >= 2 else [f"prose :Chunk nodes wrong (got {dcn}, expect chunk_count={rec['ccount']})"]
    fail += [] if ccn == 2 else [f"code :Chunk nodes wrong (got {ccn}, expect 2: connect, Pool)"]
    fail += [] if dchk["n"] == dcn and dchk["dim"] == 768 else ["chunk embedding missing/not 768-dim"]
    fail += [] if chits and chits[0]["parent"] == "emb:doc" else ["chunk vector search did not retrieve a chunk of emb:doc"]

    if fail:
        print("D3_EMBED_FAIL:", fail); sys.exit(1)
    print("D3_EMBED_OK")


if __name__ == "__main__":
    demo()
