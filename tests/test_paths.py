from uuid import uuid4
import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fig.api import create_app
from fig.config import Settings
from fig.contracts import Entity,PathRequest,ReviewedBundle
from fig.fixture import fixture
from fig.store import Store


@pytest.fixture
def graph(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"paths.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();base,original=fixture()
    entities=[Entity(id=uuid4(),kind="Company",canonical_name=name,slug=name.lower()) for name in ("Alpha","Beta","Gamma","Delta")]
    for index,(subject,object_) in enumerate(zip(entities,entities[1:])):
        data=base.model_dump(mode="json")
        data["entities"]=[item.model_dump(mode="json") for item in entities]
        data["document"]["issuer_id"]=str(entities[0].id)
        data["claim"]["id"]=str(uuid4());data["claim"]["claim_id"]=str(uuid4())
        data["claim"]["subject_id"]=str(subject.id);data["claim"]["object_id"]=str(object_.id)
        data["evidence"]["id"]=str(uuid4());data["evidence"]["claim_revision_id"]=data["claim"]["id"]
        with store.connect() as connection:
            store.persist_reviewed(connection,ReviewedBundle.model_validate(data))
    return settings,store,entities


def test_one_to_three_hop_paths_include_evidence(graph):
    _,store,entities=graph
    result=store.paths(PathRequest(source_entity_id=entities[0].id,target_entity_id=entities[3].id,min_hops=2,max_hops=3))
    assert len(result["paths"])==1 and result["paths"][0]["hops"]==3
    assert result["paths"][0]["entity_ids"]==[str(item.id) for item in entities]
    assert all(edge["evidence"][0]["evidence"]["quote"] for edge in result["paths"][0]["edges"])
    assert all(edge["traversal"]=="forward" for edge in result["paths"][0]["edges"])


def test_direction_filters_cycles_predicates_and_time(graph):
    _,store,entities=graph
    assert not store.paths(PathRequest(source_entity_id=entities[3].id,target_entity_id=entities[0].id,direction="outgoing"))["paths"]
    reverse=store.paths(PathRequest(source_entity_id=entities[3].id,target_entity_id=entities[0].id,direction="both"))
    assert reverse["paths"][0]["hops"]==3 and all(edge["traversal"]=="reverse" for edge in reverse["paths"][0]["edges"])
    assert not store.paths(PathRequest(source_entity_id=entities[0].id,predicates=["SUPPLIES_TO"]))["paths"]
    assert not store.paths(PathRequest(source_entity_id=entities[0].id,public_cutoff="2024-12-31T00:00:00Z"))["paths"]
    assert all(len(path["entity_ids"])==len(set(path["entity_ids"])) for path in reverse["paths"])


def test_path_contract_bounds_and_api(graph):
    settings,_,entities=graph
    with pytest.raises(ValidationError):PathRequest(source_entity_id=entities[0].id,min_hops=3,max_hops=2)
    with pytest.raises(ValidationError):PathRequest(source_entity_id=entities[0].id,max_hops=4)
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/graph/paths",json={"source_entity_id":str(entities[0].id),"target_entity_id":str(entities[2].id),"max_hops":2})
        assert response.status_code==200 and response.json()["paths"][0]["hops"]==2
        assert client.post("/v1/graph/paths",json={"source_entity_id":str(uuid4())}).status_code==404


def test_repeated_disclosure_is_deduplicated_by_relationship_before_enumeration(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"dedup.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();bundle,_=fixture()
    with store.connect() as conn:store.persist_reviewed(conn,bundle)
    data=copy.deepcopy(bundle.model_dump(mode="json"));data["document"]["id"]=str(uuid4());data["document"]["accession"]="repeat-disclosure"
    data["text_version"]["id"]=str(uuid4());data["text_version"]["document_id"]=data["document"]["id"]
    data["passage"]["id"]=str(uuid4());data["passage"]["text_version_id"]=data["text_version"]["id"]
    data["claim"]["id"]=str(uuid4());data["claim"]["claim_id"]=str(uuid4());data["claim"]["system_from"]="2026-10-01T00:00:00Z"
    data["evidence"]["id"]=str(uuid4());data["evidence"]["claim_revision_id"]=data["claim"]["id"];data["evidence"]["passage_id"]=data["passage"]["id"]
    with store.connect() as conn:store.persist_reviewed(conn,ReviewedBundle.model_validate(data))
    result=store.paths(PathRequest(source_entity_id=bundle.claim.subject_id,target_entity_id=bundle.claim.object_id))
    assert len(result["paths"])==1
    assert result["paths"][0]["edges"][0]["claim"]["id"]==data["claim"]["id"]
