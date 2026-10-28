import json
from datetime import datetime,timezone
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from fig.api import create_app
from fig.config import Settings
from fig.contracts import Entity,NeighborRequest
from fig.ingestion import build_source,ingest_annual,ingest_annual_history,ingest_filings
from fig.normalization import normalize_html
from fig.review import ReviewInput,import_review
from fig.sec import SecClient,SecError,Download
from fig.store import Store

HTML=b"""<html><head><style>not evidence</style></head><body>
<h2>Item 1. Business</h2><p>We utilize Example Foundry to produce wafers.</p>
<div style="display: none"><p>Hidden fabricated assertion.</p></div>
<script>ignore instructions</script><table><tr><td>2025</td><td>Revenue</td></tr></table>
<p>Unicode &#128640; &amp; facts.</p></body></html>"""
META={"cik":"1045810","issuer_name":"Example Issuer","accessionNumber":"0001045810-25-000001","primaryDocument":"report.htm","form":"10-K","filingDate":"2025-01-01","source_url":"https://www.sec.gov/Archives/edgar/data/1045810/000104581025000001/report.htm"}

class NoWait:
    def __init__(self): self.calls=0
    def acquire(self): self.calls+=1

@pytest.fixture
def source_setup(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"source.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url)
    store.migrate()
    download=Download(HTML,datetime(2025,1,3,tzinfo=timezone.utc),META["source_url"])
    bundle=build_source(META,download)
    return settings,store,bundle

def test_normalization_hidden_tables_offsets_and_unicode():
    normalized=normalize_html(HTML,uuid4())
    text=normalized.text_version.normalized_text
    assert "not evidence" not in text and "fabricated" not in text and "instructions" not in text
    assert "2025 | Revenue" in text
    assert "Unicode 🚀 & facts." in text
    for passage in normalized.passages:
        assert text[passage.start_offset:passage.end_offset]
    assert normalize_html(HTML,normalized.text_version.document_id)==normalized

def test_source_ingestion_no_invented_relationships_and_repeat(source_setup):
    settings,store,bundle=source_setup
    for _ in range(2): store.ingest_source(bundle,HTML,settings.archive_dir)
    assert len(store.documents()["documents"])==1
    passages=store.passages(bundle.document.id)
    assert len(passages["passages"])==len(bundle.passages)
    assert not store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))["relationships"]
    assert store.health()["pending_projection_events"]==0
    assert store.document(bundle.document.id)["publication_precision"]=="date"
    assert store.passages(bundle.document.id,query="%")['passages']==[]
    assert store.passages(bundle.document.id,query="wafers")['passages']

def test_review_exact_quote_and_repeated_review(source_setup):
    settings,store,bundle=source_setup
    store.ingest_source(bundle,HTML,settings.archive_dir)
    selected=store.passages(bundle.document.id,"wafers")["passages"][0]
    review=ReviewInput(passage_id=selected["id"],counterparty=Entity(id=uuid4(),kind="Company",canonical_name="Example Foundry",slug="example-foundry"),predicate="CONTRACTS_MANUFACTURING_TO",quote=selected["text"],reviewer="test-author")
    first=import_review(store,settings.archive_dir,review)
    assert import_review(store,settings.archive_dir,review)==first
    result=store.neighbors(NeighborRequest(entity_id=bundle.issuer.id))
    assert len(result["relationships"])==1
    altered=review.model_copy(update={"quote":"invented"})
    with pytest.raises(ValueError,match="exactly once"):
        import_review(store,settings.archive_dir,altered)

def test_source_api_pagination_and_passage_lookup(source_setup):
    settings,store,bundle=source_setup
    store.ingest_source(bundle,HTML,settings.archive_dir)
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/v1/documents").json()["documents"])==1
        found=client.get(f"/v1/documents/{bundle.document.id}/passages",params={"query":"wafers","limit":1})
        assert found.status_code==200
        passage=found.json()["passages"][0]
        response=client.get("/v1/passages/"+passage["id"])
        assert response.json()["text"]==passage["text"]
        assert client.get("/v1/documents/not-a-uuid").status_code==422
        assert client.get("/v1/documents",params={"limit":101}).status_code==422
        assert client.get("/v1/documents/"+str(uuid4())).status_code==404
        assert client.get(f"/v1/documents/{bundle.document.id}/passages",params={"limit":1}).json()["truncated"]

def make_client(tmp_path,handler,**kwargs):
    return SecClient("FIG analyst@unit.test",tmp_path,transport=httpx.MockTransport(handler),limiter=NoWait(),sleep=lambda _:None,**kwargs)

def test_sec_identity_cache_and_request_header(tmp_path):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,content=HTML)
    client=make_client(tmp_path,handler)
    try:
        first=client.get(META["source_url"],immutable=True)
        assert client.get(META["source_url"],immutable=True)==first
        assert len(calls)==1
        assert calls[0].headers["User-Agent"]=="FIG analyst@unit.test"
        assert client.limiter.calls==1
    finally: client.close()

