from copy import deepcopy
from hashlib import sha256

import pytest

from fig.expanded_experiment import CONDITIONS, aliases, edge_key, run_benchmark, score_edges, validate_spec


def edge(predicate="SUPPLIES_TO", quote="Issuer supplies Other."):
    return {"subject_name": "Issuer", "subject_kind": "Company", "predicate": predicate, "object_name": "Other", "object_kind": "Company", "quote": quote}


def case(id="a", predicate="SUPPLIES_TO", document="doc-a"):
    text = "Issuer supplies Other."
    return {"id": id, "document_id": document, "issuer_name": "Issuer", "text": text, "text_hash": sha256(text.encode()).hexdigest(), "expected": [edge(predicate)]}


def policies():
    fixed = {"version": "finance-v2", "definitions": {"predicates": {"SUPPLIES_TO": {"subject": ["Company"], "object": ["Company"]}}}}
    evolved = deepcopy(fixed)
    evolved["version"] = "development-evolved"
    evolved["definitions"]["predicates"]["NEW_RELATION"] = {"subject": ["Company"], "object": ["Company"]}
    return {name: {"snapshot": None if name == CONDITIONS[1] else fixed if name == CONDITIONS[0] else evolved} for name in CONDITIONS}


class Provider:
    model = "synthetic-test"

    def __init__(self, predictions):
        self.predictions = predictions

    def __call__(self, source, condition, policy):
        assert set(source) == {"id", "issuer_name", "text", "text_hash"}
        assert "expected" not in source and "documented_aliases" not in source
        return deepcopy(self.predictions[source["id"]]), {}


def test_four_conditions_apply_distinct_schema_and_pair_supported_instances():
    a, b = case(), case("b", "NEW_RELATION", "doc-b")
    report = run_benchmark({"partition": "development", "cases": [a, b]}, policies(), Provider({"a": [edge()], "b": [edge("NEW_RELATION")]}), iterations=100)
    assert report["conditions"][CONDITIONS[0]]["accepted"]["recall"] == .5
    assert report["conditions"][CONDITIONS[2]]["accepted"]["recall"] == 1
    assert report["paired_effects"]["recall_delta"] == .5
    assert report["uncertainty"]["recall_delta_ci95"] == [0, 1]
    assert report["conditions"][CONDITIONS[1]]["schema_diagnostics"]["labels_outside_fixed_ontology"] == ["NEW_RELATION"]
    assert not report["publication_ready"]


def test_failed_provider_is_missing_and_guardrail_cannot_pass():
    class Fails(Provider):
        def __call__(self, source, condition, policy):
            if condition == CONDITIONS[2]:
                raise RuntimeError("test failure")
            return super().__call__(source, condition, policy)
    report = run_benchmark({"partition": "development", "cases": [case()]}, policies(), Fails({"a": [edge()]}), iterations=10)
    assert report["status"] == "incomplete"
    assert report["conditions"][CONDITIONS[2]]["missing_cases"] == 1
    assert report["conditions"][CONDITIONS[2]]["accepted"]["recall"] is None
    assert report["paired_effects"]["precision_guardrail_pass"] is None
    assert report["uncertainty"]["paired_cases"] == 0


def test_unsupported_quote_does_not_receive_supported_credit():
    score = score_edges(case(), [edge(quote="Other")])
    assert (score["tp"], score["fp"], score["fn"]) == (0, 1, 1)
    invalid = score_edges(case(), [edge(quote="Fabricated quote")])
    assert invalid["invalid_evidence"] == 1


def test_duplicates_and_wrong_direction_are_reported_separately():
    duplicate = score_edges(case(), [edge(), edge()])
    assert duplicate["tp"] == 1 and duplicate["duplicate_predictions"] == 1
    reversed_edge = {**edge(), "subject_name": "Other", "object_name": "Issuer"}
    assert score_edges(case(), [reversed_edge])["wrong_direction"] == 1


def test_identity_does_not_strip_suffixes_or_normalize_similar_spelling():
    source = case()
    changed = {**edge(), "object_name": "Other Inc."}
    assert edge_key(edge(), source) != edge_key(changed, source)
    source["documented_aliases"] = [{"alias": "Other Inc.", "canonical": "Other", "quote": source["text"]}]
    with pytest.raises(ValueError, match="documented"):
        aliases(source)
    source["text"] += " Other Inc. (Other) is the named company."
    source["documented_aliases"][0]["quote"] = "Other Inc. (Other) is the named company."
    assert edge_key(edge(), source) == edge_key(changed, source)


def test_sealed_partition_blocked_before_cases_opened():
    with pytest.raises(ValueError, match="development only"):
        validate_spec({"partition": "test"})


def test_source_hash_and_endpoint_constraint_are_enforced():
    source = case()
    source["text_hash"] = "bad"
    with pytest.raises(ValueError, match="hash"):
        validate_spec({"partition": "development", "cases": [source]})
    predictions = {"a": [{**edge(), "object_kind": "Technology"}]}
    report = run_benchmark({"partition": "development", "cases": [case()]}, policies(), Provider(predictions), iterations=10)
    assert report["conditions"][CONDITIONS[0]]["schema_diagnostics"]["endpoint_constraint_violations"] == 1
    assert report["conditions"][CONDITIONS[1]]["raw"]["fp"] == 1


def test_noncompany_gold_endpoints_supported_by_generic_runner():
    source = case()
    source["expected"][0]["object_kind"] = "Technology"
    policy = policies()
    for condition in (CONDITIONS[0], CONDITIONS[2], CONDITIONS[3]):
        policy[condition]["snapshot"]["definitions"]["predicates"]["SUPPLIES_TO"]["object"] = ["Technology"]
    report = run_benchmark({"partition": "development", "cases": [source]}, policy, Provider({"a": source["expected"]}), iterations=10)
    assert all(record["accepted"]["tp"] == 1 for record in report["conditions"].values())


def test_unknown_usage_and_price_do_not_become_zero_cost():
    report = run_benchmark({"partition": "development", "cases": [case()]}, policies(), Provider({"a": [edge()]}), iterations=10)
    assert all(record["estimated_cost_usd"] is None for record in report["conditions"].values())
    with pytest.raises(ValueError, match="prices"):
        run_benchmark({"partition": "development", "cases": [case()]}, policies(), Provider({"a": [edge()]}), prices={"input_per_million": float("nan"), "output_per_million": 0})


def test_bootstrap_reproducible_for_same_seed():
    source = {"partition": "development", "cases": [case(), case("b", "NEW_RELATION", "doc-b")]}
    predictions = Provider({"a": [edge()], "b": [edge("NEW_RELATION")]})
    a = run_benchmark(source, policies(), predictions, iterations=50)
    b = run_benchmark(source, policies(), predictions, iterations=50)
    assert a["uncertainty"] == b["uncertainty"]
