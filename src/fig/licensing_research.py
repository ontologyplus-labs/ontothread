"""Controlled licensing intents; reused by live and isolated experimental graphs."""
from fig.contracts import NeighborRequest,PathRequest
PRED='LICENSES_TECHNOLOGY_FROM'
def licensing_plan(text,entity_count):
    text=text.casefold()
    if not any(term in text for term in ['license','licensor','licensing','licensed']):return None
    if any(term in text for term in ['material exposure','financially material','stock price','market reaction']):return None
    if 'shared' in text or 'common licensor' in text:return {'intent':'shared_licensors','requires_entities':True,'predicate':PRED,'min_hops':2,'max_hops':2}
    if 'three-hop' in text or 'three hop' in text:return {'intent':'licensing_paths','requires_entities':True,'predicate':PRED,'min_hops':3,'max_hops':3}
    incoming=any(term in text for term in ['licensees','licenses its','licenses their','licensed to','license technology from']) and 'does ' not in text
    return {'intent':'licensing_neighbors','requires_entities':True,'predicate':PRED,'direction':'incoming' if incoming else 'outgoing','min_hops':1,'max_hops':1}

def answer_licensing(service,request,entities,plan,date_parse):
    common=dict(public_cutoff=request.public_cutoff,knowledge_cutoff=request.knowledge_cutoff,effective_at=request.effective_at,ontology_version=request.ontology_version,identity_cutoff=request.identity_cutoff,limit=100)
    findings=[];relationships=[];paths=[];graph={};reason=None
    def neighbors(entity,direction):
        g=service.store.neighbors(NeighborRequest(entity_id=entity['id'],direction=direction,**common))
        return g,[r for r in g['relationships'] if r['claim']['predicate']==PRED]
    if plan['intent']=='licensing_neighbors':
        graph,relationships=neighbors(entities[0],plan['direction'])
        findings=[{'company_id':r['resolved_subject_id'] if plan['direction']=='incoming' else r['resolved_object_id'],'predicate':PRED,'relationship_id':r.get('relationship_id'),'claim_revision_id':r['claim']['id']} for r in relationships]
    elif plan['intent']=='shared_licensors':
        if len(entities)!=2:reason='shared_licensors_requires_two_companies'
        else:
            graph,left=neighbors(entities[0],'outgoing');_,right=neighbors(entities[1],'outgoing')
            shared={r['resolved_object_id'] for r in left}&{r['resolved_object_id'] for r in right}
            for counterparty in sorted(shared):
                a=next(r for r in left if r['resolved_object_id']==counterparty);b=next(r for r in right if r['resolved_object_id']==counterparty)
                if entities[0]['id']==entities[1]['id']:continue
                findings.append({'company_id':counterparty,'relationship_ids':[a.get('relationship_id'),b.get('relationship_id')],'predicate':PRED})
                relationships.extend([a,b]);paths.append({'entity_ids':[entities[0]['id'],counterparty,entities[1]['id']],'edges':[a,b],'traversals':['forward','reverse'],'derived_direct_edge':False})
    else:
        graph=service.store.paths(PathRequest(source_entity_id=entities[0]['id'],target_entity_id=entities[1]['id'] if len(entities)>1 else None,direction='both',min_hops=3,max_hops=3,**common))
        paths=[p for p in graph['paths'] if any(r['claim']['predicate']==PRED for r in p['edges'])]
        relationships=[r for p in paths for r in p['edges']];findings=[{'entity_ids':p['entity_ids']} for p in paths]
    # Distinguish schema inability from absence; never report current validity when unstated.
    version=graph.get('ontology_version')
    if version and hasattr(service.store,'supports_predicate') and not service.store.supports_predicate(PRED,version):reason='unsupported_by_ontology'
    if version and not reason and hasattr(service.store,'ontology_versions'):
        vs=service.store.ontology_versions()['versions'];snapshot=next((v for v in vs if v['version']==version),None)
        if snapshot and 'definitions' in snapshot and PRED not in snapshot['definitions']['predicates']:reason='unsupported_by_ontology'
    findings=findings[:request.limit];citations=service._relationship_citations(relationships)
    supported=bool(findings) and all(c['assessment']=='supported' for c in citations) and bool(citations)
    return {'question':request.question,'answer':f'Found {len(findings)} documented licensing result(s).' if findings else 'No supported licensing result is available for this request.','intent':plan['intent'],'resolved_entities':entities,'findings':findings,'paths':paths,'entities':graph.get('entities',entities),'citations':citations,'verification':{'status':'supported' if supported else reason or 'no_supported_path','finding_count':len(findings),'citation_count':len(citations),'rule':'Every factual licensing edge requires eligible evidence; shared licensors do not imply direct licensee relationships.'},'query_plan':{'planner':'controlled_licensing_v1',**plan,'date_parse':date_parse,'ontology_version':version,'ontology_schema_hash':graph.get('ontology_schema_hash'),'public_cutoff':request.public_cutoff.isoformat() if request.public_cutoff else None,'knowledge_cutoff':request.knowledge_cutoff.isoformat() if request.knowledge_cutoff else None,'identity_cutoff':request.identity_cutoff.isoformat() if request.identity_cutoff else None,'effective_at':request.effective_at.isoformat() if request.effective_at else None},'generated_cypher':None,'cypher_parameters':None,'execution':'Local evidence-preserving controlled graph selection.','limitations':'Documented connectivity is not economic materiality. Historical grants do not establish ongoing validity.'}
