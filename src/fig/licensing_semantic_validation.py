"""Conservative source-grounded licensing decisions; never accepts production claims."""
from copy import deepcopy
from hashlib import sha256
import re
from fig.span_licensing_extraction import source_units,licensing_temporal_check
from fig.licensing_review import PREDICATE

TECH=re.compile(r'(?i)\b(?:technolog\w*|patents?|software|process(?:es)?|intellectual property|technical rights|standard cells?|memory|I/O)\b')
TRADEMARK=re.compile(r'(?i)\b(?:trademarks?|word marks?|logos?|brands?)\b')
EXPORT=re.compile(r'(?i)\b(?:export|regulatory|government|USG|BIS|Department of Commerce)\b')
TITLE=re.compile(r'(?i)\b(?:intellectual property(?: transfer and)?|patent|technology|semiconductor)?\s*(?:cross[ -])?licen[cs]e agreement\s*,?\s*dated(?: as of)?\b')
DISPUTE=re.compile(r'(?i)\b(?:requested|seeks?|sought|claimed|alleges?|asserts?)\b.{0,140}\b(?:finding|judgment|license|licensed)\b|\b(?:disputed|contested|alleged)\s+(?:license|rights)\b')
NEGATED=re.compile(r'(?i)\b(?:not|never|no longer)\s+(?:(?:been|be|have|has|was|were|a|any)\s+){0,3}(?:granted|licensed|obtained|license|rights)\b|\bno\s+(?:license|rights)\b')
NONACTUAL=re.compile(r'(?i)\b(?:will|would|may|might|could|plans? to|intends? to|expects? to|seeks? to)\b.{0,70}\b(?:grant|granted|receive|obtain|licen[cs]e|sub[ -]?licen[cs]e)\b|\b(?:allowed|permitted|authorized) to sub[ -]?licen[cs]e\b')
RULESET='licensing-semantic-v1'

def name_pattern(name,issuer):
    literal=r'(?<!\w)'+re.escape(name)+r'(?!\w)'
    return '(?:'+literal+r'|\bwe\b)' if name==issuer else literal

def role_assertions(text,issuer,pair):
    """Return only roles established for the existing pair, never new identities."""
    units=source_units(text);found=[]
    for recipient,provider in [pair,tuple(reversed(pair))]:
        r=name_pattern(recipient,issuer);p=name_pattern(provider,issuer)
        for u in units:
            s=u['text']
            # Separate finite clauses where possible; clause support is checked below.
            patterns=[
              ('grant_recipient',p+r'\s+(?:has\s+)?grant(?:ed|s)\s+'+r+r'\s+(?:a\s+)?(?:royalt\w*\s+(?:bearing|free)\s+)?(?:(?:software|patent|technology|technical)\s+)?licen[cs]e\b'),
              ('grant_to_recipient',p+r'\s+(?:has\s+)?grant(?:ed|s)\s+(?:a\s+)?(?:royalt\w*\s+(?:bearing|free)\s+)?(?:(?:software|patent|technology|technical)\s+)?licen[cs]e\b.{0,180}?\bto\s+'+r),
              ('passive_grant',r+r'\s+(?:(?:has|have)\s+been|was|were|is)\s+granted\b.{0,180}?\blicen[cs]e\b.{0,120}?\bby\s+'+p),
              ('license_from',r+r'\b.{0,300}?\blicen[cs](?:e|es|ed|ing)\b.{0,180}?\bfrom\b.{0,150}?'+p),
              ('obtained_rights_from',r+r'\b.{0,60}?\b(?:obtained|received)\b.{0,160}?\b(?:rights|licen[cs]e)\b.{0,100}?\bfrom\s+'+p),
              ('obtained_under_agreements',r+r'\b.{0,70}?\bentered into\b.{0,160}?\blicen[cs]e agreements?\b.{0,80}?\bwith\b.{0,180}?'+p+r'.{0,200}?\bunder which\s+we\s+(?:have\s+)?obtained rights\b'),
              ('rights_under_named_agreements',r+r'\s+(?:have\s+)?obtained\s+(?:technical\s+)?rights\b.{0,100}?\bunder\b.{0,70}?\blicen[cs]e agreements? with\b.{0,80}?'+p),
            ]
            for rule,pattern in patterns:
                m=re.search(pattern,s,re.I)
                if not m:continue
                support=s[m.start():min(len(s),m.end()+180)]
                if rule=='license_from':
                    tail=re.split(r'\bfrom\b',m.group(),flags=re.I)[-1]
                    if re.search(r'(?i)\b(?:sell\w*|manufactur\w*|customer\w*|ship\w*|suppl\w*|for|to)\b',tail):continue
                technical_scope=support
                for endpoint in pair:technical_scope=technical_scope.replace(endpoint,'')
                # Exclusion checks operate on this assertion, not an unrelated later sentence.
                if TECH.search(technical_scope) and not (NONACTUAL.search(support) or NEGATED.search(support) or DISPUTE.search(support)):
                    found.append({'recipient':recipient,'provider':provider,'rule_id':rule,'start':u['start'],'end':u['end'],'assertion_text':s})
            if recipient==issuer:
                m=re.search(r'\bwe\s+(?:have\s+)?entered into\s+patent cross[ -]licenses with\b.{0,240}?'+p,s,re.I)
                if m and not NONACTUAL.search(s):
                    following=next((v for v in units if v['start']>u['start']),None)
                    if following and re.search(r'(?i)^these cross[ -]licenses provide us with.{0,120}under patents owned.{0,80}such companies',following['text']):
                        found.append({'recipient':recipient,'provider':provider,'rule_id':'cross_license_received_rights','start':u['start'],'end':following['end'],'assertion_text':text[u['start']:following['end']]})
    return found

