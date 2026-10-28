import os
from pathlib import Path
import pytest
from neo4j import GraphDatabase
from fig.fixture import fixture
from fig.store import Store
from fig.contracts import NeighborRequest
from fig.projection import project_pending
from fig.research import ResearchService,execute_readonly_cypher
from fig.contracts import ResearchRequest

@pytest.mark.integration
def test_postgres_and_neo4j(tmp_path):
    url=os.getenv("FIG_TEST_DATABASE_URL")
    uri=os.getenv("FIG_TEST_NEO4J_URI")
    password=os.getenv("FIG_TEST_NEO4J_PASSWORD")
    if not all((url,uri,password)):
        pytest.skip("Requires dedicated FIG_TEST_DATABASE_URL and FIG_TEST_NEO4J_* settings")
    store=Store(url)
    store.migrate()
    bundle,original=fixture()
    store.ingest(bundle,original,tmp_path)
    store.ingest(bundle,original,tmp_path)
    assert len(store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))["relationships"])==1
    project_pending(store,uri,"neo4j",password)
    assert project_pending(store,uri,"neo4j",password)==0
    research=ResearchService(store).ask(ResearchRequest(question="Show relationships for Example Designer with evidence"))
    graph_result=execute_readonly_cypher(uri,"neo4j",password,research["generated_cypher"],research["cypher_parameters"])
    assert graph_result["count"]==1
    assert graph_result["records"][0]["relationships"][0]["claim_revision_id"]==str(bundle.claim.id)
    with GraphDatabase.driver(uri,auth=("neo4j",password)) as driver:
        with driver.session() as session:
            row=session.run("MATCH ()-[r:BUSINESS_RELATION {claim_revision_id:$id}]->() RETURN count(r) AS n",id=str(bundle.claim.id)).single()
            assert row["n"]==1
