"""Controlled natural-language research planning over authoritative graph queries."""
import re
from datetime import datetime,timezone,timedelta

from fig.contracts import NeighborRequest,PathRequest,ResearchRequest
from fig.licensing_research import licensing_plan,answer_licensing


MUTATING_CYPHER=re.compile(r"\b(?:CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH|UNWIND|USE)\b",re.I)


def validate_readonly_cypher(query):
    stripped=query.strip()
    if len(stripped)>4000 or ";" in stripped or "//" in stripped or "/*" in stripped or MUTATING_CYPHER.search(stripped):raise ValueError("generated Cypher is not read-only")
    if not stripped.upper().startswith("MATCH ") or " RETURN " not in stripped.upper():raise ValueError("generated Cypher must be a MATCH query")
    if "[:BUSINESS_RELATION*1..3]" not in stripped:raise ValueError("generated Cypher must use the bounded business relationship projection")
    if " LIMIT $limit" not in stripped:raise ValueError("generated Cypher must retain a parameterized result limit")
    if "all(r IN relationships(p)" not in stripped:raise ValueError("generated Cypher must retain edge eligibility and temporal filters")
    return stripped


def execute_readonly_cypher(uri,user,password,query,parameters,*,driver_factory=None):
    """Execute only a validated bounded query and return plain serializable path data."""
    from neo4j import GraphDatabase
    query=validate_readonly_cypher(query);driver_factory=driver_factory or GraphDatabase.driver
    safe={"source_id":str(parameters["source_id"]),"target_id":str(parameters["target_id"]) if parameters.get("target_id") else None,
          "min_hops":max(1,min(3,int(parameters.get("min_hops",1)))),"max_hops":max(1,min(3,int(parameters["max_hops"]))),"limit":max(1,min(50,int(parameters["limit"]))),
          "public_cutoff":parameters.get("public_cutoff"),"effective_at":parameters.get("effective_at"),"ontology_version":parameters.get("ontology_version")}
    with driver_factory(uri,auth=(user,password)) as driver:
        driver.verify_connectivity()
        with driver.session(default_access_mode="READ") as session:
            records=session.run(query,**safe).data()
    return {"records":records,"count":len(records),"query_source":"neo4j_read_projection"}


