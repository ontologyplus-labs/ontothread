"""Four-condition offline benchmark with exact identity and paired edge scoring.

Providers receive source text and condition policy only. Gold labels remain in
the scorer. This module makes no network or database calls.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
import random
from time import perf_counter

CONDITIONS = ("fixed_finance_v2", "unconstrained_generated", "controlled_evolving", "oracle")
EDGE_FIELDS = {"subject_name", "subject_kind", "predicate", "object_name", "object_kind", "quote"}
PROMPT_FAMILY = "expanded-source-only-v1"


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def ratio(a, b):
    return a / b if b else None


def validate_edge(edge):
    if not isinstance(edge, dict) or set(edge) != EDGE_FIELDS:
        raise ValueError("edge must contain exactly the six named endpoint, kind, predicate, and quote fields")
    if any(not isinstance(value, str) or not value.strip() for value in edge.values()):
        raise ValueError("all edge fields must be nonempty strings")


def validate_spec(spec, *, release_verified=False):
    if spec.get("partition") != "development" and not (release_verified and spec.get("partition") == "retrospective_evaluation"):
        raise ValueError("this runner permits development only unless a retrospective release is verified; sealed execution is not enabled")
    cases = spec.get("cases", [])
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("nonempty cases with unique IDs required")
    for case in cases:
        if not case.get("document_id") or not case.get("issuer_name"):
            raise ValueError("document_id and issuer_name required")
        if sha256(case["text"].encode()).hexdigest() != case["text_hash"]:
            raise ValueError("source text hash mismatch")
        for edge in case["expected"]:
            validate_edge(edge)
            if case["text"].count(edge["quote"]) != 1:
                raise ValueError("reference quote must occur exactly once in source")
        aliases(case)  # Reject undocumented identity mappings before scoring.
        if len({edge_key(edge, case) for edge in case["expected"]}) != len(case["expected"]):
            raise ValueError("duplicate reference relation")


def aliases(case):
    mapping = {}
    for item in case.get("documented_aliases", []):
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ("alias", "canonical", "quote")):
            raise ValueError("alias requires alias, canonical, and exact evidence quote")
        if item["quote"] not in case["text"] or item["alias"] not in item["quote"] or item["canonical"] not in item["quote"]:
            raise ValueError("alias is not documented in supplied passage")
        if item["alias"] in mapping and mapping[item["alias"]] != item["canonical"]:
            raise ValueError("conflicting alias mapping")
        mapping[item["alias"]] = item["canonical"]
    if any(name in mapping and mapping[name] != name for name in mapping.values()):
        raise ValueError("chained alias mappings are unsupported")
    return mapping


def edge_key(edge, case):
    mapping = aliases(case)
    return (mapping.get(edge["subject_name"], edge["subject_name"]), edge["subject_kind"], edge["predicate"], mapping.get(edge["object_name"], edge["object_name"]), edge["object_kind"])


def evidence_errors(edge, case):
    errors = []
    if case["text"].count(edge["quote"]) != 1:
        errors.append("quote_not_unique_contiguous_source")
    for field in ("subject_name", "object_name"):
        if edge[field] != case["issuer_name"] and edge[field] not in edge["quote"]:
            errors.append("endpoint_absent_from_quote")
    return errors


def schema_errors(edge, snapshot):
    if snapshot is None:
        return []
    rule = snapshot["definitions"]["predicates"].get(edge["predicate"])
    if rule is None:
        return ["undefined_predicate"]
    return (["invalid_subject_kind"] if edge["subject_kind"] not in rule["subject"] else []) + (["invalid_object_kind"] if edge["object_kind"] not in rule["object"] else [])


def score_edges(case, edges):
    gold = {edge_key(edge, case): edge for edge in case["expected"]}
    predictions = defaultdict(list)
    for edge in edges:
        validate_edge(edge)
        predictions[edge_key(edge, case)].append(edge)
    supported = {key for key, candidates in predictions.items() if key in gold and any(not evidence_errors(edge, case) and gold[key]["quote"] in edge["quote"] for edge in candidates)}
    wrong_direction = sum((key[3], key[4], key[2], key[0], key[1]) in gold and key not in gold for key in predictions)
    known_names = {name for key in gold for name in (key[0], key[3])}
    mismatches = sum(key not in gold and any(name not in known_names for name in (key[0], key[3])) for key in predictions) if gold else 0
    return {"tp": len(supported), "fp": len(predictions) - len(supported), "fn": len(gold) - len(supported),
            "gold": len(gold), "predicted": len(predictions), "invalid_evidence": sum(bool(evidence_errors(edge, case)) for edge in edges),
            "duplicate_predictions": len(edges) - len(predictions), "wrong_direction": wrong_direction,
            "endpoint_mismatch_candidates": mismatches, "negative_cases": int(not gold), "negative_correct": int(not gold and not edges)}


def summarize(scores):
    counts = Counter()
    for score in scores:
        counts.update(score)
    if not scores:
        return {"cases": 0, "precision": None, "recall": None, "f1": None}
    return {**dict(counts), "cases": len(scores), "precision": ratio(counts["tp"], counts["tp"] + counts["fp"]),
            "recall": ratio(counts["tp"], counts["gold"]), "f1": ratio(2 * counts["tp"], 2 * counts["tp"] + counts["fp"] + counts["fn"]),
            "negative_case_accuracy": ratio(counts["negative_correct"], counts["negative_cases"])}


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    low = int(position)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)


def paired_bootstrap(rows, iterations=10000, seed=1729):
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    clusters = defaultdict(list)
    for row in rows:
        if all(row["conditions"][condition]["status"] == "completed" for condition in CONDITIONS):
            clusters[row["document_id"]].append(row)
    names = sorted(clusters)
    # Resample document totals rather than repeating per-edge work 10,000 times.
    totals = {name: {condition: summarize([row["conditions"][condition]["score"] for row in clusters[name]]) for condition in (CONDITIONS[0], CONDITIONS[2])} for name in names}
    recall, precision = [], []
    rng = random.Random(seed)
    for _ in range(iterations if names else 0):
        sample = rng.choices(names, k=len(names))
        metrics = []
        for condition in (CONDITIONS[0], CONDITIONS[2]):
            counts = Counter()
            for name in sample:
                for field in ("tp", "fp", "gold"):
                    counts[field] += totals[name][condition][field]
            metrics.append((ratio(counts["tp"], counts["gold"]), ratio(counts["tp"], counts["tp"] + counts["fp"])))
        if all(item[0] is not None for item in metrics):
            recall.append(metrics[1][0] - metrics[0][0])
        if all(item[1] is not None for item in metrics):
            precision.append(metrics[1][1] - metrics[0][1])
    return {"iterations": iterations, "seed": seed, "document_clusters": len(names), "paired_cases": sum(map(len, clusters.values())),
            "successful_recall_resamples": len(recall), "successful_precision_resamples": len(precision),
            "recall_delta_ci95": [quantile(recall, .025), quantile(recall, .975)], "precision_delta_ci95": [quantile(precision, .025), quantile(precision, .975)],
            "warning": "Fewer than two document clusters cannot estimate cross-document uncertainty." if len(names) < 2 else None}


def run_benchmark(spec, policies, provider, *, iterations=10000, seed=1729, prices=None, release_verified=False):
    validate_spec(spec, release_verified=release_verified)
    if set(policies) != set(CONDITIONS) or policies[CONDITIONS[1]].get("snapshot") is not None:
        raise ValueError("exactly four policies required; unconstrained_generated must have no constrained snapshot")
    for condition in (CONDITIONS[0], CONDITIONS[2], CONDITIONS[3]):
        snapshot = policies[condition].get("snapshot")
        if not snapshot or not snapshot.get("definitions", {}).get("predicates"):
            raise ValueError(f"{condition} requires explicit ontology snapshot")
    if policies[CONDITIONS[0]]["snapshot"]["version"] != "finance-v2":
        raise ValueError("fixed condition must use finance-v2")
    if prices is not None and (set(prices) != {"input_per_million", "output_per_million"} or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in prices.values())):
        raise ValueError("prices must contain finite nonnegative per-million rates")
    rows = []
    for case in spec["cases"]:
        row = {"case_id": case["id"], "document_id": case["document_id"], "issuer_name": case["issuer_name"], "conditions": {}}
        source = {key: case[key] for key in ("id", "issuer_name", "text", "text_hash")}
        for condition in CONDITIONS:
            start = perf_counter()
            try:
                edges, metadata = provider(dict(source), condition, json.loads(json.dumps(policies[condition])))
                if not isinstance(edges, list):
                    raise ValueError("provider output must be a list")
                if not isinstance(metadata, dict):
                    raise ValueError("provider metadata must be an object")
                for edge in edges:
                    validate_edge(edge)
                accepted, rejected = [], []
                for edge in edges:
                    reasons = evidence_errors(edge, case) + schema_errors(edge, policies[condition].get("snapshot"))
                    if reasons:
                        rejected.append({"edge": edge, "reasons": reasons})
                    else:
                        accepted.append(edge)
                row["conditions"][condition] = {"status": "completed", "raw_edges": edges, "accepted_edges": accepted, "rejections": rejected,
                    "raw_score": score_edges(case, edges), "score": score_edges(case, accepted), "metadata": metadata, "latency_seconds": metadata.get("provider_latency_seconds", perf_counter() - start)}
            except (ValueError, RuntimeError) as exc:
                # Failed calls remain missing, not successful empty predictions.
                row["conditions"][condition] = {"status": "failed", "error_type": type(exc).__name__, "latency_seconds": perf_counter() - start}
        rows.append(row)
    metrics = {}
    for condition in CONDITIONS:
        completed = [row for row in rows if row["conditions"][condition]["status"] == "completed"]
        by_issuer = defaultdict(list)
        by_predicate = defaultdict(list)
        for row in completed:
            record = row["conditions"][condition]
            by_issuer[row["issuer_name"]].append(record["score"])
            case = next(case for case in spec["cases"] if case["id"] == row["case_id"])
            predicates = {edge["predicate"] for edge in case["expected"] + record["accepted_edges"]}
            for predicate in predicates:
                subset = {**case, "expected": [edge for edge in case["expected"] if edge["predicate"] == predicate]}
                by_predicate[predicate].append(score_edges(subset, [edge for edge in record["accepted_edges"] if edge["predicate"] == predicate]))
        issuer_metrics = {name: summarize(scores) for name, scores in by_issuer.items()}
        usage = Counter()
        known_usage = 0
        for row in completed:
            data = row["conditions"][condition]["metadata"].get("usage")
            if isinstance(data, dict) and all(isinstance(data.get(key), int) and data[key] >= 0 for key in ("input_tokens", "output_tokens")):
                known_usage += 1
                usage.update({key: data[key] for key in ("input_tokens", "output_tokens")})
        latencies = [row["conditions"][condition]["latency_seconds"] for row in completed]
        baseline_definitions = policies[CONDITIONS[0]]["snapshot"]["definitions"]
        raw_edges = [edge for row in completed for edge in row["conditions"][condition]["raw_edges"]]
        labels = sorted({edge["predicate"] for edge in raw_edges})
        endpoint_violations = sum(any(reason.startswith("invalid_") for reason in schema_errors(edge, policies[condition].get("snapshot"))) for edge in raw_edges)
        macro = {}
        for name in ("precision", "recall", "f1"):
            values = [value[name] for value in issuer_metrics.values() if value[name] is not None]
            macro[name] = {"value": sum(values) / len(values) if values else None, "defined_issuers": len(values)}
        metrics[condition] = {"completed_cases": len(completed), "missing_cases": len(rows) - len(completed), "coverage": len(completed) / len(rows),
            "accepted": summarize([row["conditions"][condition]["score"] for row in completed]), "raw": summarize([row["conditions"][condition]["raw_score"] for row in completed]),
            "issuer_metrics": issuer_metrics, "issuer_macro": macro, "predicate_metrics": {name: summarize(scores) for name, scores in by_predicate.items()},
            "validation_rejections": sum(len(row["conditions"][condition]["rejections"]) for row in completed),
            "schema_diagnostics": {"unique_predicate_labels": labels, "labels_outside_fixed_ontology": sorted(set(labels) - baseline_definitions["predicates"].keys()),
                "endpoint_constraint_violations": endpoint_violations if condition != "unconstrained_generated" else None,
                "concept_quality_status": "requires adjudicated ontology decisions; novelty alone is not an error"},
            "usage": {"known_cases": known_usage, "tokens": dict(usage) if known_usage else None},
            "estimated_cost_usd": (usage["input_tokens"] * prices["input_per_million"] + usage["output_tokens"] * prices["output_per_million"]) / 1e6 if prices and known_usage == len(completed) and completed else None,
            "actual_paid_cost_usd": sum(row["conditions"][condition]["metadata"]["billed_cost_usd"] for row in completed) if completed and all("billed_cost_usd" in row["conditions"][condition]["metadata"] for row in completed) else None,
            "latency_seconds": {"median": quantile(latencies, .5), "p95": quantile(latencies, .95)}}
    paired = [row for row in rows if all(row["conditions"][condition]["status"] == "completed" for condition in CONDITIONS)]
    baseline, treatment = [summarize([row["conditions"][condition]["score"] for row in paired]) for condition in (CONDITIONS[0], CONDITIONS[2])]
    def delta(name):
        return treatment[name] - baseline[name] if baseline[name] is not None and treatment[name] is not None else None
    precision_delta = delta("precision")
    complete = len(paired) == len(rows)
    return {"version": "expanded-development-runner-v1", "partition": spec["partition"], "publication_ready": False,
        "status": "completed" if complete else "incomplete", "spec_sha256": digest(spec), "policies_sha256": digest(policies), "prompt_family": PROMPT_FAMILY,
        "provider_model": provider.model, "conditions": metrics, "results": rows,
        "paired_effects": {"paired_cases": len(paired), "recall_delta": delta("recall"), "precision_delta": precision_delta,
            "precision_noninferiority_margin": -.05, "precision_guardrail_pass": precision_delta >= -.05 if precision_delta is not None and complete else None},
        "uncertainty": paired_bootstrap(rows, iterations, seed), "price_assumptions": prices,
        "limitations": ["Development data only; this is not a sealed benchmark result.", "Supported scoring requires the reference quote to be contained in the prediction quote; semantically equivalent quotes may need separate adjudication.", "Endpoint mismatch candidates are diagnostics, not adjudicated identity errors.", "No schema-quality or question-answering conclusions follow from relation scoring alone."] + spec.get("limitations", [])}
