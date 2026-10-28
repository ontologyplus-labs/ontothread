from copy import deepcopy
from fig.licensing_metrics import summarize
from fig.licensing_review import PREDICATE
ROWS=[{'passage_id':'p','issuer':'A','accession':'d'},{'passage_id':'n','issuer':'B','accession':'e'}]
def refs():
    r={'assessments':{'p':{'verdict':'supported','edges':[{'licensee':'A','licensor':'C'}]},'n':{'verdict':'unsupported','edges':[]}}}
    return {'one':deepcopy(r),'two':deepcopy(r)}
def result(edges):return {'raw_edges':edges,'anchored_edges':[],'rejected_edges':[{'raw_edge':e} for e in edges]}
def edge(pred=PREDICATE):return {'subject_name':'A','object_name':'C','predicate':pred}
def outputs():return {'p':{'baseline':result([edge('PARTNERS_WITH')]),'licensing':result([edge()])},'n':{'baseline':result([]),'licensing':result([])}}
def test_tuple_correct_but_rejected_quote_does_not_count_as_anchored_success():
    report=summarize(ROWS,refs(),outputs());scores=report['scores']['licensing']
    assert scores['raw_tuple_tp']==1 and scores['anchored_tuple_tp']==0 and scores['anchored_tuple_fn']==1
    assert scores['rejected_licensing_edges']==1
    assert report['scores']['baseline']['raw_tuple_fn']==1

def test_unresolved_references_and_provider_failures_are_not_silently_negative():
    r=refs();r['two']['assessments']['p']={'verdict':'ambiguous','edges':[]}
    report=summarize(ROWS,r,outputs());assert report['unresolved_reference_ids']==['p'] and report['paired_passages']==1
    out=outputs();del out['p']['baseline']
    report=summarize(ROWS,refs(),out);assert report['paired_passages']==1 and report['positive_passages']==0

def test_positive_edge_with_recorded_anchor_counts_once_and_nontargets_are_excluded():
    out=outputs();out['p']['licensing']['anchored_edges']=[{'edge':edge(),'evidence':{'method':'unique_case_only_source_match'}}];out['p']['licensing']['rejected_edges']=[]
    report=summarize(ROWS,refs(),out)
    assert report['scores']['licensing']['anchored_tuple_tp']==1 and report['scores']['licensing']['case_only_source_anchors']==1
    assert report['positive_issuers']==1 and report['reference_licensing_tuples']==1
