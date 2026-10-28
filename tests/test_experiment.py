import csv,json
from fig.annotations import agreement,load_review,load_prospective_relation_review,load_prospective_qa_review
from fig.experiment import run_experiment


def test_paired_metrics_bootstrap_and_publication_gate():
    items=[]
    for index,(gold,fixed,evolving) in enumerate(((True,False,True),(True,True,True),(False,False,False),(False,True,False))):
        items.append({"id":str(index),"document_id":"a" if index<2 else "b","gold_supported":gold,
            "conditions":{"fixed":{"supported":fixed},"evolving":{"supported":evolving}}})
    report=run_experiment({"version":"v1","partition":"development","independent_human_review":False,"baseline":"fixed","treatment":"evolving","items":items},iterations=200,seed=4)
    assert report["condition_metrics"]["fixed"]["recall"]==.5
    assert report["condition_metrics"]["evolving"]["precision"]==1
    assert report["paired_effects"]["recall_delta"]==.5 and report["paired_effects"]["precision_guardrail_pass"]
    assert report["condition_metrics"]["evolving"]["precision_wilson95"][0]<1
    assert report["paired_correctness"]["recovered"]==2 and report["paired_correctness"]["regressed"]==0
    assert report["uncertainty"]["cluster_count"]==2 and report["publication_ready"] is False


def _write_review(path,verdicts):
    fields=["case_id","independent_verdict","corrected_relationships","reviewer_notes"]
    with path.open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for case_id,verdict in verdicts:writer.writerow({"case_id":case_id,"independent_verdict":verdict,"corrected_relationships":"[]" if verdict=="correct" else "","reviewer_notes":"reviewed"})


def test_annotation_validation_and_agreement(tmp_path):
    first=tmp_path/"one.csv";second=tmp_path/"two.csv"
    _write_review(first,[("a","agree"),("b","correct"),("c","")]);_write_review(second,[("a","agree"),("b","agree"),("c","uncertain")])
    result=load_review(first)
    assert result["case_count"]==3 and result["completed_count"]==2 and not result["complete"]
    score=agreement(first,second)
    assert score["double_annotated"]==2 and score["percent_agreement"]==.5 and score["disagreements"]==["b"]


def test_prospective_packet_validators_do_not_treat_blanks_as_negatives(tmp_path):
    relation=tmp_path/"relations.csv"
    relation.write_text("packet_id,relation_verdict,relationships_json,ontology_disposition\na,,,\nb,supported,[],existing_concept\n")
    result=load_prospective_relation_review(relation)
    assert result["case_count"]==2 and result["completed_count"]==1 and not result["complete"]
    qa=tmp_path/"qa.csv";qa.write_text("question_id,answer_status,answer_claims_json,valid_paths_json,citation_passage_ids_json\nq,unsupported,[],[],[]\n")
    assert load_prospective_qa_review(qa)["complete"] is True
