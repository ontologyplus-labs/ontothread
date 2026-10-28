from pathlib import Path

from fastapi.testclient import TestClient

from fig.api import create_app
from fig.config import Settings
from fig.contracts import SourceBundle
from fig.fixture import fixture
from fig.store import Store


def test_seeded_alias_identifier_resolution_and_search(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"registry.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate();bundle,original=fixture()
    data=bundle.model_dump(mode="json");data["entities"][0]["slug"]="sec-cik-1045810"
    source=SourceBundle(issuer=data["entities"][0],document=data["document"],text_version=data["text_version"],passages=[data["passage"]],quality_flags=[])
    store.ingest_source(source,original,settings.archive_dir);store.seed_core_registry()
    resolved=store.resolve_entity_mention("NVDA")
    assert resolved["resolved"]["id"]==str(source.issuer.id) and not resolved["ambiguous"]
    registry=store.entity_registry(source.issuer.id)
    assert {item["scheme"] for item in registry["identifiers"]}=={"CIK","TICKER"}
    assert store.entities("Nvidia Corporation",include_synthetic=True)["entities"][0]["id"]==str(source.issuer.id)
    assert store.resolve_entity_mention("H100")["resolved"]["canonical_name"]=="NVIDIA H100"
    assert store.resolve_entity_mention("EUV systems")["resolved"]["kind"]=="Technology"
    assert store.resolve_entity_mention("Jensen Huang")["resolved"]["canonical_name"]=="Jen-Hsun Huang"
    assert store.resolve_entity_mention("Dr. Lisa Su")["resolved"]["kind"]=="Person"
    fuzzy=store.entity_resolution_candidates("NVIDA")
    assert fuzzy["candidates"][0]["entity"]["canonical_name"]==source.issuer.canonical_name
    assert fuzzy["candidates"][0]["confidence_band"] in {"contextual_validation","manual_review"}
    assert fuzzy["automatic_fuzzy_merge"] is False
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/entities/resolve/NVDA").json()["resolved"]["id"]==str(source.issuer.id)
        assert client.get("/v1/entities/candidates/NVIDA").json()["candidates"][0]["entity"]["id"]==str(source.issuer.id)
        assert client.get(f"/v1/entities/{source.issuer.id}/registry").status_code==200


def test_registry_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/006_entity_registry.sql").read_bytes()==(root/"src/fig/resources/006_entity_registry.sql").read_bytes()
