import json
from datetime import datetime,timezone
from pathlib import Path
from fig.contracts import HybridRetrievalRequest
from fig.retrieval import RetrievalService

def _relevant(passage,phrases):
    lower=passage["text"].casefold()
    return all(phrase.casefold() in lower for phrase in phrases)

def evaluate_retrieval(store,dataset_path):
    dataset=json.loads(Path(dataset_path).read_text());service=RetrievalService(store);rows=[]
    for case in dataset["cases"]:
        modes=[]
        for use_embeddings in (False,True):
            result=service.retrieve(HybridRetrievalRequest(query=case["query"],document_limit=50,passage_limit=50,graph_limit=5,use_embeddings=use_embeddings))
            pool=result["passages"][:50];top=pool[:10]
            candidate_ranks=[index for index,passage in enumerate(pool,1) if _relevant(passage,case["expected_phrases"])]
            ranks=[index for index,passage in enumerate(top,1) if _relevant(passage,case["expected_phrases"])]
            modes.append({"mode":"embedding_rerank" if use_embeddings else "lexical_rank","candidate_pool_size":len(pool),
                "candidate_generation_hit":1 if candidate_ranks else 0,"candidate_relevant_ranks":candidate_ranks,
                "relevant_ranks":ranks,"recall_at_10":1 if ranks else 0,"reciprocal_rank":1/min(ranks) if ranks else 0,
                "top_passage_ids":[p["passage_id"] for p in top],"graph_path_available":bool(result.get("graph",{}).get("paths")),
                "embedding_metadata":result.get("embedding_metadata")})
        rows.append({**case,"results":modes})
    summary={}
    for mode_index,name in enumerate(("lexical_rank","embedding_rerank")):
        values=[row["results"][mode_index] for row in rows]
        summary[name]={"candidate_generation_hit_rate":sum(v["candidate_generation_hit"] for v in values)/len(values),
            "recall_at_10":sum(v["recall_at_10"] for v in values)/len(values),"mean_reciprocal_rank":sum(v["reciprocal_rank"] for v in values)/len(values),"candidate_pool_limit":50}
    return {"dataset":dataset["version"],"generated_at":datetime.now(timezone.utc).isoformat(),"case_count":len(rows),"summary":summary,"cases":rows,
        "comparison_scope":"Matched reranking comparison over an identical lexical candidate pool.",
        "dense_corpus_retrieval":{"status":"not_run","reason":"Embeddings do not index the full corpus; this report makes no dense-retrieval superiority claim."},
        "limitations":"Phrase labels verify retrieval of specific known passages. Candidate-generation misses and top-ten ranking misses are separate. Embedding reranking is not corpus-wide dense retrieval."}
