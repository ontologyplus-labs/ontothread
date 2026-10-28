"""Entity-aware lexical retrieval, optional cached embeddings, and graph paths."""
import heapq
import json
import re
import math
import os
from hashlib import sha256
from pathlib import Path

import httpx

from fig.contracts import HybridRetrievalRequest,PathRequest
from fig.research import ResearchService

STOP={"the","and","for","with","what","which","who","have","has","from","that","this","our","their","within","show","companies","company"}
CONCEPT_GROUPS=(
    {"manufacturing","manufacture","foundry","foundries","fabrication","wafer","production"},
    {"capacity","constraint","constraints","shortage","shortages","bottleneck","limited"},
    {"lithography","euv","duv","scanner","scanners","equipment"},
    {"guidance","outlook","forecast","forecasts","expectation","expectations"},
    {"supplier","supplies","supply","vendor","vendors"},
    {"customer","customers","client","clients"},
)

class RetrievalService:
    def __init__(self,store):self.store=store

    @staticmethod
    def _tokens(query):
        return list(dict.fromkeys(token for token in re.findall(r"[a-z0-9][a-z0-9.-]+",query.casefold()) if len(token)>=3 and token not in STOP))[:20]

    @classmethod
    def _expanded_terms(cls,tokens):
        expanded=[]
        for token in tokens:
            for group in CONCEPT_GROUPS:
                if token in group:expanded.extend(sorted(group-{token}))
        return list(dict.fromkeys(expanded))[:30]

    def retrieve(self,request: HybridRetrievalRequest):
        entities=ResearchService(self.store).mentioned_entities(request.query)
        issuer_ids={item["id"] for item in entities if item["kind"]=="Company"}
        tokens=self._tokens(request.query)
        expanded=self._expanded_terms(tokens)
        if not tokens and not entities:raise ValueError("query needs a searchable term or registered entity")
        with self.store.connect() as conn:
            args=[]
            conditions=[]
            if issuer_ids:
                conditions.append("issuer_id IN ("+",".join("?" for _ in issuer_ids)+")");args.extend(sorted(issuer_ids))
            if request.public_cutoff:
                conditions.append("published_at<=?");args.append(request.public_cutoff.isoformat(timespec="microseconds").replace("+00:00","Z"))
            if request.knowledge_cutoff:
                conditions.append("acquired_at<=?");args.append(request.knowledge_cutoff.isoformat(timespec="microseconds").replace("+00:00","Z"))
            where=" WHERE "+" AND ".join(conditions) if conditions else ""
            documents=self.store.execute(conn,"SELECT id,payload FROM document"+where+" ORDER BY published_at DESC,id LIMIT ?",(*args,request.document_limit)).fetchall()
            heap=[];serial=0;heap_limit=min(50,max(request.passage_limit*5,20)) if request.use_embeddings else request.passage_limit
            phrase=request.query.casefold()
            for document_row in documents:
                document=json.loads(document_row["payload"])
                versions=self.store.execute(conn,"SELECT id,normalized_text FROM text_version WHERE document_id=? ORDER BY id",(document_row["id"],)).fetchall()
                for version in versions:
                    rows=self.store.execute(conn,"SELECT payload FROM passage WHERE text_version_id=? ORDER BY start_offset",(version["id"],)).fetchall()
                    for row in rows:
                        passage=json.loads(row["payload"]);text=version["normalized_text"][passage["start_offset"]:passage["end_offset"]];lower=text.casefold()
                        present=[token for token in tokens if token in lower];semantic=[term for term in expanded if term in lower]
                        if not present and not semantic and phrase not in lower:continue
                        coverage=len(present)/max(1,len(tokens))
                        frequency=sum(min(3,lower.count(token)) for token in present)/max(1,len(tokens)*3)
                        semantic_score=min(1,len(semantic)/max(1,len(expanded)))
                        score=3*coverage+frequency+semantic_score+(4 if phrase in lower else 0)
                        item={"score":round(score,6),"passage_id":passage["id"],"document_id":document["id"],"issuer_id":document["issuer_id"],"form":document["form"],"published_at":document["published_at"],"accession":document["accession"],"source_url":document["source_url"],"section_path":passage["section_path"],"text":text,"matched_terms":present,"matched_expansions":semantic}
                        serial+=1;entry=(score,serial,item)
                        if len(heap)<heap_limit:heapq.heappush(heap,entry)
                        elif score>heap[0][0]:heapq.heapreplace(heap,entry)
        passages=[item for _,_,item in sorted(heap,key=lambda entry:(-entry[0],entry[1]))]
        embedding_metadata=None
        if request.use_embeddings and passages:
            candidate_count=min(50,max(request.passage_limit*5,20))
            candidates=passages[:candidate_count]
            embedder=OpenAIEmbedder()
            vectors,embedding_metadata=embedder.embed([request.query,*[item["text"] for item in candidates]])
            query_vector=vectors[0]
            for item,vector in zip(candidates,vectors[1:]):
                similarity=sum(a*b for a,b in zip(query_vector,vector))
                item["embedding_score"]=round(similarity,6)
                item["combined_score"]=round(.65*similarity+.35*min(1,item["score"]/8),6)
            passages=sorted(candidates,key=lambda item:(-item["combined_score"],-item["score"],item["passage_id"]))[:request.passage_limit]
        else:passages=passages[:request.passage_limit]
        graph=None
        companies=[entity for entity in entities if entity["kind"]=="Company"]
        if companies:
            graph=self.store.paths(PathRequest(source_entity_id=companies[0]["id"],target_entity_id=companies[1]["id"] if len(companies)>1 else None,
                direction="both",max_hops=3,limit=request.graph_limit,public_cutoff=request.public_cutoff,knowledge_cutoff=request.knowledge_cutoff,
                effective_at=request.effective_at,ontology_version=request.ontology_version,identity_cutoff=request.identity_cutoff))
        return {"query":request.query,"resolved_entities":entities,"query_terms":tokens,"semantic_expansions":expanded,"passages":passages,"graph":graph,
                "method":"transparent ontology-aware query expansion, lexical ranking and authoritative evidence-backed graph traversal",
                "temporal_scope":{"public_cutoff":request.public_cutoff.isoformat() if request.public_cutoff else None,"knowledge_cutoff":request.knowledge_cutoff.isoformat() if request.knowledge_cutoff else None,
                    "effective_at":request.effective_at.isoformat() if request.effective_at else None,"identity_cutoff":request.identity_cutoff.isoformat() if request.identity_cutoff else None},
                "semantic_expansion_used":bool(expanded),
                "semantic_embeddings_used":bool(request.use_embeddings and passages),"embedding_metadata":embedding_metadata,
                "limitations":"Embedding reranking is used only when explicitly requested and does not establish factual support; graph connectivity does not establish materiality." if request.use_embeddings else "Controlled semantic expansion is inspectable and uses no neural embeddings; graph connectivity does not establish materiality."}