class ResearchService:
    def __init__(self,store):self.store=store

    def mentioned_entities(self,question):
        question_norm=self.store.normalize_alias(question)
        with self.store.connect() as conn:
            rows=self.store.execute(conn,"""SELECT e.payload,LOWER(e.canonical_name) AS canonical,a.normalized_alias,i.value AS identifier
                FROM entity e LEFT JOIN entity_alias a ON a.entity_id=e.id
                LEFT JOIN entity_identifier i ON i.entity_id=e.id
                WHERE e.kind='Company'""").fetchall()
        matches={}
        for row in rows:
            entity=__import__('json').loads(row['payload'])
            candidates=[row['canonical'],row['normalized_alias'],str(row['identifier']).casefold() if row['identifier'] else None]
            for candidate in candidates:
                if not candidate:continue
                normalized=self.store.normalize_alias(candidate)
                if re.search(r"(?<![a-z0-9])"+re.escape(normalized)+r"(?![a-z0-9])",question_norm):
                    position=question_norm.find(normalized);candidate_match=(position,-len(normalized),entity)
                    if entity['id'] not in matches or candidate_match[:2]<matches[entity['id']][:2]:matches[entity['id']]=candidate_match
        return [item[2] for item in sorted(matches.values(),key=lambda item:(item[0],item[1],item[2]['canonical_name']))]

    @staticmethod
    def _path_freshness(path):
        dates=[evidence['document']['published_at'] for edge in path['edges'] for evidence in edge['evidence']]
        return max(dates) if dates else ''

    def plan(self,request,entities):
        text=request.question.casefold()
        if any(term in text for term in ("ontology","schema version","schema change")):
            return {"intent":"ontology_inspection","requires_entities":False}
        if any(term in text for term in ("financially material","material exposure","prove materiality","establish materiality")):
            return {"intent":"unsupported_financial_analysis","requires_entities":bool(entities)}
        license_plan=licensing_plan(text,len(entities))
        if license_plan:return license_plan
        if len(entities)>=2 and any(term in text for term in ("shared manufacturer","same manufacturer","common manufacturer","common foundry","shared foundry")):
            return {"intent":"shared_manufacturer","requires_entities":True,"predicate":"CONTRACTS_MANUFACTURING_TO"}
        if len(entities)==1 and re.search(r'\bshare(?:d)?\b',text) and any(term in text for term in ("manufacturer","supplier","counterparty")):
            return {"intent":"shared_counterparty_network","requires_entities":True,"min_hops":2,"max_hops":2}
        if len(entities)==1 and "named" in text and "manufactur" in text:
            return {"intent":"named_manufacturing_counterparties","requires_entities":True,
                    "predicates":["CONTRACTS_MANUFACTURING_TO","SUPPLIES_TO"]}
        if len(entities)==1 and "second-order" not in text and "second order" not in text and ("exposure to" in text or "manufactured by" in text or ("which companies" in text and "foundr" in text)):
            return {"intent":"incoming_manufacturing","requires_entities":True,"predicate":"CONTRACTS_MANUFACTURING_TO"}
        if any(term in text for term in ("revenue","profit","stock price","share price","market reaction","earnings per share")):
            return {"intent":"unsupported_financial_analysis","requires_entities":bool(entities)}
        plan={"intent":"evidence_lookup" if any(term in text for term in ("what evidence","show the evidence","why does the graph connect")) else "bounded_paths","requires_entities":True}
        if any(term in text for term in ("second-order","second order")):plan.update({"min_hops":2,"max_hops":2})
        return plan

    @staticmethod
    def _written_cutoffs(request):
        text=request.question.casefold();months={name:index for index,name in enumerate(("january","february","march","april","may","june","july","august","september","october","november","december"),1)}
        public=request.public_cutoff;knowledge=request.knowledge_cutoff;parsed=None;basis=None
        match=re.search(r"\b(?:public\s+)?by\s+("+"|".join(months)+r")\s+(\d{1,2}),\s*(\d{4})\b",text)
        if match:
            parsed=datetime(int(match.group(3)),months[match.group(1)],int(match.group(2)),23,59,59,999999,tzinfo=timezone.utc);basis="inclusive_written_public_date"
            if public is None:public=parsed
        match=re.search(r"\bbefore\s+("+"|".join(months)+r")\s+(\d{4})\b",text)
        if match:
            parsed=datetime(int(match.group(2)),months[match.group(1)],1,tzinfo=timezone.utc)-timedelta(microseconds=1);basis="exclusive_written_month"
            if "system know" in text or "system knew" in text:
                if knowledge is None:knowledge=parsed
                if public is None:public=parsed
            elif public is None:public=parsed
        return request.model_copy(update={"public_cutoff":public,"knowledge_cutoff":knowledge}),{"parsed":parsed.isoformat() if parsed else None,"basis":basis}

    @staticmethod
    def _relationship_citations(relationships):
        citations=[];seen=set()
        for edge_index,edge in enumerate(relationships,1):
            for item in edge["evidence"]:
                evidence=item["evidence"];document=item["document"];key=(edge["claim"]["id"],evidence["id"])
                if key in seen:continue
                seen.add(key);citations.append({"path":None,"edge":edge_index,"claim_revision_id":edge["claim"]["id"],"passage_id":item["passage"]["id"],
                    "quote":evidence["quote"],"assessment":evidence["assessment"],"document_id":document["id"],"accession":document["accession"],
                    "form":document["form"],"published_at":document["published_at"],"source_url":document["source_url"]})
        return citations

    def _incoming_manufacturing(self,request,entity,plan):
        graph=self.store.neighbors(NeighborRequest(entity_id=entity["id"],direction="incoming",public_cutoff=request.public_cutoff,
            knowledge_cutoff=request.knowledge_cutoff,effective_at=request.effective_at,ontology_version=request.ontology_version,identity_cutoff=request.identity_cutoff,limit=request.limit))
        relationships=[row for row in graph["relationships"] if row["claim"]["predicate"]==plan["predicate"]]
        names={row["id"]:row["canonical_name"] for row in graph["entities"]}
        findings=[{"company_id":row["resolved_subject_id"],"company":names.get(row["resolved_subject_id"],row["resolved_subject_id"]),
                   "relationship_id":row.get("relationship_id"),"predicate":row["claim"]["predicate"],
                   "manufacturer_id":row["resolved_object_id"],"manufacturer":names.get(row["resolved_object_id"],entity["canonical_name"])} for row in relationships]
        citations=self._relationship_citations(relationships)
        answer=(f"Found {len(findings)} reviewed compan{'y' if len(findings)==1 else 'ies'} with explicit contract-manufacturing relationships to {entity['canonical_name']}."
                if findings else f"No reviewed incoming contract-manufacturing relationship to {entity['canonical_name']} is eligible under the selected cutoffs.")
        return {"question":request.question,"answer":answer,"intent":"incoming_manufacturing","resolved_entities":[entity],"findings":findings,
            "paths":[],"entities":graph["entities"],"citations":citations,"verification":{"status":"supported" if findings else "no_supported_path",
            "path_count":0,"finding_count":len(findings),"citation_count":len(citations),"rule":"Every finding is an accepted positive non-inferred incoming CONTRACTS_MANUFACTURING_TO claim with supported evidence."},
            "query_plan":{"planner":"controlled_intent_v2",**plan,"target_entity_id":entity["id"],"public_cutoff":request.public_cutoff.isoformat() if request.public_cutoff else None,
            "knowledge_cutoff":request.knowledge_cutoff.isoformat() if request.knowledge_cutoff else None,"identity_cutoff":request.identity_cutoff.isoformat() if request.identity_cutoff else None,
            "effective_at":request.effective_at.isoformat() if request.effective_at else None,
            "ontology_version":graph.get("ontology_version"),"ontology_schema_hash":graph.get("ontology_schema_hash")},"generated_cypher":None,"cypher_parameters":None,
            "execution":"Authoritative relational claim selection.","limitations":"A shared manufacturer is documented connectivity, not a direct relationship among its customers or proof of economic materiality."}

    def _named_manufacturing_counterparties(self,request,entity,plan):
        common=dict(public_cutoff=request.public_cutoff,knowledge_cutoff=request.knowledge_cutoff,
            effective_at=request.effective_at,ontology_version=request.ontology_version,
            identity_cutoff=request.identity_cutoff,limit=request.limit)
        outgoing=self.store.neighbors(NeighborRequest(entity_id=entity['id'],direction='outgoing',**common))
        incoming=self.store.neighbors(NeighborRequest(entity_id=entity['id'],direction='incoming',**common))
        relationships=[row for row in outgoing['relationships'] if row['claim']['predicate']=='CONTRACTS_MANUFACTURING_TO']
        relationships += [row for row in incoming['relationships'] if row['claim']['predicate']=='SUPPLIES_TO']
        entities_by_id={row['id']:row for row in [*outgoing['entities'],*incoming['entities']]}
        findings=[]
        paths=[]
        for row in relationships:
            counterparty_id=row['resolved_object_id'] if row['claim']['predicate']=='CONTRACTS_MANUFACTURING_TO' else row['resolved_subject_id']
            findings.append({'company_id':counterparty_id,'company':entities_by_id.get(counterparty_id,{}).get('canonical_name',counterparty_id),
                'relationship_id':row.get('relationship_id'),'predicate':row['claim']['predicate'],'claim_revision_id':row['claim']['id']})
            paths.append({'entity_ids':[entity['id'],counterparty_id],'edges':[row]})
        citations=self._relationship_citations(relationships)
        return {'question':request.question,'answer':f"Found {len(findings)} reviewed manufacturing or supplier claims for {entity['canonical_name']}.",
            'intent':'named_manufacturing_counterparties','resolved_entities':[entity],'findings':findings,'paths':paths,
            'entities':list(entities_by_id.values()),'citations':citations,
            'verification':{'status':'supported' if findings else 'no_supported_path','path_count':len(paths),'finding_count':len(findings),'citation_count':len(citations),
                'rule':'Every finding is either an accepted outgoing CONTRACTS_MANUFACTURING_TO claim or an accepted incoming SUPPLIES_TO claim with supported evidence.'},
            'query_plan':{'planner':'controlled_intent_v4',**plan,'target_entity_id':entity['id'],'ontology_version':outgoing.get('ontology_version'),
                'ontology_schema_hash':outgoing.get('ontology_schema_hash')},'generated_cypher':None,'cypher_parameters':None,
            'execution':'Authoritative union of outgoing contract-manufacturing and incoming supplier claims.',
            'limitations':'Supplier and contract-manufacturing statements are reported as documented; they do not establish financial materiality.'}

    def _shared_manufacturer(self,request,entities,plan):
        selected=entities[:2];graphs=[]
        for entity in selected:
            graphs.append(self.store.neighbors(NeighborRequest(entity_id=entity["id"],direction="outgoing",public_cutoff=request.public_cutoff,
                knowledge_cutoff=request.knowledge_cutoff,effective_at=request.effective_at,ontology_version=request.ontology_version,
                identity_cutoff=request.identity_cutoff,limit=100)))
        per_company=[]
        for graph in graphs:
            per_company.append({row["resolved_object_id"]:row for row in graph["relationships"] if row["claim"]["predicate"]==plan["predicate"]})
        shared=sorted(set(per_company[0]) & set(per_company[1]))
        names={item["id"]:item["canonical_name"] for graph in graphs for item in graph["entities"]}
        findings=[];relationships=[]
        for manufacturer_id in shared[:request.limit]:
            edges=[mapping[manufacturer_id] for mapping in per_company]
            relationships.extend(edges);findings.append({"manufacturer_id":manufacturer_id,"manufacturer":names.get(manufacturer_id,manufacturer_id),
                "company_ids":[item["id"] for item in selected],"company_names":[item["canonical_name"] for item in selected],
                "relationship_ids":[edge.get("relationship_id") for edge in edges]})
        citations=self._relationship_citations(relationships)
        status="supported" if findings else "no_supported_path"
        answer=(f"Found {len(findings)} shared reviewed contract manufacturer{'s' if len(findings)!=1 else ''} for {selected[0]['canonical_name']} and {selected[1]['canonical_name']}."
                if findings else f"No shared reviewed contract manufacturer is supported for {selected[0]['canonical_name']} and {selected[1]['canonical_name']} under the selected cutoffs.")
        return {"question":request.question,"answer":answer,"intent":"shared_manufacturer","resolved_entities":selected,"findings":findings,"paths":[],
            "entities":list({item["id"]:item for graph in graphs for item in graph["entities"]}.values()),"citations":citations,
            "verification":{"status":status,"path_count":0,"finding_count":len(findings),"citation_count":len(citations),
                "rule":"Both companies must have distinct accepted outgoing CONTRACTS_MANUFACTURING_TO claims to the same resolved manufacturer."},
            "query_plan":{"planner":"controlled_intent_v3",**plan,"company_ids":[item["id"] for item in selected],
                "public_cutoff":request.public_cutoff.isoformat() if request.public_cutoff else None,"knowledge_cutoff":request.knowledge_cutoff.isoformat() if request.knowledge_cutoff else None,
                "effective_at":request.effective_at.isoformat() if request.effective_at else None,"identity_cutoff":request.identity_cutoff.isoformat() if request.identity_cutoff else None,
                "ontology_version":graphs[0].get("ontology_version"),"ontology_schema_hash":graphs[0].get("ontology_schema_hash")},
            "generated_cypher":None,"cypher_parameters":None,"execution":"Authoritative intersection of two relational neighbor sets.",
            "limitations":"A shared manufacturer establishes two documented relationships. It does not establish a direct relationship, shared demand, causality or material exposure between the two customers."}

    def _shared_counterparty_network(self,request,entity,plan):
        common=dict(public_cutoff=request.public_cutoff,knowledge_cutoff=request.knowledge_cutoff,
            effective_at=request.effective_at,ontology_version=request.ontology_version,
            identity_cutoff=request.identity_cutoff,limit=100)
        target_graph=self.store.neighbors(NeighborRequest(entity_id=entity['id'],direction='incoming',**common))
        supplier_edges=[row for row in target_graph['relationships'] if row['claim']['predicate']=='SUPPLIES_TO']
        paths=[];all_entities={row['id']:row for row in target_graph['entities']}
        for supplier_id in sorted({row['resolved_subject_id'] for row in supplier_edges}):
            supplier_graph=self.store.neighbors(NeighborRequest(entity_id=supplier_id,direction='incoming',**common))
            all_entities.update({row['id']:row for row in supplier_graph['entities']})
            development_edges=[row for row in supplier_graph['relationships'] if row['claim']['predicate']=='CONTRACTS_MANUFACTURING_TO']
            target_claims=[row for row in supplier_edges if row['resolved_subject_id']==supplier_id]
            for target_edge in target_claims:
                for development_edge in development_edges:
                    paths.append({'entity_ids':[entity['id'],supplier_id,development_edge['resolved_subject_id']],
                        'edges':[target_edge,development_edge]})
        paths=paths[:request.limit]
        relationships=[]
        for path in paths:relationships.extend(path['edges'])
        citations=self._relationship_citations(relationships)
        return {'question':request.question,'answer':f"Found {len(paths)} filing-level shared-counterparty evidence paths for {entity['canonical_name']}.",
            'intent':'shared_counterparty_network','resolved_entities':[entity],'findings':[],'paths':paths,
            'entities':list(all_entities.values()),'citations':citations,
            'verification':{'status':'supported' if paths else 'no_supported_path','path_count':len(paths),'citation_count':len(citations),
                'rule':'Each path combines one accepted supplier-to-target claim and one accepted development-company-to-same-manufacturer claim; every edge has supported evidence.'},
            'query_plan':{'planner':'controlled_intent_v4',**plan,'target_entity_id':entity['id'],
                'ontology_version':target_graph.get('ontology_version'),'ontology_schema_hash':target_graph.get('ontology_schema_hash')},
            'generated_cypher':None,'cypher_parameters':None,'execution':'Authoritative claim-level join through a shared resolved counterparty.',
            'limitations':'Each path is a pair of filing-supported claims. It does not create a direct relationship or establish economic materiality between the endpoint companies.'}

    def ask(self,request: ResearchRequest):
        request,date_parse=self._written_cutoffs(request)
        entities=self.mentioned_entities(request.question)
        plan=self.plan(request,entities)
        if plan["intent"]=="ontology_inspection":
            versions=self.store.ontology_versions()["versions"]
            return {"question":request.question,"answer":f"The active local ontology is {versions[-1]['version']}; {len(versions)} immutable versions are available.",
                "intent":"ontology_inspection","resolved_entities":[],"ontology_versions":versions,"paths":[],"entities":[],"citations":[],
                "verification":{"status":"supported","path_count":0,"citation_count":0,"rule":"Ontology metadata comes from the authoritative version store."},
                "query_plan":{"planner":"controlled_intent_v2",**plan,"ontology_version":versions[-1]["version"],"ontology_schema_hash":versions[-1]["schema_hash"]},
                "generated_cypher":None,"cypher_parameters":None,"execution":"Authoritative ontology version lookup.","limitations":"Ontology approval history is system audit evidence, not an SEC fact."}
        if not entities:raise ValueError("Question must name at least one registered company")
        if plan["intent"]=="unsupported_financial_analysis":
            return {"question":request.question,"answer":"This local research graph does not have a validated intent and comparable observation pipeline for the requested financial outcome.",
                "intent":"unsupported_financial_analysis","resolved_entities":entities,"paths":[],"entities":entities,"citations":[],
                "verification":{"status":"unsupported_intent","path_count":0,"citation_count":0,"rule":"Unsupported intents abstain instead of substituting graph connectivity."},
                "query_plan":{"planner":"controlled_intent_v3",**plan,"date_parse":date_parse},"generated_cypher":None,"cypher_parameters":None,
                "execution":"No retrieval executed.","limitations":"Use the normalized financial-observation workflow only after period/unit comparability is specified."}
        if plan["intent"] in {"licensing_neighbors","shared_licensors","licensing_paths"}:return answer_licensing(self,request,entities,plan,date_parse)
        if plan["intent"]=="incoming_manufacturing":return self._incoming_manufacturing(request,entities[0],plan)
        if plan["intent"]=="named_manufacturing_counterparties":return self._named_manufacturing_counterparties(request,entities[0],plan)
        if plan["intent"]=="shared_manufacturer":return self._shared_manufacturer(request,entities,plan)
        if plan["intent"]=="shared_counterparty_network":return self._shared_counterparty_network(request,entities[0],plan)
        source=entities[0];target=entities[1] if len(entities)>1 else None
        min_hops=plan.get("min_hops",1);max_hops=plan.get("max_hops",request.max_hops)
        graph=self.store.paths(PathRequest(source_entity_id=source['id'],target_entity_id=target['id'] if target else None,direction='both',min_hops=min_hops,max_hops=max_hops,public_cutoff=request.public_cutoff,knowledge_cutoff=request.knowledge_cutoff,effective_at=request.effective_at,ontology_version=request.ontology_version,identity_cutoff=request.identity_cutoff,limit=request.limit))
        unique={}
        for path in graph['paths']:
            key=(tuple(path['entity_ids']),tuple((edge['claim']['predicate'],edge['traversal']) for edge in path['edges']))
            if key not in unique or self._path_freshness(path)>self._path_freshness(unique[key]):unique[key]=path
        paths=list(unique.values())[:request.limit]
        citations=[];seen=set();all_supported=True
        for path_index,path in enumerate(paths,1):
            for edge_index,edge in enumerate(path['edges'],1):
                if not edge['evidence']:all_supported=False;continue
                for item in edge['evidence']:
                    evidence=item['evidence'];document=item['document']
                    if evidence['assessment']!='supported':all_supported=False
                    key=(edge['claim']['id'],evidence['id'])
                    if key in seen:continue
                    seen.add(key);citations.append({'path':path_index,'edge':edge_index,'claim_revision_id':edge['claim']['id'],'passage_id':item['passage']['id'],'quote':evidence['quote'],'assessment':evidence['assessment'],'document_id':document['id'],'accession':document['accession'],'form':document['form'],'published_at':document['published_at'],'source_url':document['source_url']})
        cypher=None;cypher_parameters=None
        if not request.knowledge_cutoff and not request.identity_cutoff:
            cypher=validate_readonly_cypher("MATCH p=(source:Entity {id: $source_id})-[:BUSINESS_RELATION*1..3]-(target:Entity) WHERE length(p) >= $min_hops AND length(p) <= $max_hops AND ($target_id IS NULL OR target.id = $target_id) AND all(r IN relationships(p) WHERE r.eligible = true AND ($public_cutoff IS NULL OR r.source_available_at <= $public_cutoff) AND ($effective_at IS NULL OR (r.valid_from IS NOT NULL AND r.valid_from <= $effective_at AND (r.valid_to IS NULL OR r.valid_to > $effective_at))) AND ($ontology_version IS NULL OR r.ontology_version = $ontology_version)) RETURN [n IN nodes(p) | properties(n)] AS nodes, [r IN relationships(p) | properties(r)] AS relationships LIMIT $limit")
            cypher_parameters={'source_id':source['id'],'target_id':target['id'] if target else None,'min_hops':min_hops,'max_hops':max_hops,'limit':request.limit,
                'public_cutoff':request.public_cutoff.isoformat() if request.public_cutoff else None,'effective_at':request.effective_at.isoformat() if request.effective_at else None,
                'ontology_version':graph.get('ontology_version')}
        if target:
            summary=f"Found {len(paths)} evidence-backed path{'s' if len(paths)!=1 else ''} between {source['canonical_name']} and {target['canonical_name']} within {max_hops} hops."
        else:summary=f"Found {len(paths)} distinct evidence-backed path{'s' if len(paths)!=1 else ''} from {source['canonical_name']} within {max_hops} hops."
        return {'question':request.question,'answer':summary,'intent':plan['intent'],'resolved_entities':entities,'paths':paths,'entities':graph['entities'],'citations':citations,'verification':{'status':'supported' if paths and all_supported else ('no_supported_path' if not paths else 'incomplete'),'path_count':len(paths),'citation_count':len(citations),'rule':'Every returned edge must be a current accepted positive non-inferred claim with supported evidence.'},'query_plan':{'planner':'controlled_intent_v3',**plan,'source_entity_id':source['id'],'target_entity_id':target['id'] if target else None,'min_hops':min_hops,'max_hops':max_hops,'date_parse':date_parse,'public_cutoff':request.public_cutoff.isoformat() if request.public_cutoff else None,'knowledge_cutoff':request.knowledge_cutoff.isoformat() if request.knowledge_cutoff else None,'effective_at':request.effective_at.isoformat() if request.effective_at else None,'identity_cutoff':request.identity_cutoff.isoformat() if request.identity_cutoff else None,'ontology_version':graph.get('ontology_version'),'ontology_schema_hash':graph.get('ontology_schema_hash')},'generated_cypher':cypher,'cypher_parameters':cypher_parameters,'execution':'Authoritative relational claim traversal. Neo4j query parity is available for current identity/current knowledge queries; historical identity or knowledge cutoffs remain relational-authority-only.','limitations':'Connectivity is documented exposure, not proof of economic materiality, causality or current contract effectiveness.'}
