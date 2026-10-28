from fig.retrieval_evaluation import _relevant
import json

def test_retrieval_relevance_requires_all_frozen_phrases():
    passage={"text":"We utilize foundries such as TSMC and Samsung."}
    assert _relevant(passage,["utilize foundries","TSMC","Samsung"])
    assert not _relevant(passage,["utilize foundries","ASML"])

def test_matched_pool_reports_candidate_and_ranking_misses(tmp_path,monkeypatch):
    import fig.retrieval_evaluation as module
    class Service:
        def __init__(self,store):pass
        def retrieve(self,request):
            passages=[{"passage_id":str(i),"text":"target phrase" if i==20 else "other"} for i in range(50)]
            if request.use_embeddings:passages.insert(0,passages.pop(20))
            return {"passages":passages,"graph":{"paths":[]},"embedding_metadata":{"request_count":0} if request.use_embeddings else None}
    monkeypatch.setattr(module,"RetrievalService",Service)
    dataset=tmp_path/"queries.json";dataset.write_text(json.dumps({"version":"v1","cases":[{"id":"q","query":"test query","expected_phrases":["target phrase"]}]}))
    report=module.evaluate_retrieval(object(),dataset)
    assert report["summary"]["lexical_rank"]["candidate_generation_hit_rate"]==1
    assert report["summary"]["lexical_rank"]["recall_at_10"]==0
    assert report["summary"]["embedding_rerank"]["recall_at_10"]==1
    assert report["dense_corpus_retrieval"]["status"]=="not_run"
