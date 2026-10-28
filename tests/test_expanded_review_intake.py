"""Integrity checks for reviewer returns; fixtures are synthetic, not annotations."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import json
import shutil

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/intake_expanded_reviews.py"
spec = importlib.util.spec_from_file_location("review_intake", SCRIPT)
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)


class ReviewIntakeTests(unittest.TestCase):
    def test_cli_rejects_blank_real_packet_without_emitting_completed_files(self):
        source = SCRIPT.parents[1] / "evaluation/expanded/distribution/reviewer-2"
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "returns"
            folder.mkdir()
            for kind in ("relations", "ontology", "metadata"):
                shutil.copyfile(source / f"reviewer-2-{kind}.csv", folder / f"reviewer-2-{kind}.completed.csv")
            output = Path(temp) / "result"
            process = subprocess.run([sys.executable, str(SCRIPT), "--reviewer", "reviewer-2", "--returns", str(folder), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 1, process.stderr)
            report = json.loads((output / "validation-report.json").read_text())
            self.assertFalse(report["valid"])
            self.assertEqual(len(report["input_files"]), 3)
            self.assertFalse(list(output.glob("*.completed.csv")))
            retry = subprocess.run([sys.executable, str(SCRIPT), "--reviewer", "reviewer-2", "--returns", str(folder), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(retry.returncode, 2)
            self.assertIn("output already exists", retry.stderr)

    def test_chunks_restore_order_and_reject_gap_or_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            first = folder / "reviewer-1-relations.rows-001-002.completed.csv"
            last = folder / "reviewer-1-relations.rows-003-003.completed.csv"
            intake.write_csv(first, ["id"], [{"id": "a"}, {"id": "b"}])
            with self.assertRaisesRegex(ValueError, "missing final"):
                intake.collect_returns(folder, "reviewer-1", "relations", 3)
            intake.write_csv(last, ["id"], [{"id": "c"}])
            self.assertEqual([row["id"] for row in intake.collect_returns(folder, "reviewer-1", "relations", 3)[1]], ["a", "b", "c"])
            intake.write_csv(folder / "reviewer-1-relations.rows-002-003.completed.csv", ["id"], [{"id": "b"}, {"id": "c"}])
            with self.assertRaisesRegex(ValueError, "gap, overlap"):
                intake.collect_returns(folder, "reviewer-1", "relations", 3)

    def test_reordered_or_changed_source_rejected(self):
        originals = [{"packet_id": "a", "relation_verdict": ""}, {"packet_id": "b", "relation_verdict": ""}]
        with self.assertRaisesRegex(ValueError, "source/order"):
            intake.immutable_check(list(originals[0]), originals[::-1], list(originals[0]), originals, "relations")
        revised = [{**row, "relation_verdict": "unsupported"} for row in originals]
        intake.immutable_check(list(originals[0]), revised, list(originals[0]), originals, "relations")

    def relation(self):
        import json
        edge = {"subject_name": "Example", "predicate": "SUPPLIES_TO", "object_name": "Other", "quote": "Example supplies Other.", "subject_is_issuer": True, "polarity": "positive", "validity_note": ""}
        return {"text": "Example supplies Other.", "relation_verdict": "supported", "relationships_json": json.dumps([edge]), "identity_status": "documented", "ontology_disposition": "existing_concept", "reviewer_confidence": "4", "review_seconds": "5.5", "reviewer_notes": "Named endpoints."}

    def test_quote_must_be_contiguous_and_unsupported_empty(self):
        row = self.relation()
        intake.validate_row(row, "relations", set())
        row["text"] = "Example probably supplies Other."
        with self.assertRaisesRegex(ValueError, "contiguous"):
            intake.validate_row(row, "relations", set())
        row = self.relation()
        row["relation_verdict"] = "unsupported"
        with self.assertRaisesRegex(ValueError, r"require \[\]"):
            intake.validate_row(row, "relations", set())

    def test_nonfinite_times_and_invalid_metadata_rejected(self):
        row = self.relation()
        row["review_seconds"] = "NaN"
        with self.assertRaises(ValueError):
            intake.validate_row(row, "relations", set())
        with self.assertRaisesRegex(ValueError, "precedes"):
            intake.validate_metadata({"started_at_utc": "2026-10-01T02:00:00Z", "completed_at_utc": "2026-10-01T01:00:00Z"})
        with self.assertRaisesRegex(ValueError, "UTC timezone"):
            intake.validate_metadata({"started_at_utc": "2026-10-01T02:00:00", "completed_at_utc": "2026-10-01T03:00:00"})

    def test_ontology_endpoint_and_counterexample_checks(self):
        row = {"disposition": "new_predicate", "canonical_concept": "EXAMPLE", "corrected_definition": "Example definition.", "corrected_subject_types_json": '["Company"]', "corrected_object_types_json": "[]", "counterexample_passage_id": "", "reviewer_confidence": "4", "review_seconds": "2", "reviewer_notes": "Example."}
        with self.assertRaisesRegex(ValueError, "endpoint"):
            intake.validate_row(row, "ontology", set())
        row["corrected_object_types_json"] = '["Company"]'
        intake.validate_row(row, "ontology", set())
        row["counterexample_passage_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "absent"):
            intake.validate_row(row, "ontology", set())

    def test_synonym_merge_requires_target_not_replacement_definition(self):
        row = {"disposition": "synonym_merge", "canonical_concept": "", "merge_target": "EXISTING", "corrected_definition": "", "corrected_subject_types_json": "", "corrected_object_types_json": "", "counterexample_passage_id": "", "reviewer_confidence": "4", "review_seconds": "20", "reviewer_notes": "Use the existing concept."}
        intake.validate_row(row, "ontology", set())
        row["merge_target"] = ""
        with self.assertRaisesRegex(ValueError, "merge_target"):
            intake.validate_row(row, "ontology", set())

    def test_agreement_degenerate_kappa_not_reported_as_perfect(self):
        report = intake.agreement(["unsupported"] * 10, ["unsupported"] * 10)
        self.assertEqual(report["agreement"], 1)
        self.assertIsNone(report["cohen_kappa"])
        self.assertEqual(intake.agreement(["supported", "unsupported"], ["unsupported", "supported"])["cohen_kappa"], -1)

    def test_comparison_uses_overlap_and_ignores_edge_order(self):
        row = {**self.relation(), "packet_id": "shared"}
        a = {"relations": ([], [row, {**row, "packet_id": "a-only"}]), "ontology": ([], [])}
        b = {"relations": ([], [row, {**row, "packet_id": "b-only"}]), "ontology": ([], [])}
        report, candidates = intake.compare(a, b)
        self.assertEqual(report["relations"]["rows"], 1)
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
