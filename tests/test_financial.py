from pathlib import Path
from fig.config import Settings
from fig.contracts import Entity
from fig.store import Store
from uuid import uuid5,NAMESPACE_URL

def test_company_facts_are_idempotent_and_queryable(tmp_path):
    store=Store("sqlite:///"+str(tmp_path/"facts.sqlite3"));store.migrate()
    entity=Entity(id=uuid5(NAMESPACE_URL,"fig:sec:issuer:1045810"),kind="Company",canonical_name="NVIDIA CORP",slug="sec-cik-1045810")
    with store.connect() as conn:store.insert_immutable(conn,"entity",entity,["kind","canonical_name","slug","status"])
    data={"cik":1045810,"facts":{"us-gaap":{"RevenueFromContractWithCustomerExcludingAssessedTax":{"label":"Revenue","description":"Revenue.","units":{"USD":[{"start":"2025-01-01","end":"2025-12-31","val":100,"accn":"0001045810-26-000001","fy":2026,"fp":"FY","form":"10-K","filed":"2026-02-01"}]}}}}}
    assert store.ingest_company_facts("1045810",data)["inserted"]==1
    assert store.ingest_company_facts("1045810",data)["inserted"]==0
    result=store.financial_metrics(entity.id,"RevenueFromContractWithCustomerExcludingAssessedTax")
    assert result["observations"][0]["val"]==100 and result["observations"][0]["unit"]=="USD"

def test_financial_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/008_financial_facts.sql").read_bytes()==(root/"src/fig/resources/008_financial_facts.sql").read_bytes()
