from fig.curated_licensing_metrics import score_cases
from fig.licensing_review import PREDICATE

def e(s='A',o='B'):return {'subject_name':s,'object_name':o,'predicate':PREDICATE}
def result(raw,anchored):return {'raw_edges':raw,'anchored_edges':[{'edge':x,'evidence':{'method':'exact'}} for x in anchored],'rejected_edges':[]}

def test_separates_historical_stress_cases_and_current_disclosures():
    cases=[{'case_id':'P1','passage_id':'p','issuer':'A','temporal_scope':'as_disclosed','expected_edges':[e()]},
           {'case_id':'P2','passage_id':'h','issuer':'A','temporal_scope':'historical_grant','expected_edges':[e()]},
           {'case_id':'N1','passage_id':'n','issuer':'A','temporal_scope':'as_disclosed','expected_edges':[]}]
    outputs={'p':{'baseline':result([],[]),'licensing':result([e()],[e()])},'h':{'baseline':result([],[]),'licensing':result([],[])},'n':{'baseline':result([],[]),'licensing':result([e()],[e()])}}
    report=score_cases(cases,outputs)
    assert report['groups']['as_disclosed']['licensing']['recall_agreement']==1
    assert report['groups']['historical_grant']['licensing']['retained_fn']==1
    assert report['groups']['negative_cases']['licensing']['retained_fp']==1
    assert report['groups']['all']['licensing']['recall_agreement']==.5

def test_unscored_reciprocal_edges_are_not_mislabeled_false_positives():
    case={'case_id':'P','passage_id':'p','issuer':'A','temporal_scope':'as_disclosed','expected_edges':[e()],'unscored_implicit_reciprocal_rights':[e('B','A')]}
    report=score_cases([case],{'p':{'baseline':result([],[]),'licensing':result([e(),e('B','A')],[e()])}})
    row=next(r for r in report['per_case'] if r['condition']=='licensing')
    assert row['raw_tp']==1 and row['raw_fp']==0 and row['unscored_raw_reciprocal_predictions']==1

def test_missing_provider_result_is_a_failure_not_a_negative_prediction():
    case={'case_id':'P','passage_id':'p','issuer':'A','temporal_scope':'as_disclosed','expected_edges':[e()]}
    report=score_cases([case],{'p':{'baseline':result([],[])}})
    assert report['missing_condition_results']==1
    assert report['groups']['all']['licensing']['recall_agreement'] is None
