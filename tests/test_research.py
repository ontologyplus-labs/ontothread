import copy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from fig.api import create_app
from fig.config import Settings
from fig.contracts import Entity,ResearchRequest,ReviewedBundle
from fig.fixture import fixture
from fig.research import ResearchService,validate_readonly_cypher
from fig.store import Store


def research_setup(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"research.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();first,original=fixture()
    data=first.model_dump(mode="json");data['entities'][0]['slug']='sec-cik-1045810'
    first=ReviewedBundle.model_validate(data);store.ingest(first,original,settings.archive_dir);store.seed_core_registry()
    return settings,store,first


def test_controlled_research_resolves_alias_returns_evidence_and_cypher(tmp_path):
    settings,store,bundle=research_setup(tmp_path)
    result=ResearchService(store).ask(ResearchRequest(question="Which companies are connected to NVDA within three hops?"))
    assert result['resolved_entities'][0]['id']==str(bundle.claim.subject_id)
    assert result['verification']['status']=='supported' and len(result['citations'])==1
    assert result['citations'][0]['quote']==bundle.evidence.quote
    assert result['generated_cypher'].startswith('MATCH ') and result['execution'].startswith('Authoritative')
    assert 'all(r IN relationships(p)' in result['generated_cypher'] and result['cypher_parameters']['public_cutoff'] is None
    with TestClient(create_app(settings)) as client:
        response=client.post('/v1/research/ask',json={'question':'Show NVDA relationships with evidence','max_hops':2})
        assert response.status_code==200 and response.json()['verification']['citation_count']==1


def test_historical_knowledge_query_is_relational_only(tmp_path):
    _,store,_=research_setup(tmp_path)
    result=ResearchService(store).ask(ResearchRequest(question="Show NVDA relationships with evidence",knowledge_cutoff="2026-01-01T00:00:00Z"))
    assert result["generated_cypher"] is None and result["cypher_parameters"] is None
    assert "relational-authority-only" in result["execution"]


def test_written_dates_exact_hops_and_unsupported_intent_are_explicit(tmp_path):
    _,store,_=research_setup(tmp_path)
    dated=ResearchService(store).ask(ResearchRequest(question="What NVDA relationships were public by March 1, 2025?"))
    assert dated["query_plan"]["public_cutoff"].startswith("2025-03-01T23:59:59.999999")
    assert dated["query_plan"]["date_parse"]["basis"]=="inclusive_written_public_date"
    second=ResearchService(store).ask(ResearchRequest(question="Which companies have second-order exposure to NVDA?"))
    assert second["query_plan"]["min_hops"]==2 and second["query_plan"]["max_hops"]==2
    abstained=ResearchService(store).ask(ResearchRequest(question="What was NVDA's stock price market reaction?"))
    assert abstained["verification"]["status"]=="unsupported_intent" and abstained["paths"]==[]
    materiality=ResearchService(store).ask(ResearchRequest(question="Which relationships prove that NVDA has financially material exposure?"))
    assert materiality["verification"]["status"]=="unsupported_intent" and materiality["paths"]==[]


def test_research_rejects_unresolved_questions_and_mutating_cypher(tmp_path):
    _,store,_=research_setup(tmp_path)
    with pytest.raises(ValueError,match='registered company'):ResearchService(store).ask(ResearchRequest(question='What is connected here?'))
    with pytest.raises(ValueError,match='read-only'):validate_readonly_cypher('MATCH (n)-[:BUSINESS_RELATION*1..3]-(m) DELETE n RETURN m LIMIT $limit')
    with pytest.raises(ValueError,match='bounded business'):validate_readonly_cypher('MATCH (n)-[*1..3]-(m) RETURN m LIMIT $limit')
    with pytest.raises(ValueError,match='result limit'):validate_readonly_cypher('MATCH (n)-[:BUSINESS_RELATION*1..3]-(m) RETURN m')


def test_intent_planner_enumerates_incoming_manufacturing_and_ontology(tmp_path):
    _,store,bundle=research_setup(tmp_path)
    manufacturer=next(entity for entity in bundle.entities if entity.id==bundle.claim.object_id)
    result=ResearchService(store).ask(ResearchRequest(question=f"Which companies are manufactured by {manufacturer.canonical_name}?"))
    assert result["intent"]=="incoming_manufacturing" and result["verification"]["finding_count"]==1
    assert result["findings"][0]["company_id"]==str(bundle.claim.subject_id) and result["citations"][0]["quote"]==bundle.evidence.quote
    named=ResearchService(store).ask(ResearchRequest(question="Which named companies does NVIDIA explicitly use for manufacturing?"))
    assert named["intent"]=="named_manufacturing_counterparties" and named["verification"]["finding_count"]==1
    assert named["findings"][0]["predicate"]=="CONTRACTS_MANUFACTURING_TO"
    ontology=ResearchService(store).ask(ResearchRequest(question="Which ontology schema version is active?"))
    assert ontology["intent"]=="ontology_inspection" and ontology["ontology_versions"][-1]["version"]=="finance-v2"


def test_shared_manufacturer_requires_two_supported_edges_and_avoids_direct_relation(tmp_path):
    _,store,bundle=research_setup(tmp_path)
    second=Entity(id=uuid4(),kind="Company",canonical_name="AMD",slug="amd")
    data=copy.deepcopy(bundle.model_dump(mode="json"));data["entities"].append(second.model_dump(mode="json"))
    data["document"]["id"]=str(uuid4());data["document"]["issuer_id"]=str(second.id);data["document"]["accession"]="shared-manufacturer-test"
    data["text_version"]["id"]=str(uuid4());data["text_version"]["document_id"]=data["document"]["id"]
    data["passage"]["id"]=str(uuid4());data["passage"]["text_version_id"]=data["text_version"]["id"]
    data["claim"]["id"]=str(uuid4());data["claim"]["claim_id"]=str(uuid4());data["claim"]["subject_id"]=str(second.id)
    data["evidence"]["id"]=str(uuid4());data["evidence"]["claim_revision_id"]=data["claim"]["id"];data["evidence"]["passage_id"]=data["passage"]["id"]
    with store.connect() as conn:store.persist_reviewed(conn,ReviewedBundle.model_validate(data))
    result=ResearchService(store).ask(ResearchRequest(question="Do NVIDIA and AMD have a shared manufacturer?"))
    assert result["intent"]=="shared_manufacturer" and result["verification"]["status"]=="supported"
    assert len(result["findings"])==1 and len(result["findings"][0]["relationship_ids"])==2
    assert "does not establish a direct relationship" in result["limitations"]
    plan=ResearchService(store).plan(ResearchRequest(question="Which development-corpus company and NVIDIA share a documented manufacturer or supplier?"),[bundle.entities[0].model_dump(mode='json')])
    assert plan["intent"]=="shared_counterparty_network" and plan["min_hops"]==2 and plan["max_hops"]==2
