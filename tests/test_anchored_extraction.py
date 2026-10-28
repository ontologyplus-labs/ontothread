from copy import deepcopy
from hashlib import sha256
import pytest
from fig.anchored_extraction import AnchoredExperimentalExtractor
from fig.followup_schema import canonical_schema_hash

class Provider:
    def call(self,request):return {'edges':[]}

def adapter():
    base={'entities':['Company'],'predicates':{'PARTNERS_WITH':{'subject':['Company'],'object':['Company']}}}
    child=deepcopy(base);child['predicates']['LICENSES_TECHNOLOGY_FROM']={'subject':['Company'],'object':['Company']}
    snapshots={name:{'definitions':d,'schema_hash':canonical_schema_hash(d)} for name,d in [('baseline',base),('licensing',child)]}
    return AnchoredExperimentalExtractor(Provider(),snapshots=snapshots,semantic_catalog={'predicates':{}})

def source():
    text='We obtained technology rights from ARM.'
    return {'id':'s','issuer_name':'Tower','text':text,'text_hash':sha256(text.encode()).hexdigest()}

def edge():return {'subject_name':'Tower','subject_kind':'Company','predicate':'LICENSES_TECHNOLOGY_FROM','object_name':'ARM','object_kind':'Company','quote':'we obtained technology rights from ARM.'}

def test_adapter_preserves_raw_output_and_records_exact_offsets_without_accepting_fact():
    raw={'edges':[edge()]};original=deepcopy(raw);s=source();r=adapter().process(s,'licensing',raw)
    item=r['anchored_edges'][0];e=item['evidence']
    assert raw==original and r['raw_edges']==original['edges']
    assert s['text'][e['start']:e['end']]==item['edge']['quote']
    assert e['raw_quote']==original['edges'][0]['quote'] and item['review_state']=='awaiting_semantic_review'
    assert r['production_imports']==0

def test_new_predicate_cannot_escape_into_baseline():
    r=adapter().process(source(),'baseline',{'edges':[edge()]})
    assert not r['anchored_edges'] and r['rejected_edges'][0]['reason']=='predicate_or_endpoint_kind_outside_schema'

def test_rejects_invented_quote_and_source_tampering():
    raw=edge();raw['quote']='We bought ARM.'
    assert adapter().process(source(),'licensing',{'edges':[raw]})['rejected_edges']
    bad=source();bad['text']='changed'
    with pytest.raises(ValueError,match='hash'):adapter().process(bad,'licensing',{'edges':[]})

def test_provider_receives_only_source_text_and_selected_catalog():
    a=adapter();assert a(source(),'baseline')['anchored_edges']==[]
