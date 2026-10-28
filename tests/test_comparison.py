from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fig.api import create_app
from fig.config import Settings
from fig.contracts import DocumentComparisonRequest,SourceBundle
from fig.fixture import fixture
from fig.store import Store


@pytest.fixture
def comparison(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"comparison.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();base,original=fixture()
    first=SourceBundle(issuer=base.entities[0],document=base.document,text_version=base.text_version,passages=[base.passage],quality_flags=[])
    store.ingest_source(first,original,settings.archive_dir)
    data=first.model_dump(mode="json");data["document"]["id"]=str(uuid4());data["document"]["accession"]="synthetic-002";data["document"]["published_at"]=(first.document.published_at+timedelta(days=365)).isoformat();data["document"]["acquired_at"]=(first.document.acquired_at+timedelta(days=365)).isoformat();data["text_version"]["id"]=str(uuid4());data["text_version"]["document_id"]=data["document"]["id"];data["passages"][0]["id"]=str(uuid4());data["passages"][0]["text_version_id"]=data["text_version"]["id"]
    second=SourceBundle.model_validate(data);store.ingest_source(second,original,settings.archive_dir)
    return settings,store,first,second


def test_document_comparison_pairs_exact_passages(comparison):
    _,store,first,second=comparison
    result=store.compare_documents(DocumentComparisonRequest(left_document_id=first.document.id,right_document_id=second.document.id,query="manufacturing"))
    assert result["left_match_count"]==result["right_match_count"]==1
    assert result["pairs"][0]["classification"]=="unchanged" and result["pairs"][0]["similarity"]==1
    assert result["left_document"]["published_at"]<result["right_document"]["published_at"]


def test_comparison_contract_issuer_guard_and_api(comparison):
    settings,store,first,second=comparison
    with pytest.raises(ValidationError):DocumentComparisonRequest(left_document_id=first.document.id,right_document_id=first.document.id,query="x")
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/documents/compare",json={"left_document_id":str(first.document.id),"right_document_id":str(second.document.id),"query":"Foundry"})
        assert response.status_code==200 and response.json()["pairs"][0]["classification"]=="unchanged"
        missing=client.post("/v1/documents/compare",json={"left_document_id":str(uuid4()),"right_document_id":str(second.document.id),"query":"Foundry"})
        assert missing.status_code==404
