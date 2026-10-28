from fastapi.testclient import TestClient
from fig.api import create_app
from fig.config import Settings
from fig.fixture import fixture
from fig.store import Store
import fig.retrieval as retrieval_module

def test_entity_aware_hybrid_retrieval_returns_source_and_graph(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"retrieval.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();bundle,original=fixture()
    data=bundle.model_dump(mode="json");data["entities"][0]["slug"]="sec-cik-1045810"
    from fig.contracts import ReviewedBundle
    bundle=ReviewedBundle.model_validate(data);store.ingest(bundle,original,settings.archive_dir);store.seed_core_registry()
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/retrieval/hybrid",json={"query":"NVDA manufacturing evidence","passage_limit":5})
    assert response.status_code==200
    body=response.json()
    assert body["resolved_entities"][0]["canonical_name"]==bundle.entities[0].canonical_name
    assert body["passages"][0]["passage_id"]==str(bundle.passage.id)
    assert len(body["graph"]["paths"])==1
    assert body["semantic_embeddings_used"] is False
    assert body["semantic_expansion_used"] is True and "foundry" in body["semantic_expansions"]

def test_embedding_reranking_is_explicit_and_disclosed(tmp_path,monkeypatch):
    settings=Settings("sqlite:///"+str(tmp_path/"embedding.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();bundle,original=fixture();store.ingest(bundle,original,settings.archive_dir)
    class RecordedEmbedder:
        def embed(self,texts):
            return [[1.0,0.0]]+[[1.0,0.0] for _ in texts[1:]],{"model":"recorded","dimensions":2,"request_count":0,"cache_hits":len(texts),"cache_misses":0,"usage":{"total_tokens":0}}
    monkeypatch.setattr(retrieval_module,"OpenAIEmbedder",RecordedEmbedder)
    result=retrieval_module.RetrievalService(store).retrieve(retrieval_module.HybridRetrievalRequest(query="manufacturing evidence",use_embeddings=True))
    assert result["semantic_embeddings_used"] is True
    assert result["embedding_metadata"]["model"]=="recorded"
    assert result["passages"][0]["embedding_score"]==1.0

def test_embedding_offline_only_fails_before_network_on_cache_miss(tmp_path):
    from fig.retrieval import OpenAIEmbedder
    embedder=OpenAIEmbedder(key=None,cache_dir=tmp_path,offline_only=True)
    import pytest
    with pytest.raises(RuntimeError,match="no API request was made"):embedder.embed(["uncached text"])

def test_hybrid_retrieval_applies_same_temporal_scope_to_passages_and_graph(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"temporal-retrieval.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();bundle,original=fixture()
    data=bundle.model_dump(mode="json");data["entities"][0]["slug"]="sec-cik-1045810"
    from fig.contracts import ReviewedBundle
    bundle=ReviewedBundle.model_validate(data);store.ingest(bundle,original,settings.archive_dir);store.seed_core_registry()
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/retrieval/hybrid",json={"query":"NVDA manufacturing evidence","public_cutoff":"2020-01-01T00:00:00Z","knowledge_cutoff":"2020-01-01T00:00:00Z"})
    assert response.status_code==200
    body=response.json()
    assert body["passages"]==[] and body["graph"]["paths"]==[]
    assert body["temporal_scope"]["public_cutoff"].startswith("2020-01-01")
