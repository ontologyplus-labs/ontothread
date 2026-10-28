"""Source-selected evidence ranges and auditable licensing temporal checks."""
from copy import deepcopy
from hashlib import sha256
import json
import re
from fig.generic_extraction import payload,ProviderFailure
from fig.licensing_policy_guard import GuardedLicensingExtractor
from fig.licensing_review import PREDICATE

ABBREVIATIONS=('inc.','ltd.','corp.','co.','u.s.','n.v.','b.v.','e.g.','i.e.')
def source_units(text):
    boundaries=[0]
    for m in re.finditer(r'[.!?](?=\s+[A-Z\u2022])',text):
        if any(text[:m.end()].lower().endswith(a) for a in ABBREVIATIONS):continue
        start=m.end()
        while start<len(text) and text[start].isspace():start+=1
        boundaries.append(start)
    boundaries.append(len(text));units=[]
    for start,end in zip(boundaries,boundaries[1:]):
        while end>start and text[end-1].isspace():end-=1
        if end>start:units.append({'id':len(units),'start':start,'end':end,'text':text[start:end]})
    return units

FUTURE=re.compile(r'(?i)\b(?:(?:will|would)\s+(?:be\s+)?(?:granted|grant|receive|obtain)|(?:expected|scheduled|planned)\s+to\s+(?:be\s+)?(?:granted|grant|receive|obtain))\b.{0,100}\b(?:licen[cs]e|rights?)\b')
CONDITIONAL=re.compile(r'(?i)\b(?:may|might|could)\b.{0,75}\b(?:sub[ -]?licen[cs]e|receive|obtain|grant)\b.{0,90}\b(?:technolog\w*|licen[cs]e|rights?)\b')
# Covers the natural "may ... sub-license such technology" phrase directly.
SUBLICENSE=re.compile(r'(?i)\b(?:may|might|could)\b.{0,75}\bsub[ -]?licen[cs]e\b')
PERMISSION=re.compile(r'(?i)\b(?:allowed|permitted|authorized)\s+to\s+sub[ -]?licen[cs]e\b')
POSITIVE=re.compile(r'(?i)\b(?:granted|grants|obtained)\b.{0,140}\b(?:licen[cs]e|rights?)\b|\b(?:licen[cs]e|licensed)\b.{0,160}\bfrom\b|\b(?:entered\s+into|have)\b.{0,100}\bcross[ -]licen[cs]es\b')

def licensing_temporal_check(quote,state):
    if state in {'future_grant','conditional_grant','uncertain','not_applicable'}:
        return {'eligible':False,'reason':'model_reports_non_granted_or_uncertain_license','model_state':state}
    future=FUTURE.search(quote);conditional=CONDITIONAL.search(quote) or SUBLICENSE.search(quote) or PERMISSION.search(quote)
    if future or conditional:
        blocked=list(FUTURE.finditer(quote))+list(CONDITIONAL.finditer(quote))+list(SUBLICENSE.finditer(quote))+list(PERMISSION.finditer(quote))
        positive=any(not any(b.start()<=m.start()<b.end() for b in blocked) for m in POSITIVE.finditer(quote))
        return {'eligible':False,'reason':'mixed_grant_context_requires_narrower_span' if positive else 'future_or_conditional_grant_cue',
                'source_cue':(future or conditional).group(),'model_state':state}
    return {'eligible':True,'reason':'no_blocking_grant_modality_cue','model_state':state,
            'ongoing_validity':'not_inferred' if state=='historical_grant' else 'as_disclosed_only','semantic_entailment':'not_established_by_temporal_check'}