class OpenAIEmbedder:
    """Content-addressed embeddings; the API key is sent only to OpenAI."""
    def __init__(self,*,key=None,model=None,dimensions=256,cache_dir=None,transport=None,offline_only=None):
        self.key=key or os.getenv("OPENAI_API_KEY");self.model=model or os.getenv("FIG_EMBEDDING_MODEL","text-embedding-3-small")
        self.dimensions=dimensions;self.cache=Path(cache_dir or os.getenv("FIG_EMBEDDING_CACHE_DIR","data/embedding-cache"));self.transport=transport
        self.offline_only=(os.getenv("FIG_EMBEDDING_OFFLINE_ONLY")=="1") if offline_only is None else offline_only
        if not self.key and not self.offline_only:raise ValueError("OPENAI_API_KEY is required when use_embeddings=true")

    def embed(self,texts):
        if not texts or any(not text.strip() for text in texts):raise ValueError("embedding inputs must be nonempty")
        self.cache.mkdir(parents=True,exist_ok=True);vectors=[None]*len(texts);missing=[]
        for index,text in enumerate(texts):
            bounded=text[:24000];key=sha256((self.model+":"+str(self.dimensions)+":"+bounded).encode()).hexdigest();path=self.cache/(key+".json")
            if path.exists():vectors[index]=json.loads(path.read_text())["embedding"]
            else:missing.append((index,bounded,path))
        usage={"prompt_tokens":0,"total_tokens":0};requests=0
        if missing:
            if self.offline_only:raise RuntimeError(f"Offline embedding cache is missing {len(missing)} input(s); no API request was made")
            payload={"model":self.model,"input":[item[1] for item in missing],"encoding_format":"float","dimensions":self.dimensions}
            with httpx.Client(timeout=90,transport=self.transport) as client:
                response=client.post("https://api.openai.com/v1/embeddings",headers={"Authorization":"Bearer "+self.key},json=payload)
            if response.status_code!=200:raise RuntimeError(f"Embedding API failed with HTTP {response.status_code}")
            data=response.json();requests=1;usage=data.get("usage",usage)
            ordered=sorted(data["data"],key=lambda item:item["index"])
            if len(ordered)!=len(missing):raise RuntimeError("Embedding API returned the wrong vector count")
            for (index,_,path),item in zip(missing,ordered):
                vector=item["embedding"];magnitude=math.sqrt(sum(value*value for value in vector))
                if not magnitude:raise RuntimeError("Embedding API returned a zero vector")
                vector=[value/magnitude for value in vector];vectors[index]=vector
                temporary=path.with_suffix(".tmp");temporary.write_text(json.dumps({"model":self.model,"dimensions":self.dimensions,"embedding":vector}));temporary.replace(path)
        return vectors,{"model":self.model,"dimensions":self.dimensions,"request_count":requests,"cache_hits":len(texts)-len(missing),"cache_misses":len(missing),"usage":usage}
