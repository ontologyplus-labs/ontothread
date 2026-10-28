from hashlib import sha256
from fig.span_licensing_extraction import source_units,licensing_temporal_check,SourceSpanLicensingExtractor,span_request
from test_anchored_extraction import adapter

def source(text):return {'id':'s','issuer_name':'Issuer','text':text,'text_hash':sha256(text.encode()).hexdigest()}
def extractor():
    a=adapter();return SourceSpanLicensingExtractor(None,snapshots=a.snapshots,semantic_catalog=a.semantic_catalog)
def edge(start=0,end=0,state='granted_or_held'):
    return {'subject_name':'Issuer','subject_kind':'Company','predicate':'LICENSES_TECHNOLOGY_FROM','object_name':'ARM','object_kind':'Company','start_unit':start,'end_unit':end,'grant_state':state}

def test_units_preserve_exact_source_and_do_not_split_company_abbreviations():
    text='We licensed from Synopsys, Inc. under an agreement. We also license from ARM.'
    units=source_units(text);assert len(units)==2
    for u in units:assert text[u['start']:u['end']]==u['text']

def test_no_generated_quote_field_and_range_copies_full_list():
    s=source('We license technology from ARM, Cadence and Synopsys. It is included in our products.')
    req=span_request(s,{'snapshot':extractor().snapshots['licensing']},{'predicates':{}})
    assert 'quote' not in req['text']['format']['schema']['properties']['edges']['items']['properties']
    result=extractor().process_spans(s,'licensing',{'edges':[edge()]})
    assert result['anchored_edges'][0]['edge']['quote']==source_units(s['text'])[0]['text']
    assert result['anchored_edges'][0]['evidence']['method']=='source_unit_range'

def test_future_grant_cannot_pass_by_claiming_completed_state():
    s=source('We will be granted a license to ARM technology.')
    result=extractor().process_spans(s,'licensing',{'edges':[edge()]})
    assert not result['anchored_edges'] and result['rejected_edges'][0]['reason']=='future_or_conditional_grant_cue'

def test_conditional_sublicense_and_unknown_model_state_are_deferred():
    assert not licensing_temporal_check('TPSCo may, in certain circumstances, sub-license such technology to Tower.','granted_or_held')['eligible']
    assert not licensing_temporal_check('We license technology from ARM.','uncertain')['eligible']

def test_future_production_does_not_cancel_existing_license_and_historical_is_preserved():
    assert licensing_temporal_check('Panasonic granted TPSCo a license. Production will begin next year.','historical_grant')['eligible']
    assert licensing_temporal_check('Panasonic granted TPSCo a license.','historical_grant')['ongoing_validity']=='not_inferred'

def test_mixed_grants_require_narrower_source_selection():
    s=source('We license technology from ARM. We may receive a license from ARM next year.')
    mixed=extractor().process_spans(s,'licensing',{'edges':[edge(end=1)]});narrow=extractor().process_spans(s,'licensing',{'edges':[edge()]})
    assert not mixed['anchored_edges'] and narrow['anchored_edges']

def test_invalid_ranges_are_rejected_and_ablation_does_not_change_raw_selection():
    s=source('We will be granted a license from ARM.')
    raw={'edges':[edge(),edge(end=90)]}
    checked=extractor().process_spans(s,'licensing',raw);ablation=extractor().process_spans(s,'licensing',raw,temporal_guard=False)
    assert checked['raw_span_edges']==ablation['raw_span_edges']==raw['edges']
    assert len(checked['span_rejections'])==1 and len(ablation['anchored_edges'])==1 and not checked['anchored_edges']


def test_permission_to_sublicense_is_not_a_completed_grant():
    assert not licensing_temporal_check('TPSCo is allowed to sublicense the licenses granted to Tower.','granted_or_held')['eligible']

def test_unknown_state_is_a_malformed_response():
    import pytest
    from fig.generic_extraction import ProviderFailure
    with pytest.raises(ProviderFailure,match='invalid_grant_state'):
        extractor().process_spans(source('We license from ARM.'),'licensing',{'edges':[edge(state='made_up')]})
