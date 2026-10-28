import json
from datetime import datetime, time, timezone
from hashlib import sha256
from uuid import uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from fig.contracts import Entity,Document,SourceBundle
from fig.normalization import normalize_html

def build_source(metadata,download,existing=None):
    cik=str(int(metadata["cik"]))
    issuer=Entity(id=uuid5(NAMESPACE_URL,"fig:sec:issuer:"+cik),kind="Company",canonical_name=metadata["issuer_name"],slug="sec-cik-"+cik)
    digest=sha256(download.body).hexdigest()
    doc_id=uuid5(NAMESPACE_URL,f"fig:sec:document:{metadata['accessionNumber']}:{metadata['primaryDocument']}:{digest}")
    # Filing date alone cannot establish precise public dissemination time.
    # Use the end of that ET calendar date as a conservative eligibility cutoff.
    date=datetime.strptime(metadata["filingDate"],"%Y-%m-%d").date()
    cutoff=datetime.combine(date,time.max,tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    reporting_period=metadata.get("reportDate") or None
    if reporting_period:datetime.strptime(reporting_period,"%Y-%m-%d")
    document=Document(id=doc_id,issuer_id=issuer.id,source="sec",source_url=metadata["source_url"],accession=metadata["accessionNumber"],filename=metadata["primaryDocument"],form=metadata["form"],published_at=cutoff,acquired_at=download.acquired_at,content_hash=digest,publication_precision="date",publication_basis="conservative_end_of_filing_date_ET",reporting_period=reporting_period)
    if existing:
        previous=Document.model_validate(existing)
        if previous.id!=document.id or previous.content_hash!=digest:
            raise ValueError("existing source identity mismatch")
        document=previous
    normalized=normalize_html(download.body,document.id)
    return SourceBundle(issuer=issuer,document=document,text_version=normalized.text_version,passages=normalized.passages,quality_flags=normalized.quality_flags)

def ingest_annual(client,store,archive_dir,cik="1045810",accession=None):
    metadata=client.latest_annual_filing(cik,accession)
    download=client.get(metadata["source_url"],immutable=True)
    initial=build_source(metadata,download)
    try:
        existing=store.document(initial.document.id)
        existing.pop("text_versions",None)
    except KeyError:
        existing=None
    bundle=build_source(metadata,download,existing)
    return store.ingest_source(bundle,download.body,archive_dir)

def ingest_annual_history(client,store,archive_dir,cik="1045810",years=3):
    results=[]
    for metadata in client.annual_filings(cik,years):
        download=client.get(metadata["source_url"],immutable=True)
        initial=build_source(metadata,download)
        try:
            existing=store.document(initial.document.id);existing.pop("text_versions",None)
        except KeyError:existing=None
        bundle=build_source(metadata,download,existing)
        results.append(store.ingest_source(bundle,download.body,archive_dir))
    return {"cik":str(int(cik)),"requested_years":years,"documents":results}

def ingest_filings(client,store,archive_dir,cik="1045810",forms=("10-K","10-Q","8-K","DEF 14A","4","20-F","6-K"),limit=20):
    results=[]
    for metadata in client.filings(cik,forms,limit):
        download=client.get(metadata["source_url"],immutable=True);initial=build_source(metadata,download)
        try:existing=store.document(initial.document.id);existing.pop("text_versions",None)
        except KeyError:existing=None
        results.append(store.ingest_source(build_source(metadata,download,existing),download.body,archive_dir))
    return {"cik":str(int(cik)),"forms":list(forms),"limit":limit,"documents":results}
