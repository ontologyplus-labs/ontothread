from fig.evidence_spans import anchor_quote,anchor_edge

def test_case_only_match_preserves_original_and_uses_source_offsets():
    source='We have obtained rights from ARM.';r=anchor_quote(source,'we have obtained rights from ARM.')
    assert r['source_quote']==source and r['raw_quote'].startswith('we')
    assert source[r['start']:r['end']]==r['source_quote']

def test_rejects_fuzzy_or_ambiguous_source_matches():
    assert anchor_quote('We obtained rights. We obtained rights.','we obtained rights.')['status']=='rejected'
    assert anchor_quote('We obtained rights.','We purchased rights.')['status']=='rejected'
    assert anchor_quote('We obtained rights.','We obtained rights…')['status']=='rejected'

def test_unicode_expansion_cannot_anchor_partial_character():
    assert anchor_quote('Straße','STRASSE')['source_quote']=='Straße'
    assert anchor_quote('ß','s')['status']=='rejected'

def test_anchor_requires_endpoints_and_does_not_assert_entailment():
    source={'text':'We obtained rights from ARM.','issuer':'Tower'}
    edge={'quote':'we obtained rights from ARM.','subject_name':'Tower','object_name':'ARM'}
    assert anchor_edge(source,edge)['entailment']=='not_established_by_anchoring'
    edge['object_name']='Arm Holdings'
    assert anchor_edge(source,edge)['status']=='rejected'
