from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fig.api import create_app
from fig.config import Settings
from fig.contracts import OntologyProposalCreate, OntologyProposalDecision, OntologyProposalRebase
from fig.fixture import fixture
from fig.store import OntologyConflict, Store


@pytest.fixture
def setup(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"ontology.sqlite3"),tmp_path/"archive")
    store=Store(settings.database_url);store.migrate()
    bundle,original=fixture();store.ingest(bundle,original,settings.archive_dir)
    return settings,store,bundle


def proposal(bundle,name="USES_PROCESS"):
    return OntologyProposalCreate(
        change_type="add_predicate",concept_name=name,
        definition="The subject company explicitly uses the object technology in production.",
        rationale="The evidence describes a recurring relation that the seed predicates cannot encode.",
        proposed_schema={"subject":["Company"],"object":["Technology"]},
        evidence_passage_ids=[bundle.passage.id],recurrence_count=3,
        base_ontology_version="finance-v2",proposer="codex:schema-pressure-test")


def decision(action="accept",version=1,**kwargs):
    values={"action":action,"expected_version":version,"reviewer":"ontology-reviewer",
            "notes":"Reviewed against examples and existing ontology concepts."}
    if action=="accept":values["migration_notes"]="Add the supported relation without migrating existing claims."
    values.update(kwargs)
    return OntologyProposalDecision(**values)


def test_accept_creates_append_only_version_and_migration(setup):
    _,store,bundle=setup
    created=store.create_ontology_proposal(proposal(bundle))
    result=store.decide_ontology_proposal(created["id"],decision())
    assert result["proposal"]["state"]=="accepted"
    assert result["migration"]["from_version"]=="finance-v2"
    assert result["migration"]["to_version"]=="finance-v3"
    versions=store.ontology_versions()["versions"]
    assert [item["version"] for item in versions]==["finance-v1","finance-v2","finance-v3"]
    assert versions[2]["definitions"]["predicates"]["USES_PROCESS"]=={"subject":["Company"],"object":["Technology"]}
    history=store.ontology_proposal(created["id"])
    assert history["decisions"][0]["reviewer"]=="ontology-reviewer"
    assert history["migration"]["to_version"]=="finance-v3"


def test_defer_then_reject_is_audited_and_stale_is_blocked(setup):
    _,store,bundle=setup
    created=store.create_ontology_proposal(proposal(bundle,"CAPACITY_EXPOSED_TO"))
    deferred=store.decide_ontology_proposal(created["id"],decision("defer"))
    assert deferred["proposal"]["state"]=="deferred"
    with pytest.raises(OntologyConflict,match="changed"):
        store.decide_ontology_proposal(created["id"],decision("reject",version=1))
    rejected=store.decide_ontology_proposal(created["id"],decision("reject",version=2))
    assert rejected["proposal"]["state"]=="rejected"
    assert len(store.ontology_proposal(created["id"])["decisions"])==2
    assert len(store.ontology_versions()["versions"])==2


def test_duplicate_schema_and_old_base_cannot_be_accepted(setup):
    _,store,bundle=setup
    first=store.create_ontology_proposal(proposal(bundle,"USES_PROCESS"))
    with pytest.raises(OntologyConflict,match="open proposal"):
        store.create_ontology_proposal(proposal(bundle,"USES_PROCESS"))
    second=store.create_ontology_proposal(proposal(bundle,"RELIES_ON_PROCESS"))
    store.decide_ontology_proposal(first["id"],decision())
    with pytest.raises(OntologyConflict,match="Rebase"):
        store.decide_ontology_proposal(second["id"],decision())
    rebased=store.rebase_ontology_proposal(second["id"],OntologyProposalRebase(expected_version=1,target_ontology_version="finance-v3",reviewer="ontology-reviewer",notes="Rechecked endpoint constraints against the newly accepted ontology."))
    assert rebased["proposal"]["base_ontology_version"]=="finance-v3" and rebased["decision"]["action"]=="rebase"
    accepted=store.decide_ontology_proposal(second["id"],decision(version=2))
    assert accepted["migration"]["from_version"]=="finance-v3" and accepted["migration"]["to_version"]=="finance-v4"


def test_merge_target_must_exist_in_matching_ontology_category(setup):
    _,store,bundle=setup
    created=store.create_ontology_proposal(proposal(bundle,"USES_FOUNDRY"))
    with pytest.raises(ValueError,match="existing concept"):
        store.decide_ontology_proposal(created["id"],decision("merge",merge_target="NOT_A_PREDICATE"))
    merged=store.decide_ontology_proposal(created["id"],decision("merge",merge_target="CONTRACTS_MANUFACTURING_TO"))
    assert merged["proposal"]["state"]=="merged"
    assert merged["decision"]["merge_target"]=="CONTRACTS_MANUFACTURING_TO"


def test_contracts_and_schema_reject_invalid_changes(setup):
    _,store,bundle=setup
    data=proposal(bundle).model_dump(mode="json");data["concept_name"]="Uses process"
    with pytest.raises(ValidationError):OntologyProposalCreate.model_validate(data)
    data=proposal(bundle,"INVALID_ENDPOINT").model_dump(mode="json")
    data["proposed_schema"]={"subject":["Company"],"object":["Facility"]}
    created=store.create_ontology_proposal(OntologyProposalCreate.model_validate(data))
    with pytest.raises(ValueError,match="unknown entity"):
        store.decide_ontology_proposal(created["id"],decision())


def test_ontology_api_and_origin_guard(setup):
    settings,_,bundle=setup
    body=proposal(bundle).model_dump(mode="json")
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/ontology/versions").json()["versions"][0]["version"]=="finance-v1"
        assert client.post("/v1/ontology/proposals",json=body,headers={"Origin":"https://unrelated.test"}).status_code==403
        created=client.post("/v1/ontology/proposals",json=body)
        assert created.status_code==200
        proposal_id=created.json()["id"]
        assert client.get("/v1/ontology/proposals?state=pending").json()["proposals"][0]["id"]==proposal_id
        accepted=client.post(f"/v1/ontology/proposals/{proposal_id}/decisions",json=decision().model_dump(mode="json"))
        assert accepted.status_code==200 and accepted.json()["migration"]["to_version"]=="finance-v3"
        assert client.get(f"/v1/ontology/proposals/{proposal_id}").json()["proposal"]["state"]=="accepted"


def test_ontology_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/"migrations/005_ontology_evolution.sql").read_bytes()==(root/"src/fig/resources/005_ontology_evolution.sql").read_bytes()
    assert (root/"ontology/finance-v2.yaml").read_bytes()==(root/"src/fig/resources/finance-v2.yaml").read_bytes()
