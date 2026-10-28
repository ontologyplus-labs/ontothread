from datetime import datetime,timedelta
from pathlib import Path
import copy
from uuid import uuid4

from fig.config import Settings
from fig.contracts import NeighborRequest,ReviewedBundle
from fig.fixture import fixture
from fig.store import Store


def test_retraction_preserves_historical_relationship(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"lifecycle.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    bundle,original=fixture();store.ingest(bundle,original,settings.archive_dir)
    current=store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))
    relationship_id=current["relationships"][0]["relationship_id"]
    decision=store.record_claim_lifecycle(relationship_id,action="retract",reviewer="test-reviewer",notes="Controlled retraction test.")
    assert not store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))["relationships"]
    before=datetime.fromisoformat(decision["decided_at"].replace("Z","+00:00"))-timedelta(microseconds=1)
    assert store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id,knowledge_cutoff=before))["relationships"]
    history=store.relationship_lifecycle(relationship_id)
    assert history["claims"][0]["id"]==str(bundle.claim.id) and history["decisions"][0]["action"]=="retract"


def test_claim_lifecycle_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/010_claim_lifecycle.sql").read_bytes()==(root/"src/fig/resources/010_claim_lifecycle.sql").read_bytes()


def test_reviewed_contradiction_preserves_both_claims_and_historical_audit(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"conflict.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    positive,_=fixture()
    with store.connect() as conn:store.persist_reviewed(conn,positive)
    data=copy.deepcopy(positive.model_dump(mode="json"));data["document"]["id"]=str(uuid4());data["document"]["accession"]="contradiction"
    data["text_version"]["id"]=str(uuid4());data["text_version"]["document_id"]=data["document"]["id"]
    data["passage"]["id"]=str(uuid4());data["passage"]["text_version_id"]=data["text_version"]["id"]
    data["claim"]["id"]=str(uuid4());data["claim"]["claim_id"]=str(uuid4());data["claim"]["polarity"]="negative";data["claim"]["system_from"]="2026-10-01T00:00:00Z"
    data["evidence"]["id"]=str(uuid4());data["evidence"]["claim_revision_id"]=data["claim"]["id"];data["evidence"]["passage_id"]=data["passage"]["id"]
    negative=ReviewedBundle.model_validate(data)
    with store.connect() as conn:store.persist_reviewed(conn,negative)
    relationship_id=store.neighbors(NeighborRequest(entity_id=positive.claim.subject_id))["relationships"][0]["relationship_id"]
    decision=store.record_claim_lifecycle(relationship_id,action="retain_conflict",reviewer="test-reviewer",notes="Both explicit statements remain source evidence.",claim_revision_id=positive.claim.id,conflicting_claim_revision_id=negative.claim.id)
    current=store.relationship_lifecycle(relationship_id)
    assert {claim["polarity"] for claim in current["claims"]}=={"positive","negative"} and current["decisions"][0]["action"]=="retain_conflict"
    before=datetime.fromisoformat(decision["decided_at"].replace("Z","+00:00"))-timedelta(microseconds=1)
    assert store.relationship_lifecycle(relationship_id,before)["decisions"]==[]
