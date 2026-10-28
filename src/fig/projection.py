"""Single-run outbox projection. Event acknowledgment follows graph commit."""
from importlib.resources import files
from neo4j import GraphDatabase
from fig.contracts import ReviewedBundle, NeighborRequest, Entity, eligible

QUERY = """
MERGE (c:ClaimRevision {id: $claim_id})
WITH c
OPTIONAL MATCH (c)-[old_endpoint:SUBJECT|OBJECT]->()
DELETE old_endpoint
WITH c
OPTIONAL MATCH ()-[old_business:BUSINESS_RELATION {claim_revision_id:$claim_id}]->()
DELETE old_business
WITH c
MERGE (s:Entity {id: $subject_id}) SET s.name=$subject_name, s.kind=$subject_kind
MERGE (o:Entity {id: $object_id}) SET o.name=$object_name, o.kind=$object_kind
SET c.predicate=$predicate, c.eligible=$eligible,
    c.ontology_version=$ontology_version, c.ontology_schema_hash=$ontology_schema_hash
MERGE (c)-[:SUBJECT]->(s)
MERGE (c)-[:OBJECT]->(o)
MERGE (d:Document {id:$document_id}) SET d.url=$source_url, d.source=$source
MERGE (p:Passage {id:$passage_id}) SET p.text=$passage_text
MERGE (c)-[:SUPPORTED_BY]->(p)
MERGE (p)-[:PART_OF]->(d)
MERGE (s)-[r:BUSINESS_RELATION {claim_revision_id:$claim_id}]->(o)
SET r.predicate=$predicate, r.eligible=$eligible, r.source_available_at=$source_available_at,
    r.system_from=$system_from, r.system_to=$system_to,
    r.valid_from=$valid_from, r.valid_to=$valid_to,
    r.ontology_version=$ontology_version, r.ontology_schema_hash=$ontology_schema_hash
"""

def parameters(bundle,subject=None,object_=None):
    entities = {e.id:e for e in bundle.entities}
    c = bundle.claim
    subject=subject or entities[c.subject_id];object_=object_ or entities[c.object_id]
    return {"subject_id":str(subject.id), "subject_name":subject.canonical_name, "subject_kind":subject.kind,
            "object_id":str(object_.id), "object_name":object_.canonical_name,"object_kind":object_.kind,
            "claim_id":str(c.id), "predicate":c.predicate,
            "ontology_version":bundle.ontology_version,"ontology_schema_hash":bundle.ontology_schema_hash,
            "eligible":eligible(c,NeighborRequest(entity_id=c.subject_id)),
            "document_id":str(bundle.document.id), "source_url":bundle.document.source_url, "source":bundle.document.source,
            "passage_id":str(bundle.passage.id), "passage_text":bundle.evidence.quote,
            **{k:bundle.claim.model_dump(mode="json")[k] for k in ("source_available_at","system_from","system_to","valid_from","valid_to")}}

def project_pending(store, uri, user, password):
    if store.fixture_mode:
        raise ValueError("Neo4j projection requires PostgreSQL mode")
    with GraphDatabase.driver(uri, auth=(user,password)) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for label in ("Entity", "ClaimRevision", "Document", "Passage"):
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
            delivered = 0
            with store.connect() as conn:
                store.execute(conn,"SELECT pg_advisory_xact_lock(184274)")
                rows = store.execute(conn,"SELECT id,payload FROM projection_outbox WHERE state='pending' ORDER BY id LIMIT 100 FOR UPDATE").fetchall()
                for row in rows:
                    bundle = ReviewedBundle.model_validate_json(row["payload"])
                    endpoints=[]
                    for endpoint in (bundle.claim.subject_id,bundle.claim.object_id):
                        canonical=store.canonical_entity_id(conn,endpoint)
                        record=store.execute(conn,"SELECT payload FROM entity WHERE id=?",(canonical,)).fetchone()
                        endpoints.append(Entity.model_validate_json(record['payload']))
                    session.execute_write(lambda tx: tx.run(QUERY, **parameters(bundle,endpoints[0],endpoints[1])).consume())
                    store.execute(conn,"UPDATE projection_outbox SET state='delivered' WHERE id=?",(row["id"],))
                    delivered += 1
            return delivered
