from fig.licensing_policy_guard import excluded_agreement_title,guard_references,GuardedLicensingExtractor
from test_anchored_extraction import adapter,source,edge

def test_title_without_grant_is_excluded_but_asserted_grant_is_not():
    assert excluded_agreement_title('Semiconductor Patent License Agreement, dated December 9, 2013, between A and B.')
    assert excluded_agreement_title('Amendment to Semiconductor Patent License Agreement, dated December 30, 2013, by and between A and B.')
    assert not excluded_agreement_title('We licensed technology from ARM under a patent agreement.')
    assert not excluded_agreement_title('Patent License Agreement, dated 2013: A granted a patent license to B.')

def test_reference_rule_preserves_original_and_records_change():
    refs={'r':{'assessments':{'p':{'verdict':'supported','edges':[{'licensee':'B','licensor':'A'}]}}}}
    corrected,changes=guard_references(refs,[{'passage_id':'p','text':'Patent License Agreement, dated 2013, between A and B.'}])
    assert refs['r']['assessments']['p']['verdict']=='supported'
    assert corrected['r']['assessments']['p']['verdict']=='unsupported' and len(changes)==1

def test_title_guard_rejects_anchored_relation_without_approving_others():
    from hashlib import sha256
    a=adapter();guard=GuardedLicensingExtractor(a.provider,snapshots=a.snapshots,semantic_catalog=a.semantic_catalog)
    s=source();s['text']='Patent License Agreement, dated 2013, between Tower and ARM.';s['text_hash']=sha256(s['text'].encode()).hexdigest()
    e=edge();e['quote']=s['text']
    result=guard.process(s,'licensing',{'edges':[e]})
    assert not result['anchored_edges'] and result['raw_edges']==[e]
    assert result['rejected_edges'][0]['reason'].startswith('frozen_policy')
