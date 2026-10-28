import httpx

from fig.jev_shadow import JevShadowJudge, evaluate_shadow


def response_payload(verdict="pass"):
    return {
        "id": "jev-test-response",
        "result": {
            "answers": {
                "overall_verdict": {"choice": verdict, "probabilities": {"pass": .9, "fail": .05, "abstain": .05}, "confidence": .85},
                "evidence_supported": {"noul": .94},
                "citation_correct": {"noul": .91},
                "answer_complete": {"noul": .88},
                "temporal_correct": {"noul": .97},
                "requires_human_review": {"noul": .12},
            },
            "usage": {"input_tokens": 100, "output_tokens": 12, "total_tokens": 112, "cost_usd": .001},
            "elapsedMs": 42,
        },
    }


def test_jev_request_and_typed_response():
    def handler(request):
        body = __import__("json").loads(request.content)
        assert request.url == "https://example.test/v1/systemone"
        assert body["state"]["id"] == "one"
        assert set(body["questions"]) == {"overall_verdict", "evidence_supported", "citation_correct", "answer_complete", "temporal_correct", "requires_human_review"}
        return httpx.Response(200, json=response_payload())
    judge = JevShadowJudge(key="test-key", model="recorded-jev", endpoint="https://example.test/v1/systemone", transport=httpx.MockTransport(handler))
    decision, metadata = judge.judge({"id": "one", "kind": "test"})
    assert decision.verdict == "pass"
    assert decision.evidence_supported_probability == .94
    assert metadata["request_id"] == "jev-test-response"


class RecordedJev:
    model = "recorded-jev"
    endpoint = "recorded://jev"
    calls = 0
    def judge(self, item):
        self.calls += 1
        judge = JevShadowJudge(key="test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_payload(item.get("verdict", "pass")))))
        return judge.judge(item)


def test_shadow_report_is_cached_and_non_mutating(tmp_path):
    judge = RecordedJev()
    items = [{"id": "one", "kind": "test"}, {"id": "two", "kind": "test", "verdict": "abstain"}]
    report = evaluate_shadow(items, tmp_path, judge=judge)
    assert report["mode"] == "shadow_evaluation_only"
    assert report["request_count"] == 2
    assert report["summary"]["pass"] == 1 and report["summary"]["abstain"] == 1
    assert all(row["shadow_only"] for row in report["results"])
    replay = evaluate_shadow(items, tmp_path, judge=judge)
    assert replay["request_count"] == 0
    assert replay["usage"]["total_tokens"] == 224


def test_missing_typed_answer_fails_closed():
    payload = response_payload()
    del payload["result"]["answers"]["temporal_correct"]
    judge = JevShadowJudge(key="test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    try:
        judge.judge({"id": "one", "kind": "test"})
    except RuntimeError as exc:
        assert "omitted answers" in str(exc)
        return
    raise AssertionError("missing Jev answer was accepted")


def test_usage_total_is_derived_when_provider_omits_it(tmp_path):
    class OmittedTotal(RecordedJev):
        def judge(self, item):
            decision, metadata = super().judge(item)
            metadata["usage"].pop("total_tokens")
            return decision, metadata
    report = evaluate_shadow([{"id": "one", "kind": "test"}], tmp_path, judge=OmittedTotal())
    assert report["usage"]["total_tokens"] == 112
