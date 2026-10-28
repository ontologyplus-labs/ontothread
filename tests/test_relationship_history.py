from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from fig.api import create_app
from fig.config import Settings
from fig.contracts import RelationshipHistoryRequest,ReviewedBundle
from fig.fixture import fixture
from fig.store import Store


def test_relationship_history_classifies_disclosures_without_inferring_termination(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"history.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();first,original=fixture()
    store.ingest(first,original,settings.archive_dir)
    data=first.model_dump(mode="json")
    data["document"]["id"]=str(uuid4());data["document"]["accession"]="synthetic-next"
    data["document"]["published_at"]=(first.document.published_at+timedelta(days=365)).isoformat()
    data["document"]["acquired_at"]=(first.document.acquired_at+timedelta(days=365)).isoformat()
    data["text_version"]["id"]=str(uuid4());data["text_version"]["document_id"]=data["document"]["id"]
    data["passage"]["id"]=str(uuid4());data["passage"]["text_version_id"]=data["text_version"]["id"]
    data["claim"]["id"]=str(uuid4());data["claim"]["claim_id"]=str(uuid4());data["claim"]["source_available_at"]=data["document"]["published_at"];data["claim"]["system_from"]=data["document"]["acquired_at"]
    data["evidence"]["id"]=str(uuid4());data["evidence"]["claim_revision_id"]=data["claim"]["id"];data["evidence"]["passage_id"]=data["passage"]["id"]
    second=ReviewedBundle.model_validate(data);store.ingest(second,original,settings.archive_dir)
    request=RelationshipHistoryRequest(subject_id=first.claim.subject_id,object_id=first.claim.object_id,predicate=first.claim.predicate)
    result=store.relationship_history(request)
    assert [event["classification"] for event in result["timelines"][0]["events"]]==["introduced","continued"]
    assert "not classified as relationship termination" in result["interpretation"]
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/relationships/history",json=request.model_dump(mode="json"))
        assert response.status_code==200 and len(response.json()["timelines"])==1
