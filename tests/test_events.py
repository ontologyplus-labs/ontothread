from pathlib import Path

from fig.contracts import EventReviewDecision
from fig.events import EventReview,EventReviewConflict
def test_event_review_persistence_audit_and_stale_decision(tmp_path):
    # Reuse the same construction pattern through a small local helper.
    from datetime import datetime,timezone
    from hashlib import sha256
    from uuid import uuid5,NAMESPACE_URL
    from fig.config import Settings
    from fig.contracts import Document,Entity,Passage,SourceBundle,TextVersion
    from fig.store import Store
    settings=Settings("sqlite:///"+str(tmp_path/"events.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    issuer=Entity(id=uuid5(NAMESPACE_URL,"fig:sec:issuer:1045810"),kind="Company",canonical_name="NVIDIA CORP",slug="sec-cik-1045810")
    text="NVIDIA raised our revenue guidance for the quarter.";digest=sha256(text.encode()).hexdigest();now=datetime.now(timezone.utc)
    document=Document(id=uuid5(NAMESPACE_URL,"events-doc"),issuer_id=issuer.id,source="sec",source_url="https://www.sec.gov/Archives/edgar/data/1045810/x/a.htm",accession="0001045810-26-000002",filename="a.htm",form="8-K",published_at=now,acquired_at=now,content_hash=digest)
    version=TextVersion(id=uuid5(NAMESPACE_URL,"events-text"),document_id=document.id,parser_version="test",normalized_hash=digest,normalized_text=text)
    passage=Passage(id=uuid5(NAMESPACE_URL,"events-passage"),text_version_id=version.id,section_path="test",start_offset=0,end_offset=len(text))
    store.ingest_source(SourceBundle(issuer=issuer,document=document,text_version=version,passages=[passage],quality_flags=[]),text.encode(),settings.archive_dir);store.seed_core_registry()
    review=EventReview(store);candidate_id=review.analyze([passage.id])["candidate_ids"][0]
    result=review.decide(candidate_id,EventReviewDecision(action="accept",expected_version=1,reviewer="test-reviewer",notes="Explicit guidance increase."))
    assert result["state"]=="accepted" and result["version"]==2
    assert review.history(candidate_id)["decisions"][0]["reviewer"]=="test-reviewer"
    try:review.decide(candidate_id,EventReviewDecision(action="reject",expected_version=1,reviewer="test-reviewer",notes="stale"))
    except EventReviewConflict:pass
    else:raise AssertionError("stale event decision should conflict")

def test_event_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/007_event_review.sql").read_bytes()==(root/"src/fig/resources/007_event_review.sql").read_bytes()
