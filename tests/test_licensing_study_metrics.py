from copy import deepcopy
import importlib.util
from pathlib import Path
from fig.licensing_study_metrics import score,aggregate,paired_bootstrap

def row(case,doc,tp,fp,fn):return {'case_id':case,'accession':doc,'issuer':'Issuer','modality':'as_disclosed','tp':tp,'fp':fp,'fn':fn,'raw_tp':tp,'raw_fp':fp,'raw_fn':fn,'repairs':0,'correct_repairs':0,'incorrect_repairs':0,'deferred_predictions':0,'decision_counts':{}}

def test_deferred_positive_stays_false_negative_and_wrong_repair_is_counted():
    e={'subject_name':'Buyer','predicate':'LICENSES_TECHNOLOGY_FROM','object_name':'Owner'};case={'case_id':'c','accession':'d','issuer':'Buyer','expected_edges':[e]}
    output={'raw_edges':[e],'anchored_edges':[],'semantic_decisions':[{'decision':'defer'}]}
    assert score(case,output)['fn']==1 and score(case,output)['deferred_predictions']==1
    wrong=dict(e,object_name='Other');output['anchored_edges']=[{'edge':wrong}];output['semantic_decisions']=[{'decision':'repair','validated_edge':wrong}]
    assert score(case,output)['incorrect_repairs']==1 and score(case,output)['fp']==1

def test_no_predictions_has_undefined_precision_not_perfect_precision():
    r=aggregate([row('c','d',0,0,1)]);assert r['precision'] is None and r['recall']==0

def test_bootstrap_uses_completed_pairs_and_documents():
    left=[row('a','one',1,1,1),row('b','two',1,0,0),row('failed','missing',0,0,1)];right=[row('a','one',2,0,0),row('b','two',1,0,0)]
    r=paired_bootstrap(left,right,iterations=10000);assert r['paired_cases']==2 and r['document_clusters']==2 and abs(r['effects']['recall_delta']['point']-1/3)<1e-10
    assert r['statistical_claim']=='inconclusive' # Some document resamples contain no improvement.

def scorer():
    path=Path(__file__).parents[1]/'scripts/score_licensing_qa.py';spec=importlib.util.spec_from_file_location('qa_score',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module.score_answer

def test_qa_wrong_citation_is_not_complete():
    expected={'citations':[{'claim_revision_id':'good','passage_id':'p'}],'paths':[]};actual={'citations':[{'claim_revision_id':'bad','passage_id':'p'}],'paths':[]}
    r=scorer()(expected,actual);assert r['false_claims']==1 and r['missed_claims']==1 and not r['answer_complete']

def test_qa_supported_claim_in_negative_case_breaks_abstention():
    actual={'citations':[{'claim_revision_id':'bad','passage_id':'p'}],'paths':[],'findings':[{}]}
    r=scorer()({'status':'unsupported'},actual,unsupported=True);assert r['correct_abstention'] is False and r['false_claims']==1
