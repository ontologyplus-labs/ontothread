"""Reproducible, read-only extraction benchmark; never accepts graph claims."""
from collections import Counter
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import UUID,uuid5,NAMESPACE_URL

from pydantic import BaseModel,ConfigDict,Field,model_validator
from fig.contracts import Entity
from fig.extraction import Proposal,Output,RulesExtractor,OpenAIExtractor,ExtractionError,PROMPT,normalized,validated_output

class Gold(BaseModel):
    model_config=ConfigDict(extra='forbid')
    counterparty_name: str
    subject_is_issuer: bool
    predicate: str
    supporting_quote: str

class Source(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_id: UUID
    passage_id: UUID
    text_version_id: UUID
    content_hash: str
    source_url: str
    start_offset: int=Field(ge=0)
    end_offset: int

class Case(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str
    issuer_name: str
    text: str=Field(min_length=1,max_length=16000)
    text_hash: str
    category: str
    annotation_notes: str
    expected: list[Gold]
    source: Source

    @model_validator(mode='after')
    def validate_case(self):
        if sha256(self.text.encode()).hexdigest()!=self.text_hash:raise ValueError('Benchmark text checksum mismatch')
        if self.source.end_offset-self.source.start_offset!=len(self.text):raise ValueError('Benchmark span length mismatch')
        for edge in self.expected:
            Proposal(counterparty_name=edge.counterparty_name,subject_is_issuer=edge.subject_is_issuer,predicate=edge.predicate,quote=edge.supporting_quote,rationale='Gold source annotation')
            if self.text.count(edge.supporting_quote)!=1 or edge.counterparty_name not in edge.supporting_quote:raise ValueError('Gold quote/name not uniquely present in source text')
        if len({key(e) for e in self.expected})!=len(self.expected):raise ValueError('Duplicate gold edge')
        return self

class Dataset(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version: str
    annotation_author: str
    annotation_status: str
    created_at: str
    policy: dict
    cases: list[Case]=Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def unique_cases(self):
        if len({c.id for c in self.cases})!=len(self.cases):raise ValueError('Duplicate benchmark case IDs')
        return self

def key(edge):
    name=re.sub(r'\s*\([A-Z0-9.&-]{2,16}\)\s*$','',edge.counterparty_name.strip())
    return (normalized(name),edge.predicate,edge.subject_is_issuer)

def verify_sources(dataset,store):
    for case in dataset.cases:
        parent=store.passage(case.source.passage_id)
        start=case.source.start_offset-parent['start_offset'];end=case.source.end_offset-parent['start_offset']
        if start<0 or end>len(parent['text']) or parent['text'][start:end]!=case.text:raise ValueError('Benchmark excerpt differs from the ingested source')
        if parent['document']['id']!=str(case.source.document_id) or parent['text_version_id']!=str(case.source.text_version_id) or parent['document']['content_hash']!=case.source.content_hash:raise ValueError('Benchmark source lineage mismatch')


def score_case(case,output):
    gold={key(e):e for e in case.expected};remaining=set(gold);supported=set();matched=set();fp=[];invalid=[];wrong_direction=0;identity_errors=0;duplicates=0;seen=set()
    for proposal in output.candidates:
        triple=key(proposal)
        if triple in seen:duplicates+=1
        seen.add(triple)
        valid=bool(proposal.quote) and case.text.count(proposal.quote)==1 and proposal.counterparty_name in proposal.quote
        if not valid:invalid.append(proposal.model_dump())
        if triple in remaining:
            remaining.remove(triple);matched.add(triple)
            if valid and gold[triple].supporting_quote in proposal.quote:supported.add(triple)
        else:
            fp.append(proposal.model_dump())
            if any(t[:2]==triple[:2] and t[2]!=triple[2] for t in gold):wrong_direction+=1
            if gold and not any(t[0]==triple[0] for t in gold):identity_errors+=1
    return {'tp':len(matched),'fp':len(fp),'fn':len(remaining),'supported_tp':len(supported),'predicted':len(output.candidates),'expected':len(gold),'invalid_quotes':len(invalid),'wrong_direction':wrong_direction,'identity_errors':identity_errors,'duplicate_predictions':duplicates,'negative_case':not bool(gold),'negative_correct':not gold and not output.candidates,'false_positives':fp,'missing_edges':[gold[t].model_dump() for t in sorted(remaining)],'invalid_evidence':invalid}

def metrics(rows):
    if not rows:return None
    counts=Counter()
    for row in rows:
        for field in ['tp','fp','fn','supported_tp','predicted','expected','invalid_quotes','wrong_direction','identity_errors','duplicate_predictions']:
            counts[field]+=row['score'][field]
    precision=counts['tp']/counts['predicted'] if counts['predicted'] else None
    recall=counts['tp']/counts['expected'] if counts['expected'] else None
    f1=2*counts['tp']/(2*counts['tp']+counts['fp']+counts['fn']) if (2*counts['tp']+counts['fp']+counts['fn']) else None
    negative=[r for r in rows if r['score']['negative_case']]
    return {**counts,'precision':precision,'recall':recall,'f1':f1,'evidence_supported_precision':counts['supported_tp']/counts['predicted'] if counts['predicted'] else None,'negative_cases':len(negative),'negative_case_accuracy':sum(r['score']['negative_correct'] for r in negative)/len(negative) if negative else None}


def evaluate(dataset,provider,cache_dir,*,extractor=None,limit=None):
    # Labels never go into the extraction prompt. No database writes are performed.
    extractor=extractor or (RulesExtractor() if provider=='rules' else OpenAIExtractor())
    ontology=getattr(extractor,'ontology',None)
    cases=dataset.cases[:limit] if limit else dataset.cases
    dataset_hash=sha256(dataset.model_dump_json().encode()).hexdigest()
    cache_dir=Path(cache_dir);cache_dir.mkdir(parents=True,exist_ok=True)
    rows=[];failure=None
    for case in cases:
        issuer=Entity(id=uuid5(NAMESPACE_URL,'fig:eval:issuer:'+case.issuer_name),kind='Company',canonical_name=case.issuer_name,slug='benchmark-issuer')
        schema=Output.model_json_schema()
        if ontology:
            allowed=sorted(name for name,rule in ontology.definitions.get('predicates',{}).items()
                           if 'Company' in rule.get('subject',[]) and 'Company' in rule.get('object',[]))
            schema['$defs']['Proposal']['properties']['predicate']['enum']=allowed
        cache_key=sha256(json.dumps({'dataset':dataset_hash,'case':case.id,'provider':provider,'model':extractor.model,'prompt':PROMPT,
                                     'schema':schema,'ontology_version':getattr(ontology,'version',None),
                                     'ontology_schema_hash':getattr(ontology,'schema_hash',None)},sort_keys=True).encode()).hexdigest()
        cache=cache_dir/(cache_key+'.json');cached=cache.exists()
        try:
            if cached:
                record=json.loads(cache.read_text());output=Output.model_validate(record['output']);metadata=record['metadata']
            else:
                output,metadata=extractor.extract({'text':case.text},issuer)
                if len(output.candidates)>20:raise ExtractionError('Extraction exceeded 20 candidates.')
                record={'cache_key':cache_key,'case_id':case.id,'output':output.model_dump(),'metadata':metadata}
                temporary=cache.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2));temporary.replace(cache)
            filtered,validation_errors=validated_output(output,case.text,case.issuer_name,ontology)
            rows.append({'case_id':case.id,'category':case.category,'cached':cached,
                         'raw_output':output.model_dump(),'output':filtered.model_dump(),
                         'validation_errors':validation_errors,'metadata':metadata,
                         'score':score_case(case,filtered)})
        except ExtractionError as error:
            failure={'case_id':case.id,'code':error.code,'http_status':error.status,'message':str(error)}
            break # Provider failures are never interpreted as an empty successful result.
    groups={}
    for row in rows:groups.setdefault(row['category'],[]).append(row)
    return {'dataset':dataset.version,'dataset_hash':dataset_hash,'annotation_author':dataset.annotation_author,'annotation_status':dataset.annotation_status,'provider':provider,'model':extractor.model,
            'ontology_version':getattr(ontology,'version',None),'ontology_schema_hash':getattr(ontology,'schema_hash',None),
            'prompt_hash':sha256(PROMPT.encode()).hexdigest(),'schema_hash':sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),'generated_at':datetime.now(timezone.utc).isoformat(),'status':'failed' if failure else 'completed','requested_cases':len(cases),'completed_cases':len(rows),'coverage':len(rows)/len(cases),'dataset_expected_edges':sum(len(c.expected) for c in cases),'raw_candidate_count':sum(len(r['raw_output']['candidates']) for r in rows),'admissible_candidate_count':sum(len(r['output']['candidates']) for r in rows),'validation_rejection_count':sum(len(r['validation_errors']) for r in rows),'metrics':metrics(rows),'category_metrics':{name:metrics(items) for name,items in groups.items()},'failure':failure,'results':rows,'limitations':dataset.policy['grouping']+' '+dataset.annotation_status+'. Scores describe only candidates that passed deterministic validation in completed cases; raw outputs and rejection reasons are retained. Quote containment is stricter than semantic equivalence.'}


def write_report(report,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    summary=['# Extraction evaluation','',f"Provider: {report['provider']} · model: {report['model']}",f"Status: {report['status']} · cases completed: {report['completed_cases']}/{report['requested_cases']}",'',report['limitations'],'']
    if report['failure']:summary+=['Failure: '+report['failure']['message'],'Error code: '+str(report['failure']['code']),'']
    if report['metrics']:
        summary+=['| Metric | Value |','| --- | --- |']
        for name,value in report['metrics'].items():summary.append(f'| {name} | {value:.4f} |' if isinstance(value,float) else f'| {name} | {value} |')
    else:summary+=['No model-quality metrics are available because no cases completed.']
    path.with_suffix('.md').write_text('\n'.join(summary)+'\n')
