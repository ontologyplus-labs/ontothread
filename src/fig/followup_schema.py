"""Development schema approval gate and separate evidence scoring contracts."""
from datetime import datetime
from hashlib import sha256
import json

DISPOSITIONS={'existing_concept','new_predicate','new_entity_kind','qualifier','subtype','synonym_merge','unsupported','defer'}


def validate_review(rows, metadata, candidates):
    expected={c['id']:c for c in candidates}
    if len(rows)!=len(expected) or {r['candidate_id'] for r in rows}!=set(expected):
        raise ValueError('candidate IDs or row count differ')
    if not metadata.get('reviewer_id') or metadata.get('reviewed_independently') is not True:
        raise ValueError('reviewer identity and independent-review attestation required')
    times=[]
    for key in ('started_at_utc','completed_at_utc'):
        value=metadata.get(key,'')
        if not value.endswith('Z'):raise ValueError('actual UTC times ending in Z required')
        times.append(datetime.fromisoformat(value.replace('Z','+00:00')))
    if times[1]<times[0]:raise ValueError('completion precedes start')
    for row in rows:
        candidate=expected[row['candidate_id']]
        if row.get('disposition') not in DISPOSITIONS or not row.get('rationale','').strip():
            raise ValueError('complete disposition and rationale required')
        allowed=set(candidate['supporting_passages']+candidate['boundary_passages'])
        for field in ('supported_example_ids','rejected_example_ids','counterexample_ids'):
            values=row.get(field)
            if not isinstance(values,list) or len(values)!=len(set(values)) or not set(values)<=allowed:
                raise ValueError('example IDs outside supplied candidate evidence')
        if set(row['supported_example_ids'])&set(row['rejected_example_ids']):
            raise ValueError('same example both supported and rejected')
        if row['disposition']=='new_predicate':
            if not row.get('corrected_definition','').strip() or not row.get('subject_types') or not row.get('object_types'):
                raise ValueError('new predicate needs definition and endpoint types')
            if not row['supported_example_ids'] or not row['counterexample_ids']:
                raise ValueError('new predicate needs supporting and boundary examples')
    return True


def capacity_approval(reviews, metadata, candidates, evidence):
    """Return eligibility only. No schema installation or reviewer fabrication."""
    if len(reviews)!=2 or len(metadata)!=2:raise ValueError('two review submissions required')
    for rows,meta in zip(reviews,metadata):validate_review(rows,meta,candidates)
    if metadata[0]['reviewer_id']==metadata[1]['reviewer_id']:
        raise ValueError('distinct reviewer IDs required')
    chosen=[next(r for r in rows if r['candidate_id']=='capacity-entitlement') for rows in reviews]
    if any(r['disposition']!='new_predicate' for r in chosen):
        return {'status':'not_approved','reason':'new-predicate approval not unanimous'}
    for row in chosen:
        if row['subject_types']!=['Company'] or row['object_types']!=['Company']:
            return {'status':'requires_adjudication','reason':'endpoint contract differs from isolated draft'}
    if chosen[0]['corrected_definition'].strip()!=chosen[1]['corrected_definition'].strip():
        return {'status':'requires_adjudication','reason':'definitions differ; no automatic semantic equivalence claim'}
    support=set(chosen[0]['supported_example_ids'])&set(chosen[1]['supported_example_ids'])
    by_id={r['passage_id']:r for r in evidence}
    if len({by_id[i]['document_id'] for i in support})<2:
        return {'status':'deferred','reason':'fewer than two shared supported documents'}
    return {'status':'eligible_for_schema_freeze','predicate':'HAS_CAPACITY_ENTITLEMENT_IN','definition':chosen[0]['corrected_definition'].strip(),
            'supported_example_ids':sorted(support),'independence':'self_attested; not separately verified','active_schema_changed':False}


def evaluate_quote(text, quote, accepted_spans):
    """Structural span match only. Entailment is a separate reviewed assessment."""
    if not quote or text.count(quote)!=1:
        return {'structurally_valid':False,'accepted_span_match':False,'entailment':'not_assessed'}
    start=text.index(quote);end=start+len(quote)
    matching=any(start<=span['start'] and end>=span['end'] and text[span['start']:span['end']]==span['text'] for span in accepted_spans)
    return {'structurally_valid':True,'accepted_span_match':matching,'entailment':'not_assessed'}


def canonical_schema_hash(definitions):
    return sha256(json.dumps(definitions,sort_keys=True,separators=(',',':')).encode()).hexdigest()
