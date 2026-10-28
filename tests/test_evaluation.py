from pathlib import Path
from hashlib import sha256
import json

import httpx
import pytest
from pydantic import ValidationError
from fig.evaluation import Dataset,score_case,evaluate,write_report
from fig.extraction import Output,Proposal,OpenAIExtractor,ExtractionError

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def dataset():return Dataset.model_validate_json((ROOT/'evaluation/nvidia-pilot.json').read_text())

def test_multi_issuer_heldout_dataset_contract():
    heldout=Dataset.model_validate_json((ROOT/'evaluation/multi-issuer-heldout-v1.json').read_text())
    assert len(heldout.cases)==13
    assert sum(len(case.expected) for case in heldout.cases)==12
    assert {case.issuer_name for case in heldout.cases}=={'ADVANCED MICRO DEVICES INC','Broadcom Inc.','ASML HOLDING NV','TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD'}

def test_curated_source_labels_and_rule_baseline(dataset,tmp_path):
    assert len(dataset.cases)==16 and sum(len(c.expected) for c in dataset.cases)==8
    result=evaluate(dataset,'rules',tmp_path)
    assert result['completed_cases']==16
    assert result['metrics']['tp']==2 and result['metrics']['fn']==6 and result['metrics']['fp']==0
    assert result['metrics']['recall']==0.25 and result['metrics']['precision']==1
    assert result['metrics']['negative_case_accuracy']==1
    cached=evaluate(dataset,'rules',tmp_path)
    assert all(r['cached'] for r in cached['results'])

def test_gold_quote_and_text_integrity_cannot_be_silently_changed(dataset):
    data=dataset.model_dump(mode='json');data['cases'][0]['text']='fabricated'
    with pytest.raises(ValidationError):Dataset.model_validate(data)
    data=dataset.model_dump(mode='json');data['cases'][0]['expected'][0]['supporting_quote']='fabricated'
    with pytest.raises(ValidationError):Dataset.model_validate(data)

def test_wrong_direction_identity_duplicate_and_evidence_scoring(dataset):
    case=dataset.cases[1];gold=case.expected[0]
    def proposal(name=gold.counterparty_name,direction=gold.subject_is_issuer,quote=gold.supporting_quote):
        return Proposal(counterparty_name=name,subject_is_issuer=direction,predicate=gold.predicate,quote=quote,rationale='test')
    wrong=score_case(case,Output(candidates=[proposal(direction=True)]))
    assert wrong['tp']==0 and wrong['wrong_direction']==1
    duplicate=score_case(case,Output(candidates=[proposal(),proposal()]))
    assert duplicate['tp']==1 and duplicate['fp']==1 and duplicate['duplicate_predictions']==1
    short=score_case(case,Output(candidates=[proposal(quote=gold.counterparty_name)]))
    assert short['tp']==1 and short['supported_tp']==0
    wrong_name=score_case(case,Output(candidates=[proposal(name='Invented company')]))
    assert wrong_name['identity_errors']==1 and wrong_name['invalid_quotes']==1

def test_scoring_treats_trailing_explicit_abbreviation_as_same_endpoint(dataset):
    case=dataset.cases[1];gold=case.expected[0]
    abbreviated=gold.model_copy(update={'counterparty_name':gold.counterparty_name+' (ACME)'})
    case=case.model_copy(update={'expected':[abbreviated]})
    output=Output(candidates=[Proposal(counterparty_name=gold.counterparty_name,subject_is_issuer=gold.subject_is_issuer,
        predicate=gold.predicate,quote=gold.supporting_quote,rationale='test')])
    assert score_case(case,output)['tp']==1

def test_labels_do_not_leak_into_provider_input(dataset,tmp_path):
    class Recorded:
        model='recorded-test'
        def extract(self,passage,issuer):
            assert list(passage)==['text']
            assert 'expected' not in passage
            return Output(candidates=[]),{}
    result=evaluate(dataset,'openai',tmp_path,extractor=Recorded(),limit=1)
    assert result['metrics']['fn']==2

def test_evaluation_scores_only_deterministically_validated_candidates(dataset,tmp_path):
    negative=dataset.model_copy(update={'cases':[dataset.cases[3]]})
    class Recorded:
        model='recorded-validation-test'
        def extract(self,passage,issuer):
            return Output(candidates=[Proposal(
                counterparty_name='foundries',subject_is_issuer=True,
                predicate='CONTRACTS_MANUFACTURING_TO',
                quote='We depend on foundries to manufacture our semiconductor wafers using their fabrication equipment and techniques.',
                rationale='Recorded unsafe model proposal.')]),{}
    result=evaluate(negative,'openai',tmp_path,extractor=Recorded())
    assert result['raw_candidate_count']==1
    assert result['admissible_candidate_count']==0
    assert result['validation_rejection_count']==1
    assert result['metrics']['fp']==0 and result['metrics']['negative_case_accuracy']==1
    assert result['results'][0]['raw_output']['candidates']
    assert result['results'][0]['output']['candidates']==[]

def test_provider_failure_is_not_an_empty_success_or_fabricated_accuracy(dataset,tmp_path):
    class Failed:
        model='failed-test'
        calls=0
        def extract(self,*args):
            self.calls+=1
            raise ExtractionError('Credits unavailable',code='credit_balance_exhausted',status=429)
    provider=Failed();report=evaluate(dataset,'openai',tmp_path/'cache',extractor=provider)
    assert provider.calls==1 and report['status']=='failed'
    assert report['coverage']==0 and report['metrics'] is None and report['results']==[]
    assert not list((tmp_path/'cache').glob('*.json'))
    write_report(report,tmp_path/'report.json')
    assert 'No model-quality metrics' in (tmp_path/'report.md').read_text()

def test_safe_specific_quota_error_does_not_expose_provider_body(dataset):
    transport=httpx.MockTransport(lambda _:httpx.Response(429,json={'error':{'code':'credit_balance_exhausted','message':'sensitive-provider-body'}}))
    provider=OpenAIExtractor(key='test-key',model='test-model',transport=transport)
    from types import SimpleNamespace
    with pytest.raises(ExtractionError) as caught:provider.extract({'text':dataset.cases[0].text},SimpleNamespace(canonical_name='NVIDIA CORP'))
    assert caught.value.code=='credit_balance_exhausted' and caught.value.status==429
    assert 'sensitive-provider-body' not in str(caught.value)
