"""Reference agreement, repair audit, paired document-cluster uncertainty."""
from collections import Counter
import random
PRED='LICENSES_TECHNOLOGY_FROM'
def tuples(edges):return {(e['subject_name'],e['predicate'],e['object_name']) for e in edges}
def score(case,output):
    expected=tuples(case['expected_edges']);excluded=tuples(case.get('unscored_edges',[]))
    predicted=tuples([a['edge'] for a in output['anchored_edges'] if a['edge']['predicate']==PRED])-excluded
    raw=tuples([e for e in output['raw_edges'] if e['predicate']==PRED])-excluded
    ds=output.get('semantic_decisions',[]);repairs=[d for d in ds if d['decision']=='repair']
    return {'case_id':case['case_id'],'accession':case['accession'],'issuer':case['issuer'],'modality':case.get('temporal_scope',case.get('modality','unknown')),'tp':len(expected&predicted),'fp':len(predicted-expected),'fn':len(expected-predicted),'raw_tp':len(expected&raw),'raw_fp':len(raw-expected),'raw_fn':len(expected-raw),'repairs':len(repairs),'correct_repairs':sum((d['validated_edge']['subject_name'],PRED,d['validated_edge']['object_name']) in expected for d in repairs),'incorrect_repairs':sum((d['validated_edge']['subject_name'],PRED,d['validated_edge']['object_name']) not in expected|excluded for d in repairs),'deferred_predictions':sum(d['decision']=='defer' for d in ds),'decision_counts':dict(Counter(d['decision'] for d in ds))}
def aggregate(rows):
    keys=['tp','fp','fn','raw_tp','raw_fp','raw_fn','repairs','correct_repairs','incorrect_repairs','deferred_predictions'];s={k:sum(r[k] for r in rows) for k in keys};tp,fp,fn=s['tp'],s['fp'],s['fn']
    return {'completed_cases':len(rows),**s,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None}
def breakdown(rows):
    return {key:{v:aggregate([r for r in rows if r[key]==v]) for v in sorted({r[key] for r in rows})} for key in ['issuer','accession','modality']}
def paired_bootstrap(left,right,iterations=10000,seed=1729):
    shared={r['case_id'] for r in left}&{r['case_id'] for r in right};left=[r for r in left if r['case_id'] in shared];right=[r for r in right if r['case_id'] in shared];docs=sorted({r['accession'] for r in left});rng=random.Random(seed);vals={'recall_delta':[],'precision_delta':[]}
    def delta(a,b,key):return None if a[key] is None or b[key] is None else b[key]-a[key]
    point={k:delta(aggregate(left),aggregate(right),k.split('_')[0]) for k in vals}
    for _ in range(iterations if docs else 0):
        selection=[rng.choice(docs) for _ in docs];a=aggregate([r for d in selection for r in left if r['accession']==d]);b=aggregate([r for d in selection for r in right if r['accession']==d])
        for k in vals:
            v=delta(a,b,k.split('_')[0])
            if v is not None:vals[k].append(v)
    intervals={}
    for k,v in vals.items():
        v.sort();intervals[k]={'point':point[k],'lower':v[int(.025*(len(v)-1))] if v else None,'upper':v[int(.975*(len(v)-1))] if v else None,'defined_resamples':len(v)}
    return {'paired_cases':len(shared),'document_clusters':len(docs),'iterations':iterations,'seed':seed,'effects':intervals,'statistical_claim':'supported' if intervals['recall_delta']['lower'] is not None and intervals['recall_delta']['lower']>0 and intervals['precision_delta']['lower'] is not None and intervals['precision_delta']['lower']>=-.05 else 'inconclusive'}
