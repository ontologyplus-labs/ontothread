import json
from datetime import datetime,timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from fig.api import create_app
from fig.config import Settings
from fig.contracts import NeighborRequest,Entity
from fig.ingestion import build_source
from fig.sec import Download
from fig.store import Store
from fig.extraction import ReviewQueue,ExtractRequest,Decision,Proposal,Output,OpenAIExtractor,ExtractionError,ReviewConflict,proposal_errors
from fig.review import ReviewInput,import_review

QUOTE='We utilize foundries, such as Alpha Company Limited, or Alpha, and Beta Electronics Co., Ltd., or Beta, to produce our semiconductor wafers.'
HTML=('<html><body><h2>Business</h2><p>Unicode 🚀. '+QUOTE+'</p></body></html>').encode()
META={'cik':'1045810','issuer_name':'Test Issuer','accessionNumber':'0001045810-25-000001','primaryDocument':'report.htm','form':'10-K','filingDate':'2025-01-01','source_url':'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000001/report.htm'}

@pytest.fixture
def setup(tmp_path):
    settings=Settings('sqlite:///'+str(tmp_path/'db.sqlite3'),tmp_path/'archive')
    store=Store(settings.database_url);store.migrate()
    bundle=build_source(META,Download(HTML,datetime(2025,1,3,tzinfo=timezone.utc),META['source_url']))
    store.ingest_source(bundle,HTML,settings.archive_dir)
    passage=store.passages(bundle.document.id,'foundries')['passages'][0]
    return settings,store,bundle,passage,ReviewQueue(store,settings.archive_dir)

def proposals(queue,passage):
    return queue.extract(ExtractRequest(passage_ids=[passage['id']]))

def decision(action='accept',version=1,**kwargs):
    return Decision(action=action,expected_version=version,reviewer='test-reviewer',**kwargs)

def test_pending_and_cached_rules_do_not_create_entities_or_claims(setup):
    settings,store,bundle,passage,queue=setup
    result=proposals(queue,passage);cached=proposals(queue,passage)
    assert not result['runs'][0]['cached'] and cached['runs'][0]['cached']
    assert result['runs'][0]['candidate_ids']==cached['runs'][0]['candidate_ids']
    assert len(queue.list(bundle.document.id)['candidates'])==2
    assert len(store.entities()['entities'])==1
    assert not store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships']
    assert store.health()['pending_projection_events']==0

def test_atomic_accept_evidence_offsets_audit_and_stale_decision(setup):
    settings,store,bundle,passage,queue=setup;proposals(queue,passage)
    candidate=queue.list(bundle.document.id)['candidates'][0]
    result=queue.decide(candidate['id'],decision(canonical_name=candidate['counterparty_name'],notes='Source checked.'))
    assert result['state']=='accepted'
    neighbors=store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships']
    assert len(neighbors)==1 and neighbors[0]['claim']['reviewer']=='test-reviewer'
    evidence=neighbors[0]['evidence'][0]['evidence']
    assert bundle.text_version.normalized_text[evidence['start_offset']:evidence['end_offset']]==QUOTE
    assert store.health()['pending_projection_events']==1
    assert queue.history(candidate['id'])['decisions'][0]['notes']=='Source checked.'
    with pytest.raises(ReviewConflict):queue.decide(candidate['id'],decision(action='reject'))
    assert len(queue.history(candidate['id'])['decisions'])==1

def test_rejection_and_explicit_identity_confirmation(setup):
    settings,store,bundle,passage,queue=setup;proposals(queue,passage)
    candidates=queue.list(bundle.document.id)['candidates']
    with pytest.raises(ValueError,match='Confirm'):queue.decide(candidates[0]['id'],decision())
    queue.decide(candidates[0]['id'],decision(action='reject',notes='Rejected in test.'))
    assert queue.list(bundle.document.id,'rejected')['candidates']
    assert not store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships']
    assert store.health()['pending_projection_events']==0

def test_accept_failure_rolls_back_claim_entity_outbox_and_audit(setup,monkeypatch):
    settings,store,bundle,passage,queue=setup;proposals(queue,passage)
    candidate=queue.list(bundle.document.id)['candidates'][0]
    original=store.persist_reviewed
    def fail(conn,bundle):
        original(conn,bundle)
        raise RuntimeError('Injected transaction failure')
    monkeypatch.setattr(store,'persist_reviewed',fail)
    with pytest.raises(RuntimeError):queue.decide(candidate['id'],decision(canonical_name=candidate['counterparty_name']))
    assert len(store.entities()['entities'])==1 and store.health()['pending_projection_events']==0
    assert queue.list(bundle.document.id)['candidates'][0]['state']=='pending'
    assert queue.history(candidate['id'])['decisions']==[]