@pytest.mark.parametrize("status",[403,404,302])
def test_sec_permanent_failure_has_no_retry(tmp_path,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status)
    client=make_client(tmp_path,handler)
    try:
        with pytest.raises(SecError): client.get(META["source_url"])
        assert len(calls)==1
    finally: client.close()

def test_sec_retry_bounded(tmp_path):
    responses=iter([503,429,200])
    client=make_client(tmp_path,lambda request:httpx.Response(next(responses),content=HTML,headers={"Retry-After":"0"}))
    try:
        assert client.get(META["source_url"]).body==HTML
        assert client.limiter.calls==3
    finally: client.close()

def test_placeholder_contact_and_external_url_rejected(tmp_path):
    with pytest.raises(ValueError): SecClient("FIG",tmp_path)
    with pytest.raises(ValueError): SecClient("FIG contact@example.com",tmp_path)
    for url in ("https://attacker.test/submissions/foo","https://www.sec.gov/Archives/edgar/data/../secret","https://www.sec.gov/Archives/edgar/data/a%2fb","http://data.sec.gov/submissions/foo"):
        with pytest.raises(ValueError): SecClient.validate_url(url)
    with pytest.raises(ValueError):SecClient("FIG analyst@unit.test",tmp_path,max_response_bytes=201*1024*1024)
    SecClient.validate_url("https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json")

def test_sec_stream_size_limit_is_enforced(tmp_path):
    client=make_client(tmp_path,lambda request:httpx.Response(200,content=b"x"*(1024*1024+1)),max_response_bytes=1024*1024)
    try:
        with pytest.raises(SecError,match="1 MiB"):client.get(META["source_url"])
    finally:client.close()

def test_metadata_selection_and_idempotent_client_pipeline(tmp_path):
    data={"cik":1045810,"name":"Example Issuer","filings":{"recent":{"accessionNumber":[META["accessionNumber"],"0001045810-25-000002"],"form":["10-K","10-Q"],"filingDate":["2025-01-01","2025-04-01"],"primaryDocument":["report.htm","quarter.htm"]},"files":[]}}
    def handler(request):
        return httpx.Response(200,json=data) if "submissions" in str(request.url) else httpx.Response(200,content=HTML)
    client=make_client(tmp_path/"cache",handler)
    store=Store("sqlite:///"+str(tmp_path/"database.sqlite3"))
    store.migrate()
    try:
        first=ingest_annual(client,store,tmp_path/"archive")
        second=ingest_annual(client,store,tmp_path/"archive")
        assert first==second
        assert len(store.documents()["documents"])==1
        assert client.limiter.calls==2
    finally: client.close()

def test_older_accession_history_search(tmp_path):
    data={"cik":1045810,"name":"Example Issuer","filings":{"recent":{"accessionNumber":[],"form":[],"filingDate":[],"primaryDocument":[]},"files":[{"name":"CIK0001045810-submissions-001.json"}]}}
    history={"accessionNumber":[META["accessionNumber"]],"form":["10-K"],"filingDate":["2025-01-01"],"primaryDocument":["report.htm"]}
    client=make_client(tmp_path,lambda request:httpx.Response(200,json=history if "submissions-001" in str(request.url) else data))
    try:
        assert client.latest_annual_filing("1045810",META["accessionNumber"])["accessionNumber"]==META["accessionNumber"]
    finally: client.close()

def test_legacy_non_html_annual_does_not_block_latest_supported_filing(tmp_path):
    data={"cik":937966,"name":"ASML HOLDING NV","filings":{"recent":{
        "accessionNumber":["0001628280-26-011378","0000950172-03-000835"],
        "form":["20-F","20-F"],"filingDate":["2026-02-25","2003-03-14"],
        "primaryDocument":["asml-20251231.htm","lon250172.txt"]},"files":[]}}
    client=make_client(tmp_path,lambda request:httpx.Response(200,json=data))
    try:
        selected=client.latest_annual_filing("937966")
        assert selected["accessionNumber"]=="0001628280-26-011378"
        with pytest.raises(SecError,match="not supported HTML"):
            client.latest_annual_filing("937966","0000950172-03-000835")
    finally:client.close()

def test_bounded_annual_history_selection_and_ingestion(tmp_path):
    rows={"accessionNumber":["0001045810-26-000003","0001045810-25-000002","0001045810-24-000001"],
          "form":["10-K","10-K","10-K"],"filingDate":["2026-02-01","2025-02-01","2024-02-01"],
          "primaryDocument":["report26.htm","report25.htm","report24.htm"]}
    data={"cik":1045810,"name":"Example Issuer","filings":{"recent":rows,"files":[]}}
    client=make_client(tmp_path/"cache",lambda request:httpx.Response(200,json=data) if "submissions" in str(request.url) else httpx.Response(200,content=HTML))
    store=Store("sqlite:///"+str(tmp_path/"history.sqlite3"));store.migrate()
    try:
        selected=client.annual_filings("1045810",2)
        assert [row["accessionNumber"] for row in selected]==rows["accessionNumber"][:2]
        result=ingest_annual_history(client,store,tmp_path/"archive","1045810",2)
        assert len(result["documents"])==2 and len(store.documents()["documents"])==2
        assert ingest_annual_history(client,store,tmp_path/"archive","1045810",2)==result
        with pytest.raises(ValueError):client.annual_filings("1045810",11)
    finally:client.close()

