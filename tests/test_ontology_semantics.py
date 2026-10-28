from pathlib import Path
import yaml
from fig.config import Settings
from fig.store import Store


def test_semantic_catalog_covers_active_development_ontology(tmp_path):
    root=Path(__file__).resolve().parents[1];catalog=yaml.safe_load((root/"ontology/semantics-v1.yaml").read_text())
    store=Store("sqlite:///"+str(tmp_path/"semantics.sqlite3"));store.migrate()
    definitions=store.ontology_versions()["versions"][-1]["definitions"]
    assert set(definitions["entities"])<=set(catalog["entities"])
    assert set(definitions["predicates"])<=set(catalog["predicates"])
    assert "PROVIDES_ADVANCED_PACKAGING" in catalog["predicates"]
    assert catalog["semantic_model"]=="constrained_property_graph" and catalog["formal_reasoner_required"] is False
