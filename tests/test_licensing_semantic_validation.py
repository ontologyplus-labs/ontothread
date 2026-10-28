from copy import deepcopy
from hashlib import sha256
import pytest
from fig.licensing_semantic_validation import validate_licensing,apply_semantics
DEFINITION='Technical intellectual property license. Direction is licensee to licensor.'

def check(text,subject='Buyer',object='Owner',issuer='Buyer',repairs=True):
    edge={'subject_name':subject,'object_name':object,'subject_kind':'Company','object_kind':'Company','predicate':'LICENSES_TECHNOLOGY_FROM','quote':text}
    source={'issuer_name':issuer,'text':text,'text_hash':sha256(text.encode()).hexdigest()}
    item={'edge':edge,'raw_edge':deepcopy(edge),'edge_index':0,'evidence':{'start':0,'end':len(text)}}
    return validate_licensing(source,item,DEFINITION,allow_repairs=repairs)

@pytest.mark.parametrize('text',[
 'Owner granted Buyer a license to process technology.',
 'Owner granted a license to process technology to Buyer.',
 'Buyer was granted a technology license by Owner.',
 'Buyer licenses software from Owner.',
 'We license patents from Owner.',
 'We obtained technical rights under license agreements with Owner.',
])
def test_explicit_roles(text):assert check(text)['decision']=='pass'

def test_repair_only_same_pair_and_keep_original():
    d=check('Owner granted Buyer a license to process technology.','Owner','Buyer')
    assert d['decision']=='repair' and d['validated_edge']['subject_name']=='Buyer' and d['raw_edge']['subject_name']=='Owner'
    assert check('Owner granted Buyer a license to process technology.','Owner','Buyer',repairs=False)['decision']=='reject'

def test_third_party_beneficiary_does_not_replace_licensee():
    assert check('Owner granted Buyer a process technology license; Beneficiary is a third-party beneficiary.','Beneficiary','Owner')['decision']=='defer'

def test_missing_party_not_invented():assert check('Owner granted Stranger a process technology license.')['decision']=='defer'

@pytest.mark.parametrize('text,rule',[
 ('Exhibit 10: Intellectual Property Transfer and License Agreement dated as of March 3, 2020 between Buyer and Owner.','agreement_title_only'),
 ('Buyer uses marks under license from Owner, which owns the registered trademarks.','trademark_only'),
 ('Buyer received an export license from the government to ship technology to Owner.','export_permission'),
 ('Buyer requested a judicial finding that it held a software license from Owner.','disputed_grant'),
 ('Buyer has not obtained a software license from Owner.','negated_grant'),
 ('Buyer will be granted a process technology license by Owner.','nonactual_grant'),
 ('Buyer may receive a software license from Owner.','nonactual_grant'),
])
def test_exclusions(text,rule):
    d=check(text);assert d['decision']=='reject' and d['rule_id']==rule

def test_title_in_factual_grant_and_future_production():
    text='Under the Technology License Agreement dated May 1, Owner granted Buyer a software license. Production will begin next year.'
    assert check(text)['decision']=='pass'

def test_mixed_scope_defers():assert check('Buyer licenses patents and trademarks from Owner.')['decision']=='defer'

def test_competing_directions_defer():assert check('Buyer licenses software from Owner. Owner licenses software from Buyer.')['decision']=='defer'

def test_self_license_reject():assert check('Buyer licenses software from Buyer.','Buyer','Buyer')['decision']=='reject'

def test_cross_license_needs_received_rights_and_no_implicit_reciprocal():
    text='We have entered into patent cross-licenses with Owner. These cross-licenses provide us with freedom of operation under patents owned by such companies.'
    assert check(text)['decision']=='pass'
    assert check('We have entered into patent cross-licenses with Owner.')['decision']=='defer'

def test_output_raw_preserved_and_repaired_quote_source_exact():
    text='Owner granted Buyer a license to process technology.';edge={'subject_name':'Owner','object_name':'Buyer','subject_kind':'Company','object_kind':'Company','predicate':'LICENSES_TECHNOLOGY_FROM','quote':text}
    source={'issuer_name':'Buyer','text':text,'text_hash':sha256(text.encode()).hexdigest()};output={'raw_edges':[edge],'anchored_edges':[{'edge':edge,'raw_edge':deepcopy(edge),'edge_index':0,'evidence':{'start':0,'end':len(text)}}],'rejected_edges':[]}
    original=deepcopy(output);got=apply_semantics(source,output,DEFINITION)
    assert output==original and got['raw_edges']==original['raw_edges']
    assert got['anchored_edges'][0]['edge']['subject_name']=='Buyer'
    d=got['semantic_decisions'][0];assert d['production_acceptance'] is False

def test_technology_in_company_name_is_not_a_technical_scope():
    assert check('Technology Owner granted Buyer a license.','Buyer','Technology Owner')['decision']=='defer'

def test_customer_after_from_clause_is_not_licensor():
    assert check('Buyer licenses software from an unnamed vendor and sells chips to Owner.')['decision']=='defer'
