import json
from pathlib import Path
import httpx
import pytest
import yaml
from fig.automated_schema_review import review_request,validate_review_result,automated_capacity_gate
from fig.bounded_responses import BoundedResponses
from fig.generic_extraction import ProviderFailure

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'evaluation/followup/schema-development-v1'


def inputs():
    return (json.loads((DIR/'schema-candidates.json').read_text())['candidates'][0],
            json.loads((DIR/'selected-development-evidence.json').read_text()),
            json.loads((DIR/'review-package/baseline-catalog.json').read_text()),
            yaml.safe_load((ROOT/'ontology/semantics-v1.yaml').read_text()))


def test_requests_blind_previous_recommendations_and_other_passes():
    c,e,b,s=inputs();r=review_request(c,e,b,s,'semantic_fit');data=json.loads(r['input'][1]['content'])
    assert set(data['proposed_change'])=={'id','title','type','definition','direction','review_question'}
    assert set(data)=={'proposed_change','existing_catalog','existing_semantics','passages'}
    assert len(data['passages'])==4


def test_invalid_model_quote_cannot_satisfy_review_gate():
    c,e,_,_=inputs()
    ids=c['supporting_passages']+c['boundary_passages']
    result={'candidate_id':c['id'],'examples':[{'passage_id':i,'verdict':'unsupported','quote':'invented quote'} for i in ids]}
    with pytest.raises(ValueError,match='quotation'):validate_review_result(result,c,e)


def test_separate_roles_are_required():
    c,e,_,_=inputs()
    assert automated_capacity_gate({},c,e)['status']=='deferred'


def test_ledger_resume_counts_cost_once_and_reuses_cached_response(tmp_path):
    def transport(r):
        return httpx.Response(200,json={'status':'completed','id':'synthetic-test-response','usage':{'input_tokens':100,'output_tokens':20},
                  'output':[{'type':'message','content':[{'type':'output_text','text':'{"test":true}'}]}]})
    request={'model':'gpt-5.4-mini-2026-03-17','max_output_tokens':4000}
    client=BoundedResponses(tmp_path,key='synthetic-test-key',transport=httpx.MockTransport(transport))
    assert client.call(request)=={'test':True}
    resumed=BoundedResponses(tmp_path,key='synthetic-test-key',transport=httpx.MockTransport(lambda r:pytest.fail('unexpected paid request')))
    assert resumed.call(request)=={'test':True}
    assert resumed.state['requests']==1 and resumed.state['known_cost_usd']>0


def test_low_budget_prevents_request(tmp_path):
    client=BoundedResponses(tmp_path,budget_usd=.0001,key='synthetic-test-key',transport=httpx.MockTransport(lambda r:pytest.fail('request escaped budget')))
    with pytest.raises(ProviderFailure,match='spend_limit'):
        client.call({'model':'gpt-5.4-mini-2026-03-17','max_output_tokens':4000})


def test_keyed_schema_requires_every_evidence_assessment():
    from fig.automated_schema_review_v2 import review_request
    c,e,b,s=inputs();request=review_request(c,e,b,s,'semantic_fit')
    examples=request['text']['format']['schema']['properties']['examples']
    assert examples['type']=='object'
    assert set(examples['required'])==set(c['supporting_passages']+c['boundary_passages'])
    for pid,entry in examples['properties'].items():assert entry['properties']['passage_id']['enum']==[pid]
