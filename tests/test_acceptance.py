import json
from fig.acceptance import run_acceptance
from fig.config import Settings
from fig.contracts import ReviewedBundle
from fig.fixture import fixture
from fig.store import Store

def test_acceptance_runner_separates_automatic_and_human_checks(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"acceptance.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    bundle,original=fixture();data=bundle.model_dump(mode="json");data["entities"][0]["slug"]="sec-cik-1045810";data["entities"][0]["canonical_name"]="NVIDIA CORP";bundle=ReviewedBundle.model_validate(data)
    store.ingest(bundle,original,settings.archive_dir);store.seed_core_registry()
    catalog={"version":"test","questions":[
        {"id":"q20","kind":"identity","question":"Resolve NVDA","acceptance":"Resolve NVIDIA."},
        {"id":"q14","kind":"document","question":"Review a document","acceptance":"Human review."}]}
    path=tmp_path/"catalog.json";path.write_text(json.dumps(catalog))
    report=run_acceptance(store,path)
    assert report["summary"]=={"pass":1,"fail":0,"independent_review_required":1}
