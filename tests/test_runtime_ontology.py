from pathlib import Path
from datetime import datetime,timezone
from uuid import NAMESPACE_URL,uuid5
from fig.config import Settings
from fig.contracts import ClaimRevision,Entity,Evidence,NeighborRequest,OntologyProposalCreate,OntologyProposalDecision,ReviewedBundle
from fig.fixture import fixture
from fig.ontology_runtime import RuntimeOntology
from fig.store import Store


def test_runtime_ontology_rejects_missing_and_accepts_seeded_predicate(tmp_path):
    store=Store("sqlite:///"+str(tmp_path/"runtime.sqlite3"));store.migrate();ontology=RuntimeOntology.from_store(store,"finance-v2")
    assert ontology.relationship_errors("Company","PROVIDES_ADVANCED_PACKAGING","Technology")
    assert ontology.validate_relationship("Company","CONTRACTS_MANUFACTURING_TO","Company")["valid"] is True


def test_runtime_ontology_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/009_runtime_ontology.sql").read_bytes()==(root/"src/fig/resources/009_runtime_ontology.sql").read_bytes()


def test_migrate_backfills_runtime_validation_for_legacy_claims(tmp_path):
    store=Store("sqlite:///"+str(tmp_path/"legacy.sqlite3"));store.migrate();bundle,_=fixture()
    with store.connect() as conn:
        store.persist_reviewed(conn,bundle)
        store.execute(conn,"DELETE FROM claim_ontology_validation WHERE claim_revision_id=?",(str(bundle.claim.id),))
    store.migrate()
    with store.connect() as conn:row=store.execute(conn,"SELECT ontology_version,validator FROM claim_ontology_validation WHERE claim_revision_id=?",(str(bundle.claim.id),)).fetchone()
    assert row["ontology_version"]=="finance-v2" and row["validator"]=="migration-backfill-v1"


def test_child_ontology_enables_new_reviewed_relationship_without_changing_parent(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"evolution.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    original_bundle,original=fixture();store.ingest(original_bundle,original,settings.archive_dir)
    proposal=store.create_ontology_proposal(OntologyProposalCreate(change_type="add_predicate",concept_name="PROVIDES_TEST_TECHNOLOGY",
        definition="The subject company explicitly provides the object technology to customers.",rationale="The test evidence requires a Company-to-Technology provider predicate.",
        proposed_schema={"subject":["Company"],"object":["Technology"]},evidence_passage_ids=[original_bundle.passage.id],recurrence_count=1,
        base_ontology_version="finance-v2",proposer="test"))
    accepted=store.decide_ontology_proposal(proposal["id"],OntologyProposalDecision(action="accept",expected_version=1,reviewer="test-reviewer",
        notes="Controlled test decision.",migration_notes="Add the predicate for the isolated regression case."))
    version=accepted["migration"]["to_version"];runtime=RuntimeOntology.from_store(store,version)
    technology=Entity(id=uuid5(NAMESPACE_URL,"fig:test:technology"),kind="Technology",canonical_name="Test Technology",slug="test-technology")
    key="fig:test:evolved-claim";claim_id=uuid5(NAMESPACE_URL,key);revision_id=uuid5(NAMESPACE_URL,key+":revision")
    claim=ClaimRevision(id=revision_id,claim_id=claim_id,subject_id=original_bundle.document.issuer_id,object_id=technology.id,
        predicate="PROVIDES_TEST_TECHNOLOGY",review_state="accepted",reviewer="test-reviewer",source_available_at=original_bundle.document.published_at,
        system_from=max(datetime.now(timezone.utc),original_bundle.document.acquired_at))
    evidence=Evidence(id=uuid5(NAMESPACE_URL,key+":evidence"),claim_revision_id=revision_id,passage_id=original_bundle.passage.id,
        quote=original_bundle.evidence.quote,start_offset=original_bundle.evidence.start_offset,end_offset=original_bundle.evidence.end_offset,assessment="supported")
    evolved=ReviewedBundle(ontology_version=version,ontology_schema_hash=runtime.schema_hash,
        entities=[next(e for e in original_bundle.entities if e.id==original_bundle.document.issuer_id),technology],document=original_bundle.document,
        text_version=original_bundle.text_version,passage=original_bundle.passage,claim=claim,evidence=evidence)
    with store.connect() as conn:store.persist_reviewed(conn,evolved)
    old=store.neighbors(NeighborRequest(entity_id=original_bundle.document.issuer_id,ontology_version="finance-v2",limit=100))
    new=store.neighbors(NeighborRequest(entity_id=original_bundle.document.issuer_id,ontology_version=version,limit=100))
    assert not any(r["claim"]["predicate"]=="PROVIDES_TEST_TECHNOLOGY" for r in old["relationships"])
    assert any(r["claim"]["predicate"]=="PROVIDES_TEST_TECHNOLOGY" for r in new["relationships"])
