"""Validate complete returns or ordered chunks, then compare shared review rows.

Uses only the standard library; never calls an external service or changes inputs.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "evaluation/expanded/distribution"
FIELDS = {
    "relations": ["relation_verdict", "relationships_json", "identity_status", "ontology_disposition", "reviewer_confidence", "review_seconds", "reviewer_notes"],
    "ontology": ["disposition", "canonical_concept", "merge_target", "corrected_definition", "corrected_subject_types_json", "corrected_object_types_json", "counterexample_passage_id", "reviewer_confidence", "review_seconds", "reviewer_notes"],
    "metadata": ["started_at_utc", "completed_at_utc", "source_access_notes", "technical_notes"],
}
DISPOSITIONS = {"existing_concept", "synonym_merge", "subtype", "qualifier", "new_predicate", "new_entity_kind", "unsupported", "defer"}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"{path.name}: missing or duplicate headers")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"{path.name}: malformed CSV row")
        return fields, rows


def collect_returns(folder: Path, reviewer: str, kind: str, count: int) -> tuple[list[str], list[dict[str, str]], list[Path]]:
    full = list(folder.rglob(f"{reviewer}-{kind}.completed.csv"))
    chunks = list(folder.rglob(f"{reviewer}-{kind}.rows-*.completed.csv"))
    if full and chunks:
        raise ValueError(f"{kind}: full file and chunks both supplied; choose one")
    if len(full) == 1:
        fields, rows = read_csv(full[0])
        return fields, rows, full
    if full or not chunks:
        raise ValueError(f"{kind}: expected one completed file or complete chunk set")
    ranges = []
    for path in chunks:
        match = re.fullmatch(re.escape(f"{reviewer}-{kind}") + r"\.rows-(\d+)-(\d+)\.completed\.csv", path.name)
        if not match:
            raise ValueError(f"invalid chunk name: {path.name}")
        ranges.append((int(match[1]), int(match[2]), path))
    fields, rows, paths = [], [], []
    next_row = 1
    for start, end, path in sorted(ranges):
        header, chunk = read_csv(path)
        if start != next_row or end < start or end > count or len(chunk) != end - start + 1:
            raise ValueError(f"{path.name}: gap, overlap, or incorrect range/count")
        if fields and header != fields:
            raise ValueError(f"{path.name}: headers differ across chunks")
        fields = header
        rows.extend(chunk)
        paths.append(path)
        next_row = end + 1
    if next_row != count + 1:
        raise ValueError(f"{kind}: missing final rows {next_row}-{count}")
    return fields, rows, paths


def immutable_check(fields, rows, expected_fields, expected_rows, kind):
    if fields != expected_fields or len(rows) != len(expected_rows):
        raise ValueError(f"{kind}: header or row count changed")
    source_fields = [field for field in fields if field not in FIELDS[kind]]
    for index, (row, original) in enumerate(zip(rows, expected_rows), 1):
        changed = [field for field in source_fields if row[field] != original[field]]
        if changed:
            raise ValueError(f"{kind} row {index}: changed source/order: {', '.join(changed)}")


def json_list(value: str, name: str) -> list:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"{name} must be a JSON list")
    return parsed


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_row(row: dict[str, str], kind: str, evidence_ids: set[str]):
    confidence = int(row["reviewer_confidence"])
    seconds = float(row["review_seconds"])
    if confidence not in range(1, 6) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("confidence must be 1-5 and review_seconds finite and nonnegative")
    if not nonempty(row["reviewer_notes"]):
        raise ValueError("reviewer_notes is blank")
    if kind == "relations":
        verdict = row["relation_verdict"]
        if verdict not in {"supported", "unsupported", "ambiguous"}:
            raise ValueError("invalid relation_verdict")
        if not nonempty(row["identity_status"]) or not nonempty(row["ontology_disposition"]):
            raise ValueError("identity_status and ontology_disposition are required")
        relationships = json_list(row["relationships_json"], "relationships_json")
        if verdict == "unsupported" and relationships:
            raise ValueError("unsupported rows require []")
        if verdict == "supported" and not relationships:
            raise ValueError("supported row requires at least one relationship")
        for relationship in relationships:
            required = {"subject_name", "predicate", "object_name", "quote", "subject_is_issuer", "polarity", "validity_note"}
            if not isinstance(relationship, dict) or not required <= relationship.keys():
                raise ValueError("relationship object missing required keys")
            if any(not nonempty(relationship[key]) for key in required - {"subject_is_issuer", "validity_note"}):
                raise ValueError("relationship endpoints, predicate, polarity, and quote must be nonempty strings")
            if type(relationship["subject_is_issuer"]) is not bool or not isinstance(relationship["validity_note"], str):
                raise ValueError("subject_is_issuer must be boolean; validity_note must be text")
            if relationship["quote"] not in row["text"]:
                raise ValueError("quote is not an exact contiguous substring of the supplied passage")
    else:
        disposition = row["disposition"]
        if disposition not in DISPOSITIONS:
            raise ValueError("invalid disposition")
        # A merge selects an existing target, rather than defining a new concept.
        # The guide separately requires merge_target for that disposition.
        accepted = disposition not in {"unsupported", "defer", "synonym_merge"}
        if accepted and any(not nonempty(row[key]) for key in ("canonical_concept", "corrected_definition")):
            raise ValueError("accepted/corrected concepts require canonical_concept and corrected_definition")
        for field in ("corrected_subject_types_json", "corrected_object_types_json"):
            if not row[field] and not accepted:
                continue
            types = json_list(row[field], field)
            if any(not nonempty(value) for value in types):
                raise ValueError(f"{field} requires strings")
            if disposition == "new_predicate" and not types:
                raise ValueError("new_predicate requires both endpoint type lists")
        if disposition == "synonym_merge" and not nonempty(row["merge_target"]):
            raise ValueError("synonym_merge requires merge_target")
        if row["counterexample_passage_id"] and row["counterexample_passage_id"] not in evidence_ids:
            raise ValueError("counterexample passage is absent from supplied evidence")


def validate_metadata(row):
    times = []
    for key in ("started_at_utc", "completed_at_utc"):
        time = datetime.fromisoformat(row[key].replace("Z", "+00:00"))
        if time.tzinfo is None or time.utcoffset() != timedelta(0):
            raise ValueError(f"{key} must include UTC timezone")
        times.append(time)
    if times[1] < times[0]:
        raise ValueError("completion precedes start")


def intake(reviewer: str, folder: Path, source: Path):
    result, errors, provenance = {}, [], []
    _, evidence = read_csv(source / "ontology-evidence.csv")
    evidence_ids = {row["passage_id"] for row in evidence}
    for kind in FIELDS:
        try:
            header, originals = read_csv(source / f"{reviewer}-{kind}.csv")
            fields, rows, paths = collect_returns(folder, reviewer, kind, len(originals))
            immutable_check(fields, rows, header, originals, kind)
            for index, row in enumerate(rows, 1):
                try:
                    if kind == "metadata":
                        validate_metadata(row)
                    else:
                        validate_row(row, kind, evidence_ids)
                except (ValueError, TypeError, KeyError) as exc:
                    errors.append(f"{kind} row {index}: {exc}")
            result[kind] = (fields, rows)
            provenance.extend({"path": str(path.resolve()), "sha256": sha256(path.read_bytes()).hexdigest()} for path in paths)
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    return result, errors, provenance


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def agreement(left: list[str], right: list[str]):
    count = len(left)
    if not count:
        return {"rows": 0, "agreement": None, "cohen_kappa": None}
    observed = sum(a == b for a, b in zip(left, right)) / count
    expected = sum(left.count(label) * right.count(label) for label in set(left + right)) / count**2
    return {"rows": count, "agreement": observed, "cohen_kappa": (observed - expected) / (1 - expected) if expected < 1 else None}


def relation_signature(row, quote=False):
    keys = ["subject_name", "predicate", "object_name", "subject_is_issuer", "polarity"]
    if quote:
        keys.append("quote")
    return sorted(set(json.dumps([edge[key] for key in keys], ensure_ascii=False) for edge in json.loads(row["relationships_json"])))


def compare(a, b):
    report, disagreements = {}, []
    for kind, id_field, label in (("relations", "packet_id", "relation_verdict"), ("ontology", "proposal_id", "disposition")):
        first = {row[id_field]: row for row in a[kind][1]}
        second = {row[id_field]: row for row in b[kind][1]}
        shared = sorted(first.keys() & second.keys())
        report[kind] = agreement([first[key][label] for key in shared], [second[key][label] for key in shared])
        substantive = 0
        for key in shared:
            left, right = first[key], second[key]
            if kind == "relations":
                differs = left[label] != right[label] or relation_signature(left) != relation_signature(right)
            else:
                compare_fields = ["disposition", "canonical_concept", "merge_target", "corrected_definition", "corrected_subject_types_json", "corrected_object_types_json"]
                differs = any(left[field] != right[field] for field in compare_fields)
            substantive += differs
            if differs:
                disagreements.append({"kind": kind, "row_id": key, "reviewer_1": left, "reviewer_2": right, "decision": "", "adjudication_notes": ""})
        report[kind]["substantive_disagreements"] = substantive
        if kind == "relations":
            report[kind]["edge_set_agreement"] = sum(relation_signature(first[key]) == relation_signature(second[key]) for key in shared) / len(shared) if shared else None
            report[kind]["edge_and_quote_agreement"] = sum(relation_signature(first[key], True) == relation_signature(second[key], True) for key in shared) / len(shared) if shared else None
    return report, disagreements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", required=True, choices=("reviewer-1", "reviewer-2"))
    parser.add_argument("--returns", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New directory; existing paths are never overwritten")
    parser.add_argument("--other-returns", type=Path, help="Optional other reviewer return directory for shared-row agreement")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new directory")
    result, errors, files = intake(args.reviewer, args.returns, DIST / args.reviewer)
    report = {"reviewer": args.reviewer, "valid": not errors, "errors": errors, "input_files": files}
    other = None
    if args.other_returns:
        other_id = "reviewer-2" if args.reviewer == "reviewer-1" else "reviewer-1"
        other, other_errors, other_files = intake(other_id, args.other_returns, DIST / other_id)
        report["other_reviewer"] = {"reviewer": other_id, "valid": not other_errors, "errors": other_errors, "input_files": other_files}
        report["valid"] = report["valid"] and not other_errors
    args.output.mkdir(parents=True)
    if report["valid"]:
        for kind, (fields, rows) in result.items():
            write_csv(args.output / f"{args.reviewer}-{kind}.completed.csv", fields, rows)
        if other is not None:
            first, second = (result, other) if args.reviewer == "reviewer-1" else (other, result)
            report["agreement"], disagreements = compare(first, second)
            (args.output / "adjudication-candidates.json").write_text(json.dumps(disagreements, indent=2, ensure_ascii=False) + "\n")
    (args.output / "validation-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"valid": report["valid"], "report": str(args.output / "validation-report.json"), "errors": len(errors)}))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
