"""Deterministic evidence-backed path diagnostics, with original edge direction."""
from collections import defaultdict
from hashlib import sha256
import json

from fig.expanded_experiment import edge_key, evidence_errors, ratio


def graph_from_cases(cases, predictions=None):
    graph = {}
    for case in cases:
        edges = case["expected"] if predictions is None else predictions.get(case["id"], [])
        for edge in edges:
            if evidence_errors(edge, case):
                continue
            key = edge_key(edge, case)
            entry = graph.setdefault(key, {"key": key, "citations": []})
            entry["citations"].append({"case_id": case["id"], "document_id": case["document_id"], "passage_id": case.get("passage_id"), "source_url": case.get("source_url"), "quote": edge["quote"]})
    return graph


def enumerate_paths(graph, source, target=None, hops=3):
    target = tuple(target) if target is not None else None
    adjacent = defaultdict(list)
    for key in graph:
        left, right = (key[0], key[1]), (key[3], key[4])
        adjacent[left].append((right, key, "forward"))
        adjacent[right].append((left, key, "reverse"))
    results = []
    def visit(node, visited, steps):
        if len(steps) == hops:
            if target is None or node == target:
                results.append(steps)
            return
        for neighbor, key, direction in sorted(adjacent[node]):
            if neighbor not in visited:
                visit(neighbor, visited | {neighbor}, steps + [{"edge": list(key), "traversal": direction}])
    visit(tuple(source), {tuple(source)}, [])
    return results


def path_signature(path):
    return json.dumps(path, sort_keys=True, separators=(",", ":"))


def generate_questions(cases, count_per_stratum=18):
    graph = graph_from_cases(cases)
    nodes = sorted({(key[0], key[1]) for key in graph} | {(key[3], key[4]) for key in graph})
    candidates = defaultdict(list)
    for source in nodes:
        for hops in (1, 2, 3):
            by_target = defaultdict(list)
            for path in enumerate_paths(graph, source, hops=hops):
                last = path[-1]
                key = last["edge"]
                target = (key[3], key[4]) if last["traversal"] == "forward" else (key[0], key[1])
                by_target[target].append(path)
            for target, paths in by_target.items():
                if source < target:  # No duplicate reverse-endpoint question.
                    candidates[f"{hops}_hop"].append((source, target, hops, paths))
        for target in nodes:
            if source < target and not any(enumerate_paths(graph, source, target, hops=hops) for hops in (1, 2, 3)):
                candidates["unsupported_or_underspecified"].append((source, target, 3, []))
    questions = []
    for stratum in ("1_hop", "2_hop", "3_hop", "unsupported_or_underspecified"):
        ranked = sorted(candidates[stratum], key=lambda item: sha256(json.dumps([stratum, item[0], item[1], 1729]).encode()).hexdigest())
        if len(ranked) < count_per_stratum:
            raise ValueError(f"insufficient distinct {stratum} questions: {len(ranked)}")
        for source, target, hops, paths in ranked[:count_per_stratum]:
            id = sha256(json.dumps([stratum, source, target]).encode()).hexdigest()[:20]
            question = f"Within the reviewed passage set, which disclosed relationship paths of exactly {hops} hops connect {source[0]} ({source[1]}) and {target[0]} ({target[1]})? Preserve each edge's asserted direction and cite every edge."
            if not paths:
                question = f"Within the reviewed passage set, is there an evidence-backed relationship path of at most three hops between {source[0]} ({source[1]}) and {target[0]} ({target[1]})? Abstain if no path is documented."
            questions.append({"id": id, "stratum": stratum, "question": question, "source": list(source), "target": list(target), "hops": hops,
                              "status": "supported" if paths else "unsupported_in_sample", "expected_paths": paths})
    return {"version": "expanded-graph-derived-qa-v1", "status": "diagnostic_references_not_independently_question_reviewed", "scope": "Disclosed relationships in the retained passage sample; no simultaneity, causal exposure, or real-world absence is asserted.",
            "traversal": "Both traversal directions allowed; reverse traversal never reverses the factual assertion.", "questions": questions}


def score_qa(cases, questions, prediction_rows, condition):
    predictions = {row["case_id"]: row["conditions"][condition]["accepted_edges"] for row in prediction_rows if row["conditions"][condition]["status"] == "completed"}
    graph = graph_from_cases(cases, predictions)
    reference = graph_from_cases(cases)
    gold_by_case = {case["id"]: {edge_key(edge, case): edge for edge in case["expected"]} for case in cases}
    rows, total_tp, total_fp, total_fn = [], 0, 0, 0
    citations, correct_citations, complete_paths = 0, 0, 0
    for question in questions["questions"]:
        actual = enumerate_paths(graph, question["source"], question["target"], question["hops"])
        if question["status"] == "unsupported_in_sample":
            actual = sum((enumerate_paths(graph, question["source"], question["target"], h) for h in (1, 2, 3)), [])
        expected = {path_signature(path) for path in question["expected_paths"]}
        predicted = {path_signature(path) for path in actual}
        valid_predictions = set()
        for path in actual:
            valid = True
            for step in path:
                key = tuple(step["edge"])
                supporting = graph[key]["citations"]
                edge_has_correct_citation = False
                for citation in supporting:
                    citations += 1
                    gold = gold_by_case[citation["case_id"]].get(key)
                    correct = gold is not None and gold["quote"] in citation["quote"]
                    correct_citations += correct
                    edge_has_correct_citation |= correct
                valid &= edge_has_correct_citation and key in reference
            if valid:
                complete_paths += 1
                valid_predictions.add(path_signature(path))
        tp = len(expected & valid_predictions)
        fp, fn = len(predicted) - tp, len(expected) - tp
        total_tp += tp
        total_fp += fp
        total_fn += fn
        rows.append({"question_id": question["id"], "stratum": question["stratum"], "expected_path_count": len(expected), "predicted_path_count": len(predicted), "supported_path_tp": tp, "fp": fp, "fn": fn,
                     "answer_exact": expected == valid_predictions and predicted == valid_predictions,
                     "abstained": not actual, "paths": [{"steps": path, "citations_per_edge": [graph[tuple(step["edge"])]["citations"] for step in path]} for path in actual]})
    negatives = [row for row in rows if row["stratum"] == "unsupported_or_underspecified"]
    return {"questions": len(rows), "coverage_complete": len(predictions) == len(cases), "path_tp": total_tp, "path_fp": total_fp, "path_fn": total_fn,
            "path_precision": ratio(total_tp, total_tp + total_fp), "path_recall": ratio(total_tp, total_tp + total_fn), "answer_exact_accuracy": ratio(sum(row["answer_exact"] for row in rows), len(rows)),
            "unsupported_abstention": ratio(sum(row["abstained"] for row in negatives), len(negatives)), "citation_correctness": ratio(correct_citations, citations),
            "citation_complete_predicted_paths": complete_paths, "predicted_citation_count": citations, "results": rows,
            "limitation": "Graph-derived diagnostic references; independent question-level double review was not performed. Strict reference-quote containment is used for supported-path credit."}
