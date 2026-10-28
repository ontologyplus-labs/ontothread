"""Actual PostgreSQL/Neo4j behavior in isolated schemas and generated graph IDs."""
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest
from neo4j import GraphDatabase
from psycopg import sql
from fig.config import Settings
from fig.contracts import NeighborRequest,ReviewedBundle,OntologyProposalCreate,OntologyProposalDecision
from fig.fixture import fixture
from fig.ingestion import build_source
from fig.sec import Download
from fig.extraction import ReviewQueue,ExtractRequest,Decision,ReviewConflict
from fig.store import Store
from fig.projection import project_pending

pytestmark=pytest.mark.integration

class IsolatedStore(Store):
    def __init__(self,url,schema):super().__init__(url);self.schema=schema
    @contextmanager
    def connect(self):
        with super().connect() as conn:
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
            yield conn

@pytest.fixture
def database(tmp_path):
    url=os.getenv('FIG_TEST_DATABASE_URL');uri=os.getenv('FIG_TEST_NEO4J_URI');password=os.getenv('FIG_TEST_NEO4J_PASSWORD')
    if not all((url,uri,password)):pytest.skip('Dedicated PostgreSQL and Neo4j test settings required')
    base=Store(url);schema='fig_test_'+uuid4().hex
    with base.connect() as conn:conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    store=IsolatedStore(url,schema);store.migrate()
    yield store,uri,password,tmp_path
    with base.connect() as conn:conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

@pytest.fixture
def unique_bundle():
    bundle,original=fixture();data=bundle.model_dump(mode='json');ids={}
    for record in [*data['entities'],data['document'],data['text_version'],data['passage'],data['claim'],data['evidence']]:ids[record['id']]=str(uuid4())
    ids[data['claim']['claim_id']]=str(uuid4())
    def replace(value):
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        if isinstance(value,list):return [replace(v) for v in value]
        return ids.get(value,value) if isinstance(value,str) else value
    return ReviewedBundle.model_validate(replace(data)),original

def graph_count(uri,password,claim_id):
    with GraphDatabase.driver(uri,auth=('neo4j',password)) as driver:
        with driver.session() as session:return session.run('MATCH ()-[r:BUSINESS_RELATION {claim_revision_id:$id}]->() RETURN count(r) AS n',id=str(claim_id)).single()['n']

def cleanup_graph(uri,password,bundle):
    ids=[str(x.id) for x in [*bundle.entities,bundle.claim,bundle.passage,bundle.document]]
    with GraphDatabase.driver(uri,auth=('neo4j',password)) as driver:
        with driver.session() as session:session.run('MATCH (n) WHERE n.id IN $ids DETACH DELETE n',ids=ids).consume()

def test_live_projection_replay_after_graph_commit_before_ack(database,unique_bundle,monkeypatch):
    store,uri,password,archive=database;bundle,original=unique_bundle;store.ingest(bundle,original,archive)
    execute=store.execute
    def fail_ack(conn,query,args=()):
        if query.startswith('UPDATE projection_outbox'):raise RuntimeError('Injected acknowledgment failure')
        return execute(conn,query,args)
    monkeypatch.setattr(store,'execute',fail_ack)
    try:
        with pytest.raises(RuntimeError,match='acknowledgment'):project_pending(store,uri,'neo4j',password)
        assert store.health()['pending_projection_events']==1
        assert graph_count(uri,password,bundle.claim.id)==1
        monkeypatch.setattr(store,'execute',execute)
        assert project_pending(store,uri,'neo4j',password)==1
        assert project_pending(store,uri,'neo4j',password)==0
        assert graph_count(uri,password,bundle.claim.id)==1
    finally:cleanup_graph(uri,password,bundle)

def test_postgres_migration_unicode_literal_search_temporal_api(database,unique_bundle):
    from fastapi.testclient import TestClient
    from fig.api import create_app
    import fig.api as api
    from unittest.mock import patch
    store,uri,password,archive=database;bundle,original=unique_bundle
    data=bundle.model_dump(mode='json');text='🚀\n'+data['text_version']['normalized_text']
    data['text_version']['normalized_text']=text;data['text_version']['normalized_hash']=sha256(text.encode()).hexdigest()
    for record in ['passage','evidence']:data[record]['start_offset']+=2;data[record]['end_offset']+=2
    bundle=ReviewedBundle.model_validate(data);store.ingest(bundle,original,archive);store.ingest(bundle,original,archive);store.migrate()
    assert store.passages(bundle.document.id,'manufacturing')['passages'][0]['text']==bundle.evidence.quote
    assert store.passages(bundle.document.id,'%')['passages']==[]
    assert store.health()['migration']=='010'
    assert not store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id,knowledge_cutoff='2025-01-01T00:00:00Z'))['relationships']
    assert not store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id,effective_at='2025-01-03T00:00:00Z'))['relationships']
    with patch.object(api,'Store',return_value=store),TestClient(create_app(Settings(store.url,archive))) as client:
        assert client.get('/v1/health').json()['storage_mode']=='postgresql'
        assert len(client.post('/v1/graph/neighbors',json={'entity_id':str(bundle.claim.subject_id)}).json()['relationships'])==1

