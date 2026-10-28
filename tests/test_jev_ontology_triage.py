from fig.jev_ontology_triage import JevOntologyTriager,triage_signals
from fig.jev_shadow import JevAnswer


class RecordedClient:
    model="recorded-jev";endpoint="recorded://jev"
    def ask(self,state,questions):
        return {
            "disposition":JevAnswer(choice="new_predicate",probabilities={"new_predicate":.8,"defer":.2},confidence=.7),
            "evidence_quality":JevAnswer(probabilities={"strong":.7,"mixed":.3},confidence=.65,score=3.7),
            "redundant_with_existing":JevAnswer(noul=.12),
            "requires_human_review":JevAnswer(noul=.91),
        },{"usage":{"input_tokens":20,"output_tokens":4}}


def signal():
    return {"concept_name":"ADVANCED_PACKAGING_PROVIDER","change_type":"add_predicate","definition":"A company provides advanced packaging.","document_recurrence":3,"evidence_examples":[{"text":"We use X for advanced packaging."}]}


def test_ontology_triage_is_shadow_only_and_cached(tmp_path):
    ontology={"entities":["Company"],"predicates":{},"qualifiers":{}}
    report=triage_signals(ontology,[signal()],tmp_path,triager=JevOntologyTriager(RecordedClient()))
    decision=report["results"][0]["decision"]
    assert decision["disposition"]=="new_predicate" and decision["human_review_probability"]==.91
    assert report["automatic_ontology_mutation"] is False
    assert triage_signals(ontology,[signal()],tmp_path,triager=JevOntologyTriager(RecordedClient()))["request_count"]==0


def test_ontology_triage_rejects_unbounded_disposition():
    class Invalid(RecordedClient):
        def ask(self,state,questions):
            answers,meta=super().ask(state,questions);answers["disposition"].choice="auto_accept";return answers,meta
    try:JevOntologyTriager(Invalid()).triage(signal(),{"entities":["Company"],"predicates":{}})
    except RuntimeError as exc:
        assert "invalid ontology disposition" in str(exc);return
    raise AssertionError("unbounded ontology disposition was accepted")
