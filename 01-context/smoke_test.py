"""A2 smoke test: neo4j-graphrag-python client connects + write + read-back."""
import os
from neo4j import GraphDatabase  # bundled by neo4j-graphrag-python

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
AUTH = ("neo4j", os.environ.get("NEO4J_PASSWORD", "companybrain"))  # local dev


def main() -> None:
    with GraphDatabase.driver(URI, auth=AUTH) as drv:
        drv.verify_connectivity()
        with drv.session() as s:
            s.run("MERGE (n:CBSmoke {id:'a2'}) SET n.note=$v", v="hello-from-A2")
            rec = s.run(
                "MATCH (n:CBSmoke {id:'a2'}) RETURN n.id AS id, n.note AS note"
            ).single()
            print(f"READBACK id={rec['id']} note={rec['note']}")
            s.run("MATCH (n:CBSmoke {id:'a2'}) DELETE n")  # cleanup
    import neo4j_graphrag
    print(f"neo4j_graphrag importable: v{getattr(neo4j_graphrag, '__version__', '(installed)')}")
    print("A2_SMOKE_OK")


if __name__ == "__main__":
    main()
