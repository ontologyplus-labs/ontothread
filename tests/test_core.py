import copy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from fig.api import create_app
from fig.config import Settings
from fig.contracts import ReviewedBundle, NeighborRequest
from fig.fixture import fixture
from fig.store import Store, ImmutableConflict

@pytest.fixture
def setup(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"test.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url)
    store.migrate()
    bundle, original=fixture()
    return settings,store,bundle,original

def test_idempotency_and_exact_evidence(setup):
    settings,store,bundle,original=setup
    store.ingest(bundle,original,settings.archive_dir)
    store.ingest(bundle,original,settings.archive_dir)
    store.migrate()
    response=store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))
    assert len(response["relationships"])==1
    evidence=response["relationships"][0]["evidence"][0]
    assert evidence["document"]["source"]=="synthetic_fixture"
    assert evidence["evidence"]["quote"]==bundle.evidence.quote
    assert (settings.archive_dir/bundle.document.content_hash).read_bytes()==original
    with store.connect() as conn:
        assert store.execute(conn,"SELECT COUNT(*) AS n FROM projection_outbox").fetchone()["n"]==1

def test_temporal_cutoffs_direction_and_unknown_validity(setup):
    settings,store,bundle,original=setup
    store.ingest(bundle,original,settings.archive_dir)
    def query(**kwargs):
        return store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id,**kwargs))["relationships"]
    assert not query(public_cutoff="2024-12-31T23:59:59Z")
    assert query(public_cutoff="2025-01-01T00:00:00Z")
    assert not query(knowledge_cutoff="2025-01-01T00:00:00Z")
    assert query(knowledge_cutoff="2025-01-02T00:00:00Z")
    assert not query(effective_at="2025-01-02T00:00:00Z")
    assert not query(direction="incoming")
    assert query(direction="outgoing")

def test_fractional_timestamp_boundary(setup):
    settings,store,bundle,original=setup
    data=bundle.model_dump(mode="json")
    data["claim"]["system_from"]="2025-01-02T00:00:00.000001Z"
    bundle=ReviewedBundle.model_validate(data)
    store.ingest(bundle,original,settings.archive_dir)
    assert not store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id,knowledge_cutoff="2025-01-02T00:00:00Z"))["relationships"]

def test_quote_corruption_and_ontology_rejected():
    bundle,_=fixture()
    for key,value in (("quote","invented relationship"),("start_offset",-1)):
        data=bundle.model_dump(mode="json")
        data["evidence"][key]=value
        with pytest.raises(ValidationError):
            ReviewedBundle.model_validate(data)
    data=bundle.model_dump(mode="json")
    data["claim"]["predicate"]="INVENTED_PREDICATE"
    with pytest.raises(ValidationError):
        ReviewedBundle.model_validate(data)

def test_unicode_spans():
    bundle,_=fixture()
    data=bundle.model_dump(mode="json")
    text="🚀\n"+bundle.text_version.normalized_text
    data["text_version"]["normalized_text"]=text
    data["text_version"]["normalized_hash"]=sha256(text.encode()).hexdigest()
    for item in ("passage","evidence"):
        data[item]["start_offset"]+=2
        data[item]["end_offset"]+=2
    valid=ReviewedBundle.model_validate(data)
    assert valid.text_version.normalized_text[valid.evidence.start_offset:valid.evidence.end_offset]==valid.evidence.quote

def test_conflict_rolls_back_new_records(setup):
    settings,store,bundle,original=setup
    store.ingest(bundle,original,settings.archive_dir)
    data=bundle.model_dump(mode="json")
    data["claim"]["reviewer"]="different-content-same-id"
    with pytest.raises(ImmutableConflict):
        store.ingest(ReviewedBundle.model_validate(data),original,settings.archive_dir)
    assert store.health()["pending_projection_events"]==1

def test_original_bytes_validated_before_ingestion(setup):
    settings,store,bundle,_=setup
    with store.connect() as conn:
        before=store.execute(conn,"SELECT COUNT(*) AS n FROM entity").fetchone()["n"]
    with pytest.raises(ValueError,match="checksum"):
        store.ingest(bundle,b"wrong source",settings.archive_dir)
    with store.connect() as conn:
        assert store.execute(conn,"SELECT COUNT(*) AS n FROM entity").fetchone()["n"]==before

def test_negative_inferred_and_pending_are_not_traversable(setup):
    settings,store,bundle,original=setup
    for key,value in (("polarity","negative"),("assertion_class","inferred"),("review_state","pending")):
        data=bundle.model_dump(mode="json")
        data["claim"][key]=value
        changed=ReviewedBundle.model_validate(data)
        # Independent stores avoid reuse of immutable IDs.
        fresh=Store(settings.database_url+"-"+key)
        fresh.migrate()
        fresh.ingest(changed,original,settings.archive_dir)
        assert not fresh.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))["relationships"]

def test_api_and_validation(setup):
    settings,store,bundle,original=setup
    store.ingest(bundle,original,settings.archive_dir)
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/health").status_code==200
        result=client.post("/v1/graph/neighbors",json={"entity_id":str(bundle.claim.subject_id)})
        assert result.status_code==200
        assert len(result.json()["relationships"])==1
        assert client.post("/v1/graph/neighbors",json={"entity_id":"bad"}).status_code==422
        assert client.post("/v1/graph/neighbors",json={"entity_id":str(bundle.claim.subject_id),"public_cutoff":"2025-01-01"}).status_code==422
        assert client.post("/v1/graph/neighbors",json={"entity_id":"00000000-0000-0000-0000-000000000000"}).status_code==404

def test_missing_migration_is_unhealthy(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"empty.sqlite3"),tmp_path/"archive")
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/health").status_code==503


def test_packaged_resources_match_authoring_sources():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/001_core.sql").read_bytes()==(root/"src/fig/resources/001_core.sql").read_bytes()
    assert (root/"ontology/finance-v1.yaml").read_bytes()==(root/"src/fig/resources/finance-v1.yaml").read_bytes()
    assert (root/"ontology/finance-v2.yaml").read_bytes()==(root/"src/fig/resources/finance-v2.yaml").read_bytes()

def test_increasing_interval_and_end_exclusion(setup):
    settings,store,bundle,original=setup
    data=bundle.model_dump(mode="json")
    data["claim"]["valid_from"]="2025-01-01T00:00:00Z"
    data["claim"]["valid_to"]="2025-02-01T00:00:00Z"
    valid=ReviewedBundle.model_validate(data)
    store.ingest(valid,original,settings.archive_dir)
    assert store.neighbors(NeighborRequest(entity_id=valid.claim.subject_id,effective_at="2025-01-01T00:00:00Z"))["relationships"]
    assert not store.neighbors(NeighborRequest(entity_id=valid.claim.subject_id,effective_at="2025-02-01T00:00:00Z"))["relationships"]
    data["claim"]["valid_to"]="2025-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        ReviewedBundle.model_validate(data)

def test_rejected_unreviewed_endpoints():
    bundle,_=fixture()
    data=bundle.model_dump(mode="json")
    data["entities"][0]["status"]="provisional"
    with pytest.raises(ValidationError):
        ReviewedBundle.model_validate(data)
