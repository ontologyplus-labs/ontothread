"""Explicit reference agreement on an enriched, agent-curated licensing set."""
from fig.licensing_review import PREDICATE

def score_cases(cases,outputs):
    per_case=[]
    for case in cases:
        pid=case['passage_id'];expected={(e['subject_name'],e['object_name']) for e in case['expected_edges']}
        unscored={(e['subject_name'],e['object_name']) for e in case.get('unscored_implicit_reciprocal_rights',[])}
        for condition in ['baseline','licensing']:
            result=outputs.get(pid,{}).get(condition)
            if result is None:
                per_case.append({'case_id':case['case_id'],'condition':condition,'status':'failed','temporal_scope':case['temporal_scope']});continue
            raw={ (e['subject_name'],e['object_name']) for e in result['raw_edges'] if e['predicate']==PREDICATE}
            retained={(a['edge']['subject_name'],a['edge']['object_name']) for a in result['anchored_edges'] if a['edge']['predicate']==PREDICATE}
            row={'case_id':case['case_id'],'condition':condition,'status':'completed','issuer':case['issuer'],'temporal_scope':case['temporal_scope'],'expected_tuples':len(expected),
                 'unscored_raw_reciprocal_predictions':len(raw&unscored),'unscored_retained_reciprocal_predictions':len(retained&unscored)}
            for name,actual in [('raw',raw-unscored),('retained',retained-unscored)]:
                row.update({name+'_tp':len(expected&actual),name+'_fp':len(actual-expected),name+'_fn':len(expected-actual)})
            targeted=[a for a in result['anchored_edges'] if a['edge']['predicate']==PREDICATE]
            row.update(exact_source_quotes=sum(a['evidence']['method']=='exact' for a in targeted),case_only_source_anchors=sum(a['evidence']['method']=='unique_case_only_source_match' for a in targeted),
                       rejected_licensing_edges=sum(a['raw_edge']['predicate']==PREDICATE for a in result['rejected_edges']))
            per_case.append(row)
    groups={}
    for group in ['all','as_disclosed','historical_grant','negative_cases']:
        groups[group]={}
        for condition in ['baseline','licensing']:
            selected=[r for r in per_case if r['condition']==condition and r['status']=='completed' and
                      (group=='all' or group=='negative_cases' and r['expected_tuples']==0 or group in ['as_disclosed','historical_grant'] and r['temporal_scope']==group and r['expected_tuples']>0)]
            totals={k:sum(r[k] for r in selected) for k in ['expected_tuples','raw_tp','raw_fp','raw_fn','retained_tp','retained_fp','retained_fn','exact_source_quotes','case_only_source_anchors','rejected_licensing_edges']}
            tp,fp,fn=totals['retained_tp'],totals['retained_fp'],totals['retained_fn']
            groups[group][condition]={'completed_cases':len(selected),**totals,'recall_agreement':tp/(tp+fn) if tp+fn else None,'precision_agreement':tp/(tp+fp) if tp+fp else None}
    return {'groups':groups,'per_case':per_case,'missing_condition_results':sum(r['status']=='failed' for r in per_case),
            'scope':'Agreement with agent-curated references on a purposively enriched source challenge set; not independent accuracy, prevalence, or full-graph precision.'}
