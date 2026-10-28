from datetime import datetime,timezone,timedelta
from hashlib import sha256
from uuid import uuid4

from fig.config import Settings
from fig.contracts import Document,Entity,Passage,SourceBundle,TextVersion
from fig.schema_pressure import detect_schema_pressure
from fig.store import Store

def test_recurring_schema_pressure_requires_distinct_documents(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"pressure.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    issuer=Entity(id=uuid4(),kind="Company",canonical_name="Pressure Corp",slug="pressure-corp")
    for index in range(2):
        text="We rely on advanced packaging services for this product.";digest=sha256((text+str(index)).encode()).hexdigest();now=datetime.now(timezone.utc)+timedelta(seconds=index)
        document=Document(id=uuid4(),issuer_id=issuer.id,source="sec",source_url=f"https://www.sec.gov/Archives/edgar/data/1/{index}/a.htm",accession=f"0000000001-26-00000{index}",filename="a.htm",form="8-K",published_at=now,acquired_at=now,content_hash=digest)
        version=TextVersion(id=uuid4(),document_id=document.id,parser_version="test",normalized_hash=sha256(text.encode()).hexdigest(),normalized_text=text)
        passage=Passage(id=uuid4(),text_version_id=version.id,section_path="test",start_offset=0,end_offset=len(text))
        store.ingest_source(SourceBundle(issuer=issuer,document=document,text_version=version,passages=[passage],quality_flags=[]),(text+str(index)).encode(),settings.archive_dir)
        store.create_schema_discovery(passage_id=passage.id,failure_type="missing_predicate",concept_name="USES_PACKAGING_SERVICE",
            proposed_change_type="add_predicate",exact_quote=text,rationale="The bounded extractor cannot encode this explicit reviewed relation.",
            proposed_schema={"subject":["Company"],"object":["Technology"]})
    result=detect_schema_pressure(store,2)
    signal=next(item for item in result["signals"] if item["concept_name"]=="PROVIDES_ADVANCED_PACKAGING")
    assert signal["document_recurrence"]==2 and signal["recommendation"]=="propose_for_review"
    discovered=next(item for item in result["signals"] if item["concept_name"]=="USES_PACKAGING_SERVICE")
    assert discovered["detection_sources"]==["schema_discovery"] and discovered["document_recurrence"]==2
    assert result["automatic_mutation"] is False
