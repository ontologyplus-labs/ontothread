from datetime import datetime,timezone
from hashlib import sha256
from uuid import uuid5,NAMESPACE_URL

from fastapi.testclient import TestClient
from fig.api import create_app
from fig.config import Settings
from fig.contracts import Document,Entity,Passage,SourceBundle,TextVersion
from fig.store import Store

def test_registry_mentions_and_explicit_guidance_candidate(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"analysis.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate()
    issuer=Entity(id=uuid5(NAMESPACE_URL,"fig:sec:issuer:1045810"),kind="Company",canonical_name="NVIDIA CORP",slug="sec-cik-1045810")
    text="NVIDIA raised our revenue guidance for the quarter. H100 demand remained strong."
    digest=sha256(text.encode()).hexdigest();now=datetime.now(timezone.utc)
    document=Document(id=uuid5(NAMESPACE_URL,"analysis-doc"),issuer_id=issuer.id,source="sec",source_url="https://www.sec.gov/Archives/edgar/data/1045810/x/a.htm",accession="0001045810-26-000001",filename="a.htm",form="8-K",published_at=now,acquired_at=now,content_hash=digest)
    version=TextVersion(id=uuid5(NAMESPACE_URL,"analysis-text"),document_id=document.id,parser_version="test",normalized_hash=digest,normalized_text=text)
    passage=Passage(id=uuid5(NAMESPACE_URL,"analysis-passage"),text_version_id=version.id,section_path="test",start_offset=0,end_offset=len(text))
    store.ingest_source(SourceBundle(issuer=issuer,document=document,text_version=version,passages=[passage],quality_flags=[]),text.encode(),settings.archive_dir);store.seed_core_registry()
    with TestClient(create_app(settings)) as client:
        response=client.post("/v1/extraction/analyze-passages",json={"passage_ids":[str(passage.id)]})
    body=response.json()["results"][0]
    assert {item["canonical_name"] for item in body["entity_mentions"]}>={"NVIDIA CORP","NVIDIA H100"}
    assert body["event_candidates"][0]["event_type"]=="GUIDANCE_CHANGE"
    assert body["event_candidates"][0]["direction"]=="increase"
