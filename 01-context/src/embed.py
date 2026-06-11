"""D3-embed (beads cb-dfv.3): embed intrinsic node content with local EmbeddingGemma-300M ($0,
768-dim, matches the node_embedding vector index) and dual-chunk by content kind:
  prose -> contextual windows (overlapping sentence groups)
  code  -> AST chunks (one per top-level def / class)
Writes n.embedding (768 vector) + n.chunks[] + freshness stamps (embedded_at, embedding_model,
embedded_content_rev, dirty=false). The content vector is searchable via the HNSW index.
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


def embed(text):
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_node(tx, key, content, kind, now):
    """kind in {prose, code}. Chunk by kind, embed the whole content, write vector + chunks."""
    chunks = chunk_prose(content) if kind == "prose" else chunk_code(content)
    vec = embed(content)
    tx.run("MATCH (n:Entity {key:$key}) "
           "SET n.embedding=$vec, n.chunks=$chunks, n.chunk_kind=$kind, "
           "    n.embedding_model=$model, n.embedded_at=datetime($now), "
           "    n.embedded_content_rev=coalesce(n.content_rev,0), n.dirty=false",
           key=key, vec=vec, chunks=chunks, kind=kind, model=MODEL, now=now)
    return len(vec), chunks


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
            dlen, dchunks = s.execute_write(lambda tx: embed_node(tx, "emb:doc", prose, "prose", NOW))
            clen, cchunks = s.execute_write(lambda tx: embed_node(tx, "emb:code", code, "code", NOW))

            rec = s.run("MATCH (n:Entity {key:'emb:doc'}) "
                        "RETURN size(n.embedding) AS dim, n.chunk_kind AS kind, size(n.chunks) AS nchunks, "
                        "n.embedding_model AS model").single()
            crec = s.run("MATCH (n:Entity {key:'emb:code'}) "
                         "RETURN size(n.embedding) AS dim, n.chunk_kind AS kind, size(n.chunks) AS nchunks").single()
            # vector search via the HNSW index — prove the written vector is retrievable
            qvec = embed("database connection pool timeout")
            hits = s.run("CALL db.index.vector.queryNodes('node_embedding', 5, $q) "
                         "YIELD node, score WHERE node.namespace=$ns "
                         "RETURN node.key AS k, score ORDER BY score DESC", q=qvec, ns=NS).data()
            s.execute_write(lambda tx: tx.run("MATCH (n) WHERE n.namespace=$ns DETACH DELETE n", ns=NS))

    print(f"[prose] emb:doc  dim={rec['dim']} model={rec['model']} kind={rec['kind']} chunks={rec['nchunks']}")
    for c in dchunks:
        print(f"          - {c[:70]}")
    print(f"[code]  emb:code dim={crec['dim']} kind={crec['kind']} chunks={crec['nchunks']}")
    for c in cchunks:
        print(f"          - {c.splitlines()[0]}")
    print(f"[vsearch] query 'database connection pool timeout' -> {[(h['k'], round(h['score'],4)) for h in hits]}")

    fail += [] if rec["dim"] == 768 and crec["dim"] == 768 else ["embedding not 768-dim"]
    fail += [] if rec["kind"] == "prose" and rec["nchunks"] >= 1 else ["prose chunks missing"]
    fail += [] if crec["kind"] == "code" and crec["nchunks"] == 2 else ["code AST chunks wrong (expect 2: connect, Pool)"]
    fail += [] if hits and hits[0]["k"] == "emb:doc" else ["vector search did not retrieve the content vector"]

    if fail:
        print("D3_EMBED_FAIL:", fail); sys.exit(1)
    print("D3_EMBED_OK")


if __name__ == "__main__":
    demo()
