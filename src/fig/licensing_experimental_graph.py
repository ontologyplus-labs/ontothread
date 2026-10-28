"""Isolated SQLite evidence graphs; no access to the application database."""
from datetime import datetime,timezone
from hashlib import sha256
import json,sqlite3
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
from fig.research import ResearchService

def identity(name):return str(uuid5(NAMESPACE_URL,'licensing-study-entity:'+name))
class ExperimentalGraph:
    def __init__(self,path,version=None,definition=None):
        self.path=Path(path)
        if version is not None:
            if self.path.exists():raise ValueError('experimental graph already exists')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(self.path) as c:
                c.executescript('CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT); CREATE TABLE entities (id TEXT PRIMARY KEY,name TEXT UNIQUE); CREATE TABLE edges (id TEXT PRIMARY KEY,payload TEXT);')
                c.executemany('INSERT INTO metadata VALUES (?,?)',[('version',version),('definition',json.dumps(definition)),('created_at',datetime.now(timezone.utc).isoformat())])
        with sqlite3.connect(self.path) as c:self.meta=dict(c.execute('SELECT key,value FROM metadata'))
        self.definitions=json.loads(self.meta['definition'])
    def supports_predicate(self,predicate,version):return version==self.meta['version'] and predicate in self.definitions['predicates']
    def ontology_versions(self):return {'versions':[{'version':self.meta['version'],'definitions':self.definitions}]}
    def add_cases(self,cases,outputs=None):
        with sqlite3.connect(self.path) as conn:
            for case in cases:
                conn.execute('INSERT OR IGNORE INTO entities VALUES (?,?)',(identity(case['issuer']),case['issuer']))
                edges=case['expected_edges'] if outputs is None else [a['edge']|{'start':a['evidence']['start'],'end':a['evidence']['end']} for a in outputs.get(case['passage_id'],{}).get('anchored_edges',[])]
                for edge in edges:
                    if edge['predicate'] not in self.definitions['predicates']:continue
                    quote=edge['quote'];start,end=edge['start'],edge['end']
                    if case['text'][start:end]!=quote:raise ValueError('graph evidence is not source exact')
                    subject,object=edge['subject_name'],edge['object_name'];sid,oid=identity(subject),identity(object)
                    conn.executemany('INSERT OR IGNORE INTO entities VALUES (?,?)',[(sid,subject),(oid,object)])
                    eid=str(uuid5(NAMESPACE_URL,case['passage_id']+':'+subject+':'+edge['predicate']+':'+object))
                    source_date=case.get('published_at',case.get('filing_date'));relation_id=str(uuid5(NAMESPACE_URL,subject+':'+edge['predicate']+':'+object))
                    data={'claim':{'id':eid,'subject_id':sid,'object_id':oid,'predicate':edge['predicate'],'knowledge_at':self.meta['created_at'],'valid_from':edge.get('valid_from'),'valid_to':edge.get('valid_to'),'modality':edge.get('modality',case.get('temporal_scope'))},'relationship_id':relation_id,'resolved_subject_id':sid,'resolved_object_id':oid,'evidence':[{'evidence':{'id':eid,'quote':quote,'assessment':'supported','start':start,'end':end,'source_text_hash':case['text_hash']},'passage':{'id':case['passage_id']},'document':{'id':case['accession'],'accession':case['accession'],'form':case.get('form','unknown'),'published_at':source_date,'source_url':case['source_url']}}],'provenance':'experimental_reference' if outputs is None else 'experimental_prediction; not accepted application claim','ontology_version':self.meta['version']}
                    conn.execute('INSERT OR IGNORE INTO edges VALUES (?,?)',(eid,json.dumps(data)))
    def entities(self):
        with sqlite3.connect(self.path) as c:return [{'id':id,'kind':'Company','canonical_name':name} for id,name in c.execute('SELECT id,name FROM entities ORDER BY name')]
    def edges(self,request):
        if request.ontology_version and request.ontology_version!=self.meta['version']:return []
        with sqlite3.connect(self.path) as c:rows=[json.loads(r[0]) for r in c.execute('SELECT payload FROM edges ORDER BY id')]
        eligible=[]
        for r in rows:
            claim=r['claim'];date=r['evidence'][0]['document']['published_at'];public=datetime.fromisoformat(date.replace('Z','+00:00'))
            if public.tzinfo is None:public=public.replace(tzinfo=timezone.utc)
            if request.public_cutoff and public>request.public_cutoff:continue
            if request.knowledge_cutoff and datetime.fromisoformat(claim['knowledge_at'])>request.knowledge_cutoff:continue
            if request.identity_cutoff and datetime.fromisoformat(self.meta['created_at'])>request.identity_cutoff:continue
            if request.effective_at:
                if not claim['valid_from']:continue
                if datetime.fromisoformat(claim['valid_from'])>request.effective_at:continue
                if claim['valid_to'] and datetime.fromisoformat(claim['valid_to'])<=request.effective_at:continue
            eligible.append(r)
        return eligible
    def _envelope(self):return {'entities':self.entities(),'ontology_version':self.meta['version'],'ontology_schema_hash':sha256(json.dumps(self.definitions,sort_keys=True).encode()).hexdigest()}
    def neighbors(self,request):
        id=str(request.entity_id);rows=[r for r in self.edges(request) if request.direction in {'both','outgoing'} and r['resolved_subject_id']==id or request.direction in {'both','incoming'} and r['resolved_object_id']==id]
        return {**self._envelope(),'relationships':rows[:request.limit],'truncated':len(rows)>request.limit}
    def paths(self,request):
        rows=self.edges(request);paths=[];start=str(request.source_entity_id);target=str(request.target_entity_id) if request.target_entity_id else None
        def walk(nodes,edges):
            if request.min_hops<=len(edges)<=request.max_hops and (not target or nodes[-1]==target):paths.append({'entity_ids':nodes,'edges':edges})
            if len(edges)>=request.max_hops:return
            for r in rows:
                s,o=r['resolved_subject_id'],r['resolved_object_id'];nextnode=o if s==nodes[-1] and request.direction in {'both','outgoing'} else s if o==nodes[-1] and request.direction in {'both','incoming'} else None
                if nextnode and nextnode not in nodes:walk(nodes+[nextnode],edges+[r])
        walk([start],[])
        # Collapse repeated disclosures to stable relationship paths, retaining evidence in rows.
        unique={}
        for p in paths:unique.setdefault((tuple(p['entity_ids']),tuple(r['relationship_id'] for r in p['edges'])),p)
        return {**self._envelope(),'paths':list(unique.values())[:request.limit]}
class ExperimentalResearchService(ResearchService):
    def mentioned_entities(self,question):
        matches=[e for e in self.store.entities() if e['canonical_name'].casefold() in question.casefold()]
        return sorted(matches,key=lambda e:question.casefold().find(e['canonical_name'].casefold()))
