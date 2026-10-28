"""Focused licensing agreement metrics; other predicates are not reference-complete."""
from fig.licensing_review import PREDICATE

def summarize(rows,references,outputs):
    rowmap={r['passage_id']:r for r in rows};paired=[];unresolved=[]
    for row in rows:
        pid=row['passage_id'];assessments=[r['assessments'][pid] for r in references.values()]
        sets=[{(e['licensee'],e['licensor']) for e in a['edges']} for a in assessments]
        if len(assessments)!=2 or assessments[0]['verdict']!=assessments[1]['verdict'] or assessments[0]['verdict']=='ambiguous' or sets[0]!=sets[1]:unresolved.append(pid);continue
        if set(outputs.get(pid,{}))=={'baseline','licensing'}:paired.append((pid,sets[0]))
    scores={}
    for condition in ['baseline','licensing']:
        raw_tp=raw_fp=raw_fn=anchored_tp=anchored_fp=anchored_fn=0;predicted=exact=case_only=rejected=0
        for pid,expected in paired:
            result=outputs[pid][condition];raw=[e for e in result['raw_edges'] if e['predicate']==PREDICATE];accepted=[r for r in result['anchored_edges'] if r['edge']['predicate']==PREDICATE]
            predicted+=len(raw);exact+=sum(r['evidence']['method']=='exact' for r in accepted);case_only+=sum(r['evidence']['method']=='unique_case_only_source_match' for r in accepted)
            rejected+=sum(r['raw_edge']['predicate']==PREDICATE for r in result['rejected_edges'])
            actual={(e['subject_name'],e['object_name']) for e in raw};anchored={(r['edge']['subject_name'],r['edge']['object_name']) for r in accepted}
            raw_tp+=len(actual&expected);raw_fp+=len(actual-expected);raw_fn+=len(expected-actual)
            anchored_tp+=len(anchored&expected);anchored_fp+=len(anchored-expected);anchored_fn+=len(expected-anchored)
        scores[condition]={'raw_tuple_tp':raw_tp,'raw_tuple_fp':raw_fp,'raw_tuple_fn':raw_fn,'anchored_tuple_tp':anchored_tp,'anchored_tuple_fp':anchored_fp,'anchored_tuple_fn':anchored_fn,
                           'anchored_recall_agreement':anchored_tp/(anchored_tp+anchored_fn) if anchored_tp+anchored_fn else None,
                           'anchored_precision_agreement':anchored_tp/(anchored_tp+anchored_fp) if anchored_tp+anchored_fp else None,
                           'raw_licensing_edges':predicted,'exact_source_quotes':exact,'case_only_source_anchors':case_only,'rejected_licensing_edges':rejected}
    positive_ids=[pid for pid,s in paired if s]
    return {'scope':'licensing-only agreement against two same-model reference roles; not independent accuracy or full-graph precision',
            'sample_passages':len(rows),'paired_passages':len(paired),'unresolved_reference_ids':unresolved,
            'positive_passages':len(positive_ids),'positive_documents':len({rowmap[pid]['accession'] for pid in positive_ids}),
            'positive_issuers':len({rowmap[pid]['issuer'] for pid in positive_ids}),'reference_licensing_tuples':sum(len(s) for _,s in paired),'scores':scores}
