import json
from types import SimpleNamespace

from fig.llm_judge import JudgeDecision,judge_items


class RecordedJudge:
    model="recorded-judge"
    def judge(self,item,run):
        verdict="pass" if run==1 else item.get("second","pass")
        return JudgeDecision(verdict=verdict,evidence_supported=verdict=="pass",citation_correct=True,answer_complete=True,temporal_correct=True,unsupported_claims=[],reasons=["Recorded rubric result."],corrected_output=None),{"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}


def test_judge_cache_consensus_and_disagreement(tmp_path):
    items=[{"id":"one","kind":"test"},{"id":"two","kind":"test","second":"abstain"}]
    report=judge_items(items,tmp_path,judge=RecordedJudge(),runs=2)
    assert report["request_count"]==4
    assert report["summary"]=={"pass":1,"fail":0,"abstain":0,"disagreement":1}
    assert report["results"][1]["requires_human_review"] is True
    cached=judge_items(items,tmp_path,judge=RecordedJudge(),runs=2)
    assert cached["request_count"]==0 and cached["usage"]["total_tokens"]==60


def test_judge_schema_rejects_uncontrolled_verdict():
    try:JudgeDecision.model_validate({"verdict":"maybe","evidence_supported":False,"citation_correct":False,"answer_complete":False,"temporal_correct":False,"unsupported_claims":[],"reasons":["x"],"corrected_output":None})
    except Exception:return
    raise AssertionError("invalid verdict accepted")