def test_known_claim_is_duplicate_and_existing_identity_resolves(setup):
    settings,store,bundle,passage,queue=setup
    entity=Entity(id=uuid4(),canonical_name='Alpha Company Limited',slug='alpha',kind='Company')
    reviewed=import_review(store,settings.archive_dir,ReviewInput(passage_id=passage['id'],counterparty=entity,predicate='CONTRACTS_MANUFACTURING_TO',quote=QUOTE,reviewer='original-reviewer'))
    proposals(queue,passage)
    duplicate=queue.list(bundle.document.id,'duplicate')['candidates'][0]
    assert duplicate['claim_revision_id']==reviewed['claim_revision_id']
    assert not queue.history(duplicate['id'])['decisions']
    other=queue.list(bundle.document.id)['candidates'][0]
    # A reviewer can resolve an extracted name to an existing canonical company;
    # its original immutable claim and reviewer are retained, with a new decision audit.
    queue.decide(other['id'],decision(entity_id=entity.id,notes='Explicit resolution for test.'))
    assert len(store.entities()['entities'])==2
    assert len(store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships'])==1
    assert queue.history(other['id'])['decisions'][0]['resolved_entity_id']==str(entity.id)

def mock_response(output,status='completed'):
    return {'id':'recorded-response','status':status,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(output)}]}],'usage':{'input_tokens':10,'output_tokens':10}}

def test_openai_structured_contract_and_cache_without_live_network(setup):
    settings,store,bundle,passage,queue=setup;calls=[]
    proposal=Proposal(counterparty_name='Alpha Company Limited',subject_is_issuer=True,predicate='CONTRACTS_MANUFACTURING_TO',quote=QUOTE,rationale='Recorded test proposal.')
    def handler(request):
        calls.append(request)
        body=json.loads(request.content)
        assert str(request.url)=='https://api.openai.com/v1/responses'
        assert body['store'] is False and body['text']['format']['strict'] is True
        assert body['text']['format']['schema']['additionalProperties'] is False
        assert body['text']['format']['schema']['$defs']['Proposal']['required']==list(Proposal.model_fields)
        return httpx.Response(200,json=mock_response({'candidates':[proposal.model_dump()]}))
    extractor=OpenAIExtractor(key='test-key',model='test-model',transport=httpx.MockTransport(handler))
    request=ExtractRequest(provider='openai',passage_ids=[passage['id']])
    queue.extract(request,extractor);queue.extract(request,extractor)
    assert len(calls)==1 and len(queue.list(bundle.document.id)['candidates'])==1
    assert not store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))['relationships']

