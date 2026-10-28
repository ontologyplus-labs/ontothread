from copy import deepcopy
import pytest
from fig.licensing_review import validate,gate,ROLES,request
ROWS=[{'passage_id':str(i),'issuer':'Issuer','accession':str(i),'text':text,'text_hash':'hash'} for i,text in enumerate(['We obtained technology rights under a license from ARM.','We obtained technology rights under a license from ARM.','We may seek a license from ARM.','License agreement with ARM'])]
def result():
    return {'decision':'approve','assessments':{r['passage_id']:{'verdict':'supported' if i<2 else 'unsupported','edges':[{'licensee':'Issuer','licensor':'ARM','validity_note':'as disclosed'}] if i<2 else [],'rationale':'source judgment'} for i,r in enumerate(ROWS)}}
def test_whole_passage_evidence_cannot_be_model_authored():
    facts=validate(result(),ROWS)
    assert facts[0]['quote']==ROWS[0]['text']
    altered=result();altered['assessments']['0']['edges'][0]['licensor']='Arm Holdings plc'
    with pytest.raises(ValueError,match='absent'):validate(altered,ROWS)
def test_unsupported_rows_cannot_smuggle_edges():
    r=result();r['assessments']['2']['edges']=r['assessments']['0']['edges']
    with pytest.raises(ValueError,match='verdict'):validate(r,ROWS)
def test_gate_requires_recurrence_agreement_and_approval():
    results={role:result() for role in ROLES}
    assert gate(results,ROWS)['status']=='eligible_for_isolated_schema_freeze'
    altered=deepcopy(results);altered['counterexample_check']['decision']='defer'
    assert gate(altered,ROWS)['status']=='deferred'
    rows=deepcopy(ROWS);rows[1]['accession']=rows[0]['accession']
    assert gate(results,rows)['status']=='deferred'
    altered=deepcopy(results);altered['counterexample_check']['assessments']['0']['edges'][0]['licensee']='ARM'
    with pytest.raises(ValueError,match='self licensing'):gate(altered,ROWS)
    altered=deepcopy(results);altered['counterexample_check']['assessments']['1']={'verdict':'unsupported','edges':[],'rationale':'disagreement'}
    assert gate(altered,ROWS)['status']=='deferred'
def test_review_does_not_receive_expected_outcomes():
    r=request(ROWS,{}, {}, 'semantic_fit')
    assert 'verdict' not in r['input'][1]['content']
    assert set(r['text']['format']['schema']['properties']['assessments']['required'])=={'0','1','2','3'}