def span_request(source,policy,semantics):
    request=payload(source,policy,semantics,max_output_tokens=2500);units=source_units(source['text'])
    if not units:raise ValueError('empty source')
    item=request['text']['format']['schema']['properties']['edges']['items'];props=item['properties'];del props['quote']
    props.update(start_unit={'type':'integer','minimum':0,'maximum':len(units)-1},end_unit={'type':'integer','minimum':0,'maximum':len(units)-1},
                 grant_state={'type':'string','enum':['granted_or_held','historical_grant','future_grant','conditional_grant','uncertain','not_applicable']})
    item['required']=sorted(props)
    request['text']['format']['name']='source_selected_relations'
    request['input'][0]['content']+='\nEvidence interface: select start_unit and end_unit (inclusive) from the supplied source units. Never compose or abbreviate a quote. Choose the shortest contiguous range that contains every non-issuer endpoint and the complete directed assertion. For licensing, distinguish an already granted/held right from a future or conditional grant. Past explicit grants can be historical_grant; do not infer their ongoing validity. Future production under an already granted license does not make the grant future. Set not_applicable for other predicates. Do not infer a licensor merely from manufacture-for or customer language. A permission to sublicense is not a completed sublicense.'
    request['input'][1]['content']=json.dumps({'issuer':source['issuer_name'],'source_units':[{'id':u['id'],'text':u['text']} for u in units]},ensure_ascii=False)
    return request

class SourceSpanLicensingExtractor(GuardedLicensingExtractor):
    def __call__(self,source,condition):
        request=span_request(source,{'snapshot':self.snapshots[condition]},self.semantic_catalog)
        return self.process_spans(source,condition,self.provider.call(request))

    def process_spans(self,source,condition,result,*,temporal_guard=True):
        if sha256(source['text'].encode()).hexdigest()!=source['text_hash']:raise ValueError('source checksum differs')
        if set(result)!={'edges'} or not isinstance(result['edges'],list) or len(result['edges'])>30:raise ProviderFailure('invalid_span_envelope')
        units=source_units(source['text']);converted=[];mapping=[];span_rejections=[]
        for i,edge in enumerate(result['edges']):
            expected={'subject_name','subject_kind','predicate','object_name','object_kind','start_unit','end_unit','grant_state'}
            if set(edge)!=expected:raise ProviderFailure('invalid_span_edge_fields')
            if edge['grant_state'] not in {'granted_or_held','historical_grant','future_grant','conditional_grant','uncertain','not_applicable'}:raise ProviderFailure('invalid_grant_state')
            first,last=edge['start_unit'],edge['end_unit']
            if type(first)!=int or type(last)!=int or not 0<=first<=last<len(units):
                span_rejections.append({'provider_edge_index':i,'raw_span_edge':deepcopy(edge),'reason':'invalid_source_unit_range'});continue
            quote=source['text'][units[first]['start']:units[last]['end']]
            converted.append({k:edge[k] for k in ['subject_name','subject_kind','predicate','object_name','object_kind']}|{'quote':quote})
            mapping.append({'provider_edge_index':i,'raw_span_edge':deepcopy(edge),'source_start':units[first]['start'],'source_end':units[last]['end']})
        output=super().process(source,condition,{'edges':converted});kept=[]
        for item in output['anchored_edges']:
            info=mapping[item['edge_index']];item['span_selection']=info
            item['evidence'].update(method='source_unit_range',start=info['source_start'],end=info['source_end'])
            if item['edge']['predicate']==PREDICATE:
                decision=licensing_temporal_check(item['edge']['quote'],info['raw_span_edge']['grant_state']);item['temporal_check']=decision
                if temporal_guard and not decision['eligible']:
                    output['rejected_edges'].append({'edge_index':item['edge_index'],'raw_edge':item['raw_edge'],'span_selection':info,'reason':decision['reason'],'temporal_check':decision});continue
            kept.append(item)
        output['anchored_edges']=kept;output['raw_span_edges']=deepcopy(result['edges']);output['span_rejections']=span_rejections
        output['temporal_guard_enabled']=temporal_guard;output['quote_origin']='copied_from_source_unit_range; no provider-authored quote'
        return output
