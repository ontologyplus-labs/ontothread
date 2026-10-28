"""Auditable source anchoring; never silently edits a provider's raw quotation."""
def anchor_quote(text,quote):
    if not isinstance(quote,str) or not quote:return {'status':'rejected','reason':'empty_quote'}
    if text.count(quote)==1:
        start=text.index(quote);return {'status':'anchored','method':'exact','start':start,'end':start+len(quote),'source_quote':quote,'raw_quote':quote}
    if quote in text:return {'status':'rejected','reason':'ambiguous_exact_quote','raw_quote':quote}
    folded=[];positions=[]
    for i,c in enumerate(text):
        f=c.casefold();folded.append(f);positions.extend([i]*len(f))
    target=quote.casefold();haystack=''.join(folded)
    first=haystack.find(target)
    if first<0:return {'status':'rejected','reason':'no_case_only_match','raw_quote':quote}
    if haystack.find(target,first+1)>=0:return {'status':'rejected','reason':'ambiguous_case_only_match','raw_quote':quote}
    start=positions[first];end=positions[first+len(target)-1]+1;source=text[start:end]
    if source.casefold()!=target:return {'status':'rejected','reason':'partial_unicode_expansion','raw_quote':quote}
    return {'status':'anchored','method':'unique_case_only_source_match','start':start,'end':end,'source_quote':source,'raw_quote':quote}

def anchor_edge(source,edge):
    anchor=anchor_quote(source['text'],edge.get('quote'))
    if anchor['status']=='rejected':return anchor
    for field in ['subject_name','object_name']:
        if edge.get(field) not in anchor['source_quote'] and not (field=='subject_name' and edge.get(field)==source['issuer']):
            return {'status':'rejected','reason':'endpoint_absent_from_anchored_quote','raw_quote':edge.get('quote')}
    return {**anchor,'entailment':'not_established_by_anchoring'}
