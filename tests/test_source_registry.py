from pathlib import Path
from fig.source_registry import load_source_registry,ingestible_sources

def test_non_sec_sources_are_official_and_fail_closed():
    path=Path(__file__).resolve().parents[1]/"sources/non-sec-sources.yaml"
    registry=load_source_registry(path)
    assert len(registry["sources"])==5
    assert ingestible_sources(path)==[]
    assert all(source["archive_policy"]=="pending_review" for source in registry["sources"])