def validate_licensing(source,item,definition,*,allow_repairs=True):
    raw=deepcopy(item['edge']);text=source['text'];quote=raw['quote'];ev=item['evidence'];start,end=ev['start'],ev['end']
    if sha256(text.encode()).hexdigest()!=source['text_hash'] or text[start:end]!=quote:raise ValueError('source evidence differs')
    if not definition or 'licensee' not in definition.casefold() or 'licensor' not in definition.casefold():raise ValueError('frozen licensing direction definition required')
    decision={'ruleset':RULESET,'raw_edge':raw,'definition_sha256':sha256(definition.encode()).hexdigest(),'original_span':{'start':start,'end':end},'production_acceptance':False}
    def finish(status,rule,why,edge=None,span=None):
        result={**decision,'decision':status,'rule_id':rule,'explanation':why,'supporting_span':span or {'start':start,'end':end}}
        if edge is not None:result['validated_edge']=edge
        return result
    if raw['predicate']!=PREDICATE:return finish('pass','other_predicate_unchanged','Licensing validation does not evaluate other predicates.',raw)
    if raw['subject_name']==raw['object_name']:return finish('reject','self_license','This directed predicate requires distinct companies.')
    pair=(raw['subject_name'],raw['object_name'])
    # Look only at units intersecting the selected range, plus one immediately following
    # unit for the explicit cross-license received-rights construction. No free context search.
    units=source_units(text);overlap=[u for u in units if u['start']<end and u['end']>start]
    if not overlap:return finish('defer','no_complete_source_unit','No complete assertion is available.')
    last=units.index(overlap[-1]);context_end=units[last+1]['end'] if last+1<len(units) else end
    context_start=overlap[0]['start'];context=text[context_start:context_end]
    facts=role_assertions(context,source['issuer_name'],pair)
    facts=[f for f in facts if f['start']+context_start<end and f['end']+context_start>start]
    directions={(f['recipient'],f['provider']) for f in facts}
    if len(directions)>1:return finish('defer','competing_roles','Source establishes competing directions; a narrower assertion is required.')
    if facts:
        fact=min(facts,key=lambda f:(f['end']-f['start'],f['start']));a,b=context_start+fact['start'],context_start+fact['end'];support=text[a:b]
        # Mixed technical/regulatory or trademark scope must not be guessed.
        if re.search(r'(?i)\bexport licen[cs]e\b',support):return finish('reject','export_permission','An export license is an excluded authorization.')
        if TRADEMARK.search(support) or EXPORT.search(support):return finish('defer','mixed_scope','Technical and excluded scopes are not separable in the supporting assertion.')
        checked=licensing_temporal_check(support,item.get('temporal_check',{}).get('model_state','granted_or_held'))
        if not checked['eligible']:return finish('reject','nonactual_grant',checked['reason'])
        correct=deepcopy(raw);correct.update(subject_name=fact['recipient'],object_name=fact['provider'],quote=support)
        span={'start':a,'end':b}
        if (correct['subject_name'],correct['object_name'])==pair:return finish('pass',fact['rule_id'],'Explicit source roles and technical scope support this direction.',correct,span)
        if not allow_repairs:return finish('reject','reversed_roles','Explicit source roles contradict the proposed direction.')
        return finish('repair',fact['rule_id'],'Swapped only the original endpoint pair to match explicit licensee and licensor roles.',correct,span)
    if TITLE.search(quote) and not re.search(r'(?i)\b(?:granted|obtained|received|licenses|licensed)\b',quote):return finish('reject','agreement_title_only','Dated agreement reference does not assert a directed grant.')
    if TRADEMARK.search(quote) and not re.search(r'(?i)\b(?:patents?|software|process technolog\w*|technical)\b',quote):return finish('reject','trademark_only','Brand or trademark permissions are outside technical licensing.')
    if EXPORT.search(quote) and re.search(r'(?i)\b(?:exports?|ship|regulatory|government|USG|BIS)\b',quote):return finish('reject','export_permission','Export/regulatory authorization is not a company technology license.')
    if NEGATED.search(quote):return finish('reject','negated_grant','The cited grant is explicitly negated.')
    if DISPUTE.search(quote):return finish('reject','disputed_grant','A disputed or requested finding is not an established grant.')
    if NONACTUAL.search(quote):return finish('reject','nonactual_grant','A proposed, future, or conditional grant is not a completed grant.')
    return finish('defer','roles_or_scope_unresolved','The bounded grammar cannot establish the directed technical license.')

def apply_semantics(source,output,definition,*,allow_repairs=True):
    result=deepcopy(output);kept=[];decisions=[]
    for item in result['anchored_edges']:
        d=validate_licensing(source,item,definition,allow_repairs=allow_repairs)
        if item['edge']['predicate']==PREDICATE:decisions.append(d)
        if d['decision'] in {'pass','repair'}:
            item['edge']=d['validated_edge'];item['semantic_decision']=d
            span=d['supporting_span'];item['evidence'].update(start=span['start'],end=span['end'],source_quote=item['edge']['quote'],method='source_unit_range')
            item['evidence_adjustment']={'original':d['original_span'],'validated':span,'source_only':True}
            kept.append(item)
        else:result['rejected_edges'].append({'edge_index':item['edge_index'],'raw_edge':item['raw_edge'],'reason':d['rule_id'],'semantic_decision':d})
    result['anchored_edges']=kept;result['semantic_decisions']=decisions;result['semantic_ruleset']=RULESET;result['audited_repairs_enabled']=allow_repairs
    return result