def test_postgres_ontology_version_acceptance(database,unique_bundle):
    store,uri,password,archive=database;bundle,original=unique_bundle
    store.ingest(bundle,original,archive)
    proposal=OntologyProposalCreate(
        change_type='add_qualifier',concept_name='CAPACITY_SCOPE',
        definition='Identifies the capacity category explicitly scoped by a documented relationship.',
        rationale='Repeated source passages need a controlled field that preserves capacity scope.',
        proposed_schema={'type':'string','required':False},
        evidence_passage_ids=[bundle.passage.id],recurrence_count=3,
        base_ontology_version='finance-v2',proposer='integration-test')
    created=store.create_ontology_proposal(proposal)
    result=store.decide_ontology_proposal(created['id'],OntologyProposalDecision(
        action='accept',expected_version=1,reviewer='integration-test',
        notes='Reviewed for PostgreSQL transaction and JSON persistence behavior.',
        migration_notes='Add an optional capacity scope qualifier; no claim rewrite required.'))
    assert result['migration']['to_version']=='finance-v3'
    assert store.ontology_versions()['versions'][-1]['definitions']['qualifiers']['CAPACITY_SCOPE']['type']=='string'

QUOTE='We utilize foundries, such as Integration Foundry Limited, to produce our semiconductor wafers.'
def source(store,archive):
    html=('<html><body><p>Unicode 🚀. '+QUOTE+'</p></body></html>').encode()
    meta={'cik':'1045810','issuer_name':'Integration Issuer','accessionNumber':'0001045810-25-000001','primaryDocument':'report.htm','form':'10-K','filingDate':'2025-01-01','source_url':'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000001/report.htm'}
    bundle=build_source(meta,Download(html,datetime(2025,1,3,tzinfo=timezone.utc),meta['source_url']));store.ingest_source(bundle,html,archive)
    queue=ReviewQueue(store,archive);passage=store.passages(bundle.document.id,'foundries')['passages'][0]
    queue.extract(ExtractRequest(passage_ids=[passage['id']]))
    return bundle,queue,queue.list(bundle.document.id)['candidates'][0]

def test_postgres_concurrent_review_one_winner(database):
    store,uri,password,archive=database;bundle,queue,candidate=source(store,archive)
    assert not store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships']
    barrier=Barrier(2)
    def decide(action):
        barrier.wait()
        try:return queue.decide(candidate['id'],Decision(action=action,expected_version=1,reviewer='integration-test',canonical_name='Integration Foundry Limited'))
        except ReviewConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(decide,['accept','reject']))
    assert results.count('conflict')==1
    winner=next(r for r in results if isinstance(r,dict));expected=1 if winner['state']=='accepted' else 0
    assert len(queue.history(candidate['id'])['decisions'])==1
    assert store.health()['pending_projection_events']==expected
    assert len(store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships'])==expected

def test_postgres_review_rollback_after_persistence(database,monkeypatch):
    store,uri,password,archive=database;bundle,queue,candidate=source(store,archive);persist=store.persist_reviewed
    def fail(conn,bundle):persist(conn,bundle);raise RuntimeError('Injected persistence failure')
    monkeypatch.setattr(store,'persist_reviewed',fail)
    with pytest.raises(RuntimeError):queue.decide(candidate['id'],Decision(action='accept',expected_version=1,reviewer='integration-test',canonical_name='Integration Foundry Limited'))
    assert queue.list(bundle.document.id)['candidates'][0]['state']=='pending'
    assert queue.history(candidate['id'])['decisions']==[]
    assert len(store.entities()['entities'])==1 and store.health()['pending_projection_events']==0

@pytest.mark.parametrize('field,value',[('review_state','pending'),('polarity','negative'),('assertion_class','inferred')])
def test_postgres_and_graph_keep_ineligible_claims_out_of_traversal(database,unique_bundle,field,value):
    store,uri,password,archive=database;bundle,original=unique_bundle
    data=bundle.model_dump(mode='json');data['claim'][field]=value;bundle=ReviewedBundle.model_validate(data);store.ingest(bundle,original,archive)
    try:
        assert not store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))['relationships']
        project_pending(store,uri,'neo4j',password)
        with GraphDatabase.driver(uri,auth=('neo4j',password)) as driver:
            with driver.session() as session:assert session.run('MATCH ()-[r:BUSINESS_RELATION {claim_revision_id:$id}]->() RETURN r.eligible AS eligible',id=str(bundle.claim.id)).single()['eligible'] is False
    finally:cleanup_graph(uri,password,bundle)