@pytest.mark.parametrize('response',[mock_response({'candidates':[]},'incomplete'),{'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'no'}]}]},mock_response({'candidates':[{'invented':True}]})])
def test_refused_incomplete_invalid_outputs_fail_safely(setup,response):
    settings,store,bundle,passage,queue=setup
    extractor=OpenAIExtractor(key='test-key',model='test-model',transport=httpx.MockTransport(lambda _:httpx.Response(200,json=response)))
    request=ExtractRequest(provider='openai',passage_ids=[passage['id']])
    with pytest.raises(ExtractionError):queue.extract(request,extractor)
    with pytest.raises(ReviewConflict):queue.extract(request,extractor)
    assert not queue.list(bundle.document.id,'all')['candidates']
    with pytest.raises(ExtractionError):queue.extract(request.model_copy(update={'retry_failed':True}),extractor)

def test_invalid_quote_and_anonymous_names_excluded(setup):
    settings,store,bundle,passage,queue=setup
    class Recorded:
        model='test-model'
        def extract(self,*args):
            return Output(candidates=[Proposal(counterparty_name='Alpha Company Limited',subject_is_issuer=True,predicate='OWNS',quote='invented',rationale='test'),Proposal(counterparty_name='unknown supplier',subject_is_issuer=True,predicate='OWNS',quote=QUOTE,rationale='test')]),{}
    result=queue.extract(ExtractRequest(provider='openai',passage_ids=[passage['id']]),Recorded())
    assert len(result['runs'][0]['validation_errors'])==2
    assert not queue.list(bundle.document.id,'all')['candidates']

def test_semantic_validation_rejects_observed_live_failure_modes():
    issuer='NVIDIA CORP'
    def rejected(text,**values):
        proposal=Proposal(rationale='recorded failure',**values)
        assert proposal_errors(proposal,text,issuer)
    generic='We depend on foundries to manufacture our semiconductor wafers.'
    rejected(generic,counterparty_name='foundries',subject_is_issuer=True,
             predicate='CONTRACTS_MANUFACTURING_TO',quote=generic)
    isolated='large cloud services companies such as Amazon and Microsoft;'
    rejected(isolated,counterparty_name='Amazon',subject_is_issuer=True,
             predicate='COMPETES_WITH',quote=isolated)
    proposed='We are finalizing an investment and partnership agreement with OpenAI. There is no assurance that we will enter into an investment and partnership agreement with OpenAI.'
    rejected(proposed,counterparty_name='OpenAI',subject_is_issuer=True,
             predicate='PARTNERS_WITH',quote='We are finalizing an investment and partnership agreement with OpenAI.')
    agreement='Under our agreement with Microsoft for the Xbox, Microsoft may have rights of refusal.'
    rejected(agreement,counterparty_name='Microsoft',subject_is_issuer=True,
             predicate='PARTNERS_WITH',quote=agreement)

def test_semantic_validation_enforces_supplier_direction_and_literal_quotes():
    text='We purchase memory from SK Hynix Inc., Micron Technology, Inc., and Samsung.'
    valid=Proposal(counterparty_name='SK Hynix Inc.',subject_is_issuer=False,
                   predicate='SUPPLIES_TO',quote=text,rationale='Supplier sells memory to issuer.')
    assert proposal_errors(valid,text,'NVIDIA CORP')==[]
    reversed_direction=valid.model_copy(update={'subject_is_issuer':True})
    assert any('reversed' in reason for reason in proposal_errors(reversed_direction,text,'NVIDIA CORP'))
    invented=valid.model_copy(update={'counterparty_name':'Micron Technology, Inc.','quote':'We purchase memory from ... Micron Technology, Inc.'})
    assert any('exact contiguous' in reason for reason in proposal_errors(invented,text,'NVIDIA CORP'))

def test_semantic_validation_accepts_explicit_named_supplier_lists():
    text='The primary foundry suppliers include Taiwan Semiconductor Manufacturing Company (TSMC), Global Foundries and Samsung Electronics.'
    valid=Proposal(counterparty_name='Taiwan Semiconductor Manufacturing Company (TSMC)',subject_is_issuer=False,
                   predicate='SUPPLIES_TO',quote=text,rationale='Explicit named supplier list.')
    assert proposal_errors(valid,text,'QUALCOMM INC/DE')==[]
    reversed_direction=valid.model_copy(update={'subject_is_issuer':True})
    assert any('reversed' in reason for reason in proposal_errors(reversed_direction,text,'QUALCOMM INC/DE'))

def test_api_review_origin_filters_history_and_missing_model(setup,monkeypatch):
    settings,store,bundle,passage,queue=setup
    monkeypatch.delenv('OPENAI_API_KEY',raising=False);monkeypatch.delenv('FIG_LLM_MODEL',raising=False)
    with TestClient(create_app(settings)) as client:
        body={'passage_ids':[passage['id']]}
        assert client.post('/v1/extraction/runs',json=body,headers={'Origin':'https://unrelated.test'}).status_code==403
        assert client.post('/v1/extraction/runs',json={**body,'provider':'openai'}).status_code==422
        assert client.post('/v1/extraction/runs',json=body,headers={'Origin':'http://testserver'}).status_code==200
        assert client.get(f'/v1/documents/{bundle.document.id}/candidates?state=invalid').status_code==422
        candidate=client.get(f'/v1/documents/{bundle.document.id}/candidates').json()['candidates'][0]
        path=f"/v1/candidates/{candidate['id']}/decisions"
        result=client.post(path,json=decision(canonical_name=candidate['counterparty_name']).model_dump(mode='json'))
        assert result.status_code==200
        assert client.post(path,json=decision(action='reject').model_dump(mode='json')).status_code==409
        assert client.get(path).json()['decisions'][0]['reviewer']=='test-reviewer'
        assert 'Candidate review' in client.get('/assets/app.js').text

def test_review_migration_packaged_identically():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert (root/'migrations/003_review.sql').read_bytes()==(root/'src/fig/resources/003_review.sql').read_bytes()
