from copy import deepcopy
import json
from pathlib import Path
import pytest
from fig.followup_schema import capacity_approval, evaluate_quote, validate_review
from fig.ontology_runtime import RuntimeOntology
from fig.generic_extraction import payload

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'evaluation/followup/schema-development-v1'


def test_draft_adds_capacity_right_without_changing_active_catalog():
    parent=json.loads((DATA/'review-package/baseline-catalog.json').read_text())
    draft=json.loads((DATA/'draft-capacity-ontology.json').read_text())
    old=RuntimeOntology(parent['version'],parent['schema_hash'],parent['definitions'])
    new=RuntimeOntology(draft['version'],draft['schema_hash'],draft['definitions'])
    assert old.relationship_errors('Company','HAS_CAPACITY_ENTITLEMENT_IN','Company')
    assert not new.relationship_errors('Company','HAS_CAPACITY_ENTITLEMENT_IN','Company')
    assert new.relationship_errors('Company','HAS_CAPACITY_ENTITLEMENT_IN','Geography')
    assert draft['status']=='proposed_not_approved'
    assert parent['definitions']['entities']==draft['definitions']['entities']


def test_source_only_schema_payload_includes_proposal_but_not_reviews():
    draft=json.loads((DATA/'draft-capacity-ontology.json').read_text())
    evidence=json.loads((DATA/'selected-development-evidence.json').read_text())[0]
    source={'id':evidence['passage_id'],'issuer_name':evidence['issuer'],'text':evidence['text'],'text_hash':evidence['text_hash']}
    sem=json.loads((DATA/'draft-capacity-semantics.json').read_text())
    req=payload(source,{'snapshot':draft},sem)
    assert 'HAS_CAPACITY_ENTITLEMENT_IN' in req['text']['format']['schema']['properties']['edges']['items']['properties']['predicate']['enum']
    assert 'reviewer' not in req['input'][1]['content']
    assert 'present entitlement' in req['input'][0]['content']


def test_blank_review_cannot_approve_candidate():
    candidates=json.loads((DATA/'schema-candidates.json').read_text())['candidates']
    rows=json.loads((DATA/'review-package/review-responses.json').read_text())
    with pytest.raises(ValueError):validate_review(rows,{},candidates)


def test_quote_variants_are_structural_not_entailment_judgments():
    text='NXP is entitled to 10% of the capacity.'
    spans=[{'start':0,'end':len(text),'text':text}]
    assert evaluate_quote(text,text,spans)=={'structurally_valid':True,'accepted_span_match':True,'entailment':'not_assessed'}
    assert not evaluate_quote(text,'is entitled',spans)['accepted_span_match']
    assert not evaluate_quote(text,'NXP owns the capacity.',spans)['structurally_valid']


def test_followup_provider_refuses_unapproved_schema_before_key_access(tmp_path):
    from fig.followup_extraction import FollowupOpenAIProvider
    from fig.generic_extraction import ProviderFailure
    with pytest.raises(ProviderFailure,match='schema_review_not_approved'):
        FollowupOpenAIProvider(tmp_path,{},approval={'status':'proposed_not_approved'},baseline_hash='a',child_hash='b')


def test_followup_provider_uses_declared_ceiling_with_mock_transport(tmp_path):
    import httpx
    from fig.followup_extraction import FollowupOpenAIProvider
    sem=json.loads((DATA/'draft-capacity-semantics.json').read_text())
    draft=json.loads((DATA/'draft-capacity-ontology.json').read_text())
    e=json.loads((DATA/'selected-development-evidence.json').read_text())[0]
    source={'id':e['passage_id'],'issuer_name':e['issuer'],'text':e['text'],'text_hash':e['text_hash']}
    def handle(request):
        assert json.loads(request.content)['max_output_tokens']==8000
        return httpx.Response(200,json={'status':'completed','id':'synthetic-test-response','usage':{'input_tokens':10,'output_tokens':5},
                                      'output':[{'type':'message','content':[{'type':'output_text','text':'{"edges":[]}'}]}]})
    # Synthetic approval solely for exercising the transport contract.
    approval={'status':'eligible_for_schema_freeze','predicate':'HAS_CAPACITY_ENTITLEMENT_IN','definition':sem['predicates']['HAS_CAPACITY_ENTITLEMENT_IN']['definition']}
    provider=FollowupOpenAIProvider(tmp_path,sem,approval=approval,baseline_hash=draft['parent_schema_hash'],child_hash=draft['schema_hash'],
                                   key='synthetic-test-key',transport=httpx.MockTransport(handle))
    edges,meta=provider(source,'approved_child',{'snapshot':draft})
    assert edges==[] and provider.ledger()['requests']==1
