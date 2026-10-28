import json
from hashlib import sha256

import httpx
import pytest

from fig.generic_extraction import GenericOpenAIProvider, ProviderFailure, payload, parse_response, usage_cost


def source():
    text = "Issuer develops Named Technology."
    return {"id": "example", "issuer_name": "Issuer", "text": text, "text_hash": sha256(text.encode()).hexdigest()}


def policy(version="example"):
    return {"snapshot": {"version": version, "definitions": {"entities": ["Company", "Technology"], "predicates": {"DEVELOPS": {"subject": ["Company"], "object": ["Technology"]}}}}}


def response(status="completed"):
    return {"id": "test-response", "status": status, "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({"edges": [{"subject_name": "Issuer", "subject_kind": "Company", "predicate": "DEVELOPS", "object_name": "Named Technology", "object_kind": "Technology", "quote": source()["text"]}]})}]}], "usage": {"input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {"cached_tokens": 200}}}


def test_generic_schema_and_gold_leakage_guard():
    request = payload(source(), policy(), {"predicates": {}})
    properties = request["text"]["format"]["schema"]["properties"]["edges"]["items"]["properties"]
    assert properties["object_kind"]["enum"] == ["Company", "Technology"]
    assert properties["predicate"]["enum"] == ["DEVELOPS"]
    assert json.loads(request["input"][1]["content"]) == {"issuer": "Issuer", "passage": source()["text"]}
    assert request["store"] is False
    with pytest.raises(ValueError, match="source-only"):
        payload({**source(), "expected": []}, policy(), {})


def test_unconstrained_schema_has_no_predicate_enum():
    request = payload(source(), {"snapshot": None}, {})
    assert "enum" not in request["text"]["format"]["schema"]["properties"]["edges"]["items"]["properties"]["predicate"]


def test_provider_caches_identical_policies_without_duplicating_paid_calls(tmp_path):
    calls = []
    def handle(request):
        assert request.url == "https://api.openai.com/v1/responses"
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    provider = GenericOpenAIProvider(tmp_path, {"predicates": {}}, key="test-key", transport=httpx.MockTransport(handle))
    a, paid = provider(source(), "controlled_evolving", policy("one"))
    b, cached = provider(source(), "oracle", policy("two"))
    assert a == b and len(calls) == 1
    assert paid["billed_cost_usd"] == usage_cost(response()["usage"])
    assert cached["billed_cost_usd"] == 0 and cached["cached"]
    assert provider.ledger()["requests"] == 1
    assert "test-key" not in next(tmp_path.glob("*.json")).read_text()


def test_failure_halts_without_retry_and_is_not_empty_success(tmp_path):
    provider = GenericOpenAIProvider(tmp_path, {}, key="test-key", transport=httpx.MockTransport(lambda _: httpx.Response(429, json={"error": {"message": "private-provider-body"}})))
    for _ in range(2):
        with pytest.raises(ProviderFailure, match="provider_http_429") as caught:
            provider(source(), "unconstrained_generated", {"snapshot": None})
        assert "private-provider-body" not in str(caught.value)
    assert provider.ledger()["requests"] == 1
    assert provider.ledger()["uncertain_failure_cost_upper_bound_usd"] > 0
    assert not list(tmp_path.glob("*.json"))


def test_spend_reservation_stops_before_network_call(tmp_path):
    def should_not_call(_):
        raise AssertionError("budget-limited request contacted network")
    provider = GenericOpenAIProvider(tmp_path, {}, key="test-key", budget_usd=.00001, transport=httpx.MockTransport(should_not_call))
    with pytest.raises(ProviderFailure, match="spend_limit"):
        provider(source(), "unconstrained_generated", {"snapshot": None})
    assert provider.ledger()["requests"] == 0


def test_incomplete_response_cost_is_retained_and_not_cached(tmp_path):
    provider = GenericOpenAIProvider(tmp_path, {}, key="test-key", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response("incomplete"))))
    with pytest.raises(ProviderFailure, match="incomplete"):
        provider(source(), "unconstrained_generated", {"snapshot": None})
    assert provider.ledger()["known_cost_usd"] > 0
    assert not list(tmp_path.glob("*.json"))


def test_invalid_schema_or_usage_is_rejected():
    result = response()
    result["output"][0]["content"][0]["text"] = '{"edges": [{"subject_name":"invented"}]}'
    with pytest.raises(ProviderFailure, match="schema"):
        parse_response(result)
    with pytest.raises(ProviderFailure, match="usage"):
        usage_cost({"input_tokens": 1, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 3}})
