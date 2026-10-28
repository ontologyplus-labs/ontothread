from hashlib import sha256
import json
from pathlib import Path

from fig.expanded_qa import graph_from_cases, enumerate_paths, generate_questions, score_qa


def cases():
    items = []
    for id, subject, object in (("a", "A", "B"), ("b", "B", "C")):
        text = f"{subject} supplies {object}."
        items.append({"id": id, "document_id": id, "issuer_name": subject, "text": text, "text_hash": sha256(text.encode()).hexdigest(), "expected": [{"subject_name": subject, "subject_kind": "Company", "predicate": "SUPPLIES_TO", "object_name": object, "object_kind": "Company", "quote": text}]})
    return items


def test_reverse_traversal_preserves_asserted_direction_and_avoids_cycles():
    graph = graph_from_cases(cases())
    paths = enumerate_paths(graph, ("C", "Company"), ("A", "Company"), 2)
    assert len(paths) == 1
    assert all(edge["traversal"] == "reverse" for edge in paths[0])
    assert paths[0][0]["edge"][:3] == ["B", "Company", "SUPPLIES_TO"]
    assert enumerate_paths(graph, ("A", "Company"), ("A", "Company"), 2) == []


def test_repeated_disclosure_does_not_duplicate_paths():
    items = cases()
    items.append({**items[0], "id": "another-disclosure"})
    graph = graph_from_cases(items)
    assert len(graph) == 2
    assert len(enumerate_paths(graph, ("A", "Company"), ("B", "Company"), 1)) == 1


def test_reference_derived_set_is_balanced_and_explicitly_diagnostic():
    path = Path(__file__).resolve().parents[1] / "evaluation/expanded/finalized/retrospective-v1/references.json"
    data = generate_questions(json.loads(path.read_text())["cases"])
    assert len(data["questions"]) == 72
    for stratum in ("1_hop", "2_hop", "3_hop", "unsupported_or_underspecified"):
        assert sum(question["stratum"] == stratum for question in data["questions"]) == 18
    assert "not_independently" in data["status"]


def test_citation_integrity_is_required_for_supported_paths():
    items = cases()
    graph = graph_from_cases(items)
    question = {"id": "q", "stratum": "2_hop", "source": ["A", "Company"], "target": ["C", "Company"], "hops": 2, "status": "supported", "expected_paths": enumerate_paths(graph, ("A", "Company"), ("C", "Company"), 2)}
    predictions = [{"case_id": case["id"], "conditions": {"fixed": {"status": "completed", "accepted_edges": case["expected"]}}} for case in items]
    correct = score_qa(items, {"questions": [question]}, predictions, "fixed")
    assert correct["path_tp"] == 1 and correct["citation_correctness"] == 1
    predictions[0]["conditions"]["fixed"]["accepted_edges"] = [{**items[0]["expected"][0], "quote": "B"}]
    wrong = score_qa(items, {"questions": [question]}, predictions, "fixed")
    assert wrong["path_tp"] == 0 and wrong["path_fn"] == 1
