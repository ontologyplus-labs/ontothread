"""Pure claim, path and citation agreement helpers for research experiments."""
def path_key(p):return (tuple(p['entity_ids']),tuple((e['claim']['subject_id'],e['claim']['predicate'],e['claim']['object_id']) for e in p['edges']))
def citation_keys(a):return {(c['claim_revision_id'],c['passage_id']) for c in a.get('citations',[])}
def score_answer(expected,actual,unsupported=False):
    e=citation_keys(expected);a=citation_keys(actual);ep={path_key(p) for p in expected.get('paths',[])};ap={path_key(p) for p in actual.get('paths',[])}
    return {'claim_tp':len({k[0] for k in e}&{k[0] for k in a}),'false_claims':len({k[0] for k in a}-{k[0] for k in e}),'missed_claims':len({k[0] for k in e}-{k[0] for k in a}),'path_tp':len(ep&ap),'false_paths':len(ap-ep),'missed_paths':len(ep-ap),'citation_tp':len(e&a),'false_citations':len(a-e),'missed_citations':len(e-a),'answer_complete':e<=a and ep<=ap,'correct_abstention':not a and not ap and not actual.get('findings') if unsupported else None}
