#!/usr/bin/env python3
import json
import array
import subprocess
from contextlib import contextmanager

from neo4j import GraphDatabase
from goms_store import GomsStore

URI = "bolt://127.0.0.1:7687"
USER = "neo4j"
KEYCHAIN_SERVICE = "aineko-goms-neo4j"


def _password():
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        text=True,
    ).strip()


@contextmanager
def driver():
    d = GraphDatabase.driver(URI, auth=(USER, _password()))
    try:
        d.verify_connectivity()
        yield d
    finally:
        d.close()


def status():
    with driver() as d:
        with d.session() as s:
            row = s.run("""
                MATCH (n:GOMS)
                OPTIONAL MATCH (n)-[r]->()
                WHERE type(r) = 'GOMS_REL'
                RETURN count(DISTINCT n) AS nodes, count(r) AS outgoing_relations
            """).single()
            return {"connected": True, "nodes": row["nodes"],
                    "outgoing_relations": row["outgoing_relations"]}


def _chunks(rows, size=1000):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]

def rebuild(store=None, batch_size=1000):
    store = store or GomsStore()
    with store.connect() as con:
        entities = [dict(r) for r in con.execute("SELECT * FROM entities").fetchall()]
        relations = [dict(r) for r in con.execute("SELECT * FROM relations").fetchall()]
        branches = [dict(r) for r in con.execute("SELECT * FROM branches").fetchall()]
        checkpoints = [dict(r) for r in con.execute("SELECT * FROM checkpoints").fetchall()]
        assertions = [dict(r) for r in con.execute("SELECT * FROM semantic_assertions").fetchall()]
        terms = [dict(r) for r in con.execute("SELECT * FROM ontology_terms").fetchall()]
        proposals = [dict(r) for r in con.execute("SELECT * FROM ontology_proposals WHERE status='candidate'").fetchall()]
        embedding_rows = [dict(r) for r in con.execute("SELECT target_kind,target_id,dimensions,vector_blob FROM semantic_embeddings").fetchall()]

    for e in entities:
        e["tags"] = json.loads(e.get("tags") or "[]")
    for b in branches:
        b["unresolved"] = json.loads(b.get("unresolved") or "[]")
    for c in checkpoints:
        c["unresolved"] = json.loads(c.get("unresolved") or "[]")
        c["provenance"] = json.dumps(json.loads(c.get("provenance") or "{}"), sort_keys=True)
    for a in assertions:
        a["metadata"] = json.dumps(json.loads(a.get("metadata") or "{}"), sort_keys=True)

    embeddings = {}
    for r in embedding_rows:
        v = array.array("f")
        v.frombytes(r["vector_blob"])
        embeddings[(r["target_kind"], r["target_id"])] = list(v)
    for e in entities:
        if ("entity", e["id"]) in embeddings:
            e["embedding"] = embeddings[("entity", e["id"])]
    for b in branches:
        if ("branch", b["id"]) in embeddings:
            b["embedding"] = embeddings[("branch", b["id"])]
    for t in terms:
        if ("ontology_term", t["id"]) in embeddings:
            t["embedding"] = embeddings[("ontology_term", t["id"])]
    for p in proposals:
        if ("ontology_proposal", p["id"]) in embeddings:
            p["embedding"] = embeddings[("ontology_proposal", p["id"])]

    with driver() as d:
        with d.session() as s:
            s.run("MATCH (n:GOMS) DETACH DELETE n").consume()
            s.run("CREATE CONSTRAINT goms_id IF NOT EXISTS FOR (n:GOMS) REQUIRE n.id IS UNIQUE").consume()

            for rows in _chunks(entities, batch_size):
                s.run("""
                    UNWIND $rows AS e
                    MERGE (n:GOMS:Memory {id:e.id})
                    SET n.type=e.type, n.title=e.title, n.summary=e.summary,
                        n.project=e.project, n.status=e.status, n.confidence=e.confidence,
                        n.source=e.source, n.tags=e.tags, n.updated_at=e.updated_at,
                        n.embedding=e.embedding
                """, rows=rows).consume()

            for rows in _chunks(relations, batch_size):
                s.run("""
                    UNWIND $rows AS x
                    MATCH (a:GOMS {id:x.src}), (b:GOMS {id:x.dst})
                    MERGE (a)-[r:GOMS_REL {kind:x.rel}]->(b)
                    SET r.evidence=x.evidence, r.created_at=x.created_at
                """, rows=rows).consume()

            for rows in _chunks(branches, batch_size):
                s.run("""
                    UNWIND $rows AS b
                    MERGE (n:GOMS:Branch {id:b.id})
                    SET n.title=b.title, n.project=b.project, n.status=b.status,
                        n.objective=b.objective, n.last_result=b.last_result,
                        n.unresolved=b.unresolved, n.next_action=b.next_action,
                        n.blocker=b.blocker, n.worker=b.worker, n.updated_at=b.updated_at,
                        n.embedding=b.embedding
                """, rows=rows).consume()

            parent_rows=[b for b in branches if b.get("parent_branch")]
            for rows in _chunks(parent_rows, batch_size):
                s.run("""
                    UNWIND $rows AS b
                    MATCH (child:GOMS:Branch {id:b.id}), (parent:GOMS:Branch {id:b.parent_branch})
                    MERGE (child)-[:PARENT_BRANCH]->(parent)
                """, rows=rows).consume()

            for rows in _chunks(checkpoints, batch_size):
                s.run("""
                    UNWIND $rows AS c
                    MERGE (n:GOMS:Checkpoint {id:c.id})
                    SET n.status=c.status, n.summary=c.summary,
                        n.unresolved=c.unresolved, n.next_action=c.next_action,
                        n.blocker=c.blocker, n.provenance=c.provenance,
                        n.created_at=c.created_at
                    WITH c
                    MATCH (b:GOMS:Branch {id:c.branch_id}), (n:GOMS:Checkpoint {id:c.id})
                    MERGE (b)-[:HAS_CHECKPOINT]->(n)
                """, rows=rows).consume()

            for rows in _chunks(terms, batch_size):
                s.run("""
                    UNWIND $rows AS t
                    MERGE (n:GOMS:OntologyTerm {id:t.id})
                    SET n.kind=t.kind, n.canonical_name=t.canonical_name,
                        n.description=t.description, n.status=t.status,
                        n.version=t.version, n.updated_at=t.updated_at,
                        n.embedding=t.embedding
                """, rows=rows).consume()

            for rows in _chunks(proposals, batch_size):
                s.run("""
                    UNWIND $rows AS p
                    MERGE (n:GOMS:OntologyProposal {id:p.id})
                    SET n.proposal_type=p.proposal_type, n.canonical_name=p.canonical_name,
                        n.description=p.description, n.evidence_count=p.evidence_count,
                        n.confidence=p.confidence, n.status=p.status,
                        n.rationale=p.rationale, n.updated_at=p.updated_at,
                        n.embedding=p.embedding
                """, rows=rows).consume()

            obj_assertions=[a for a in assertions if a.get("object_id")]
            lit_assertions=[a for a in assertions if not a.get("object_id")]
            for rows in _chunks(obj_assertions, batch_size):
                s.run("""
                    UNWIND $rows AS a
                    MATCH (x:GOMS {id:a.subject_id}), (y:GOMS {id:a.object_id})
                    MERGE (x)-[r:SEMANTIC_ASSERTION {id:a.id}]->(y)
                    SET r.predicate=a.predicate, r.confidence=a.confidence,
                        r.epistemic_status=a.epistemic_status,
                        r.valid_from=a.valid_from, r.valid_to=a.valid_to,
                        r.source_entity_id=a.source_entity_id, r.source_ref=a.source_ref,
                        r.supersedes=a.supersedes, r.metadata=a.metadata, r.updated_at=a.updated_at
                """, rows=rows).consume()
            s.run("""
                CREATE VECTOR INDEX goms_embedding IF NOT EXISTS
                FOR (n:GOMS) ON (n.embedding)
                OPTIONS {indexConfig: {
                  `vector.dimensions`: 768,
                  `vector.similarity_function`: 'cosine'
                }}
            """).consume()

            for rows in _chunks(lit_assertions, batch_size):
                s.run("""
                    UNWIND $rows AS a
                    MATCH (x:GOMS {id:a.subject_id})
                    MERGE (n:GOMS:AssertionLiteral {id:a.id})
                    SET n.predicate=a.predicate, n.value=a.literal_value,
                        n.confidence=a.confidence, n.epistemic_status=a.epistemic_status,
                        n.source_ref=a.source_ref, n.updated_at=a.updated_at
                    MERGE (x)-[:HAS_ASSERTION]->(n)
                """, rows=rows).consume()

    return {"entities": len(entities), "relations": len(relations),
            "branches": len(branches), "checkpoints": len(checkpoints),
            "assertions": len(assertions), "ontology_terms": len(terms),
            "ontology_proposals": len(proposals), "embeddings": len(embedding_rows)}

def neighbors(node_id, limit=50):
    limit = max(1, min(int(limit), 200))
    with driver() as d:
        with d.session() as s:
            rows = s.run("""
                MATCH (n:GOMS {id:$id})-[r]-(m:GOMS)
                RETURN type(r) AS edge_type, r.kind AS relation,
                       m.id AS id, labels(m) AS labels,
                       m.type AS type, m.title AS title,
                       m.project AS project, m.status AS status
                LIMIT $limit
            """, id=node_id, limit=limit)
            return [dict(row) for row in rows]


def vector_search(embedding, limit=10):
    limit=max(1,min(int(limit),100))
    with driver() as d:
        with d.session() as s:
            rows=s.run("""
                CALL db.index.vector.queryNodes('goms_embedding', $limit, $embedding)
                YIELD node, score
                RETURN node.id AS id, labels(node) AS labels,
                       node.type AS type, coalesce(node.title,node.canonical_name) AS title,
                       node.summary AS summary, score
                ORDER BY score DESC
            """, limit=limit, embedding=embedding)
            return [dict(r) for r in rows]