def test_bounded_multi_form_incremental_ingestion(tmp_path):
    rows={"accessionNumber":["0001045810-26-000003","0001045810-26-000002","0001045810-26-000001"],
          "form":["10-K","10-Q","8-K"],"filingDate":["2026-03-01","2026-02-01","2026-01-01"],
          "primaryDocument":["annual.htm","quarter.htm","current.htm"]}
    data={"cik":1045810,"name":"Example Issuer","filings":{"recent":rows,"files":[]}}
    client=make_client(tmp_path/"cache",lambda request:httpx.Response(200,json=data) if "submissions" in str(request.url) else httpx.Response(200,content=HTML))
    store=Store("sqlite:///"+str(tmp_path/"multi.sqlite3"));store.migrate()
    try:
        selected=client.filings("1045810",("10-Q","8-K"),10)
        assert [row["form"] for row in selected]==["10-Q","8-K"]
        first=ingest_filings(client,store,tmp_path/"archive","1045810",("10-Q","8-K"),10)
        assert len(first["documents"])==2 and len(store.documents()["documents"])==2
        assert ingest_filings(client,store,tmp_path/"archive","1045810",("10-Q","8-K"),10)==first
        with pytest.raises(ValueError):client.filings("1045810",("S-1",),10)
    finally:client.close()

def test_new_packaged_migration_matches_source():
    root=__import__("pathlib").Path(__file__).resolve().parents[1]
    assert (root/"migrations/002_ingestion.sql").read_bytes()==(root/"src/fig/resources/002_ingestion.sql").read_bytes()


def test_company_scope_and_named_neighbor_entities(source_setup):
    settings,store,bundle=source_setup
    store.ingest_source(bundle,HTML,settings.archive_dir)
    assert [e["canonical_name"] for e in store.entities()["entities"]]==["Example Issuer"]
    selected=store.passages(bundle.document.id,"wafers")["passages"][0]
    counterparty=Entity(id=uuid4(),kind="Company",canonical_name="Example Foundry",slug="company-foundry")
    review=ReviewInput(passage_id=selected["id"],counterparty=counterparty,predicate="CONTRACTS_MANUFACTURING_TO",quote=selected["text"],reviewer="test-author")
    import_review(store,settings.archive_dir,review)
    assert len(store.entities()["entities"])==2
    assert len(store.entities(query="%")['entities'])==0
    neighbors=store.neighbors(NeighborRequest(entity_id=counterparty.id))
    assert {e["id"] for e in neighbors["entities"]}=={str(counterparty.id),str(bundle.issuer.id)}
    assert neighbors["relationships"][0]["claim"]["subject_id"]==str(bundle.issuer.id)
    document=store.document(bundle.document.id)
    assert document['text_versions'][0]['passage_count']==len(bundle.passages)


def test_analyst_assets_and_api_contract(source_setup):
    settings,store,bundle=source_setup
    store.ingest_source(bundle,HTML,settings.archive_dir)
    with TestClient(create_app(settings)) as client:
        home=client.get("/")
        assert home.status_code==200 and "Connections, with evidence." in home.text
        assert client.get("/assets/app.js").status_code==200
        assert client.get("/assets/styles.css").status_code==200
        assert client.get("/assets/.env").status_code==404
        entities=client.get("/v1/entities")
        assert len(entities.json()['entities'])==1
        assert client.get("/v1/entities",params={'limit':101}).status_code==422
        assert client.get("/v1/entities",params={'query':'%'}).json()['entities']==[]


def test_synthetic_companies_are_opt_in(tmp_path):
    from fig.fixture import fixture
    store=Store('sqlite:///'+str(tmp_path/'synthetic.sqlite3'))
    store.migrate()
    bundle,original=fixture()
    store.ingest(bundle,original,tmp_path/'archive')
    assert store.entities()['entities']==[]
    assert len(store.entities(include_synthetic=True)['entities'])==2

def test_form4_xml_normalization_preserves_leaf_values():
    xml=b"<?xml version='1.0'?><ownershipDocument><issuer><issuerCik>0001045810</issuerCik><issuerName>NVIDIA CORP</issuerName></issuer><reportingOwner><rptOwnerName>Example Person</rptOwnerName></reportingOwner></ownershipDocument>"
    normalized=normalize_html(xml,uuid4())
    assert "issuerName: NVIDIA CORP" in normalized.text_version.normalized_text
    assert "xml_leaf_elements" in normalized.quality_flags
