import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import classify_reviews as classifier
import generate_insights as insights


class ResumeAndInsightsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.output = self.temp / "outputs" / "test" / "classification_qwen_resume.json"
        self.validation, self.reviews = classifier.load_reviews(classifier.DEFAULT_CSV)
        self.fixtures = json.loads((AGENT_DIR / "tests" / "fixtures" / "mock_classifications.json").read_text())
        self.network = patch.object(classifier.request, "build_opener", side_effect=AssertionError("Unexpected network"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.settings = patch.object(classifier, "load_local_settings", side_effect=AssertionError("Unexpected settings read"))
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def run_main(self, arguments):
        with patch.object(classifier, "AGENT_DIR", self.temp), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return classifier.main(arguments)

    def make_report(self, count=3, mode="qwen"):
        answers = [(self.fixtures[review["review_id"]]["classification"], {"total_tokens": 10}) for review in self.reviews[:count]]
        with patch.object(classifier, "classify_qwen", side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
            return classifier.analyze_batch(self.reviews[:count], self.validation, mode, "qwen-plus", self.output, fixtures=self.fixtures)

    def adopt_legacy(self):
        report = self.make_report()
        report["schema_version"] = "2.3"
        report.pop("classifier_signature")
        for result in report["results"]:
            result.pop("input_sha256")
        legacy = self.output.parent / "classification_qwen_batch.json"
        classifier.save_json(legacy, report)
        self.output.unlink()
        return legacy

    def test_legacy_migration_keeps_source_bytes_and_never_reads_settings(self):
        legacy = self.adopt_legacy()
        original = legacy.read_bytes()
        self.assertEqual(self.run_main(["--mode", "qwen", "--adopt-legacy", "--confirm-legacy-input"]), 0)
        self.assertEqual(legacy.read_bytes(), original)
        migrated = classifier.load_checkpoint(self.output, self.reviews, "qwen", "qwen-plus")
        self.assertEqual(len(migrated["results"]), 3)
        self.assertTrue(all(row["legacy_input_attested"] for row in migrated["results"]))
        before = self.output.read_bytes()
        self.assertEqual(self.run_main(["--mode", "qwen", "--adopt-legacy", "--confirm-legacy-input"]), 2)
        self.assertEqual(self.output.read_bytes(), before)

    def test_legacy_requires_explicit_confirmation(self):
        self.adopt_legacy()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_main(["--mode", "qwen", "--adopt-legacy"])
        self.assertFalse(self.output.exists())

    def test_resume_skips_first_three_merges_six_and_preserves_old_rows(self):
        previous = self.make_report()
        old_rows = copy.deepcopy(previous["results"])
        answers = [(self.fixtures[review["review_id"]]["classification"], {"total_tokens": 10}) for review in self.reviews[3:]]
        with patch.object(classifier, "load_local_settings", return_value={}), patch.object(classifier, "classify_qwen", side_effect=answers) as api:
            self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6"]), 0)
        self.assertEqual([call.args[0]["review_id"] for call in api.call_args_list], ["4", "5", "6", "7", "8", "9"])
        report = json.loads(self.output.read_text())
        self.assertEqual(report["results"][:3], old_rows)
        self.assertEqual(report["classified_records"], 9)
        self.assertEqual(report["skipped_records"], 3)
        self.assertEqual(report["new_success_records"], 6)
        self.assertEqual(report["usage"]["total_tokens"], 90)
        self.assertEqual(len({row["review_id"] for row in report["results"]}), 9)

    def test_resume_when_all_done_never_reads_settings_or_calls_api(self):
        self.make_report(9)
        self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6"]), 0)
        self.assertEqual(json.loads(self.output.read_text())["skipped_records"], 9)

    def test_dry_run_preserves_checkpoint(self):
        self.make_report()
        before = self.output.read_bytes()
        self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--dry-run", "--limit", "6"]), 0)
        self.assertEqual(self.output.read_bytes(), before)

    def test_resume_failure_keeps_successes_and_retries_only_unfinished_next_time(self):
        self.make_report()
        with patch.object(classifier, "load_local_settings", return_value={}), patch.object(classifier, "classify_qwen", side_effect=classifier.ClassificationError("Timeout", stop_batch=True)):
            self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6"]), 1)
        report = json.loads(self.output.read_text())
        self.assertEqual(len(report["results"]), 3)
        self.assertEqual(report["failures"][0]["review_id"], "4")
        self.assertEqual(report["unprocessed_records"], 5)
        with patch.object(classifier, "load_local_settings", return_value={}), patch.object(classifier, "classify_qwen", return_value=(self.fixtures["4"]["classification"], {})) as api:
            self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "1"]), 0)
        self.assertEqual(api.call_args.args[0]["review_id"], "4")
        self.assertEqual(len(json.loads(self.output.read_text())["failure_history"]), 1)

    def test_resume_rejects_changed_content_brand_model_schema_or_duplicate_id(self):
        baseline = self.make_report()
        variants = []
        for field, value in (("model", "other-model"), ("schema_version", "2.3"), ("classifier_signature", "changed")):
            report = copy.deepcopy(baseline)
            report[field] = value
            variants.append(report)
        for field, value in (("brand", "Brand B"), ("input_sha256", "changed"), ("sentiment", "Neutral")):
            report = copy.deepcopy(baseline)
            report["results"][0][field] = value
            variants.append(report)
        report = copy.deepcopy(baseline)
        report["results"].append(report["results"][0])
        variants.append(report)
        for report in variants:
            classifier.save_json(self.output, report)
            before = self.output.read_bytes()
            self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6"]), 2)
            self.assertEqual(self.output.read_bytes(), before)
        classifier.save_json(self.output, baseline)
        changed = copy.deepcopy(self.reviews)
        changed[0]["review_text"] += " Changed."
        with self.assertRaises(classifier.ClassificationError):
            classifier.load_checkpoint(self.output, changed, "qwen", "qwen-plus")

    def test_existing_qwen_file_is_not_overwritten(self):
        self.make_report()
        batch = self.output.parent / "classification_qwen_batch.json"
        batch.write_bytes(self.output.read_bytes())
        before = batch.read_bytes()
        self.assertEqual(self.run_main(["--mode", "qwen", "--limit", "3"]), 2)
        self.assertEqual(batch.read_bytes(), before)

    def test_mock_insights_nine_reviews_and_sample_counts(self):
        report = insights.generate_insights(self.make_report(9, "mock"))
        self.assertEqual(report["classified_sample_size"], 9)
        self.assertEqual(report["synthetic_records"], 9)
        self.assertEqual([report["brands"][brand]["sample_size"] for brand in insights.BRANDS], [3, 3, 3])
        self.assertEqual(report["brands"]["Brand C"]["aspect_counts"]["Maintenance"]["Positive"], 2)
        self.assertEqual(report["brands"]["Brand A"]["aspect_counts"]["Battery Life"]["Negative"], 1)
        self.assertEqual(len(report["comparison_table"]), 8)
        self.assertTrue(all(brand["comparison_status"] == "Insufficient Data" for brand in report["brands"].values()))

    def test_deduplicates_per_review_aspect_sentiment_and_pain_text(self):
        report = self.make_report(1, "mock")
        row = report["results"][0]
        aspect = row["product_aspects"][0]
        row["product_aspects"].extend([copy.deepcopy(aspect), {**aspect, "feedback": "Short battery runtime"}])
        row["pain_points"].extend([row["pain_points"][0], row["pain_points"][0].upper()])
        result = insights.generate_insights(report)["brands"]["Brand A"]
        self.assertEqual(result["aspect_counts"]["Battery Life"]["Negative"], 1)
        self.assertEqual(result["top_pain_points"][0]["review_count"], 1)
        self.assertEqual(result["top_negative_aspects"][0]["review_ids"], ["1"])

    def test_unknown_brand_excluded_and_duplicate_ids_rejected(self):
        report = self.make_report(1, "mock")
        report["results"][0]["brand"] = "unknown"
        result = insights.generate_insights(report)
        self.assertEqual(result["unknown_brand_records"], 1)
        self.assertEqual(result["brands"]["Brand A"]["sample_size"], 0)
        report["results"].append(copy.deepcopy(report["results"][0]))
        with self.assertRaises(classifier.ClassificationError):
            insights.generate_insights(report)

    def test_insights_cli_creates_separate_json_without_changing_source(self):
        self.make_report(9, "mock")
        original = self.output.read_bytes()
        with patch.object(insights, "AGENT_DIR", self.temp), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(insights.main(["--input", str(self.output)]), 0)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertTrue((self.temp / "outputs" / "test" / "insights_mock.json").exists())

    def test_moved_checkpoint_still_skips_all_completed_ids(self):
        self.make_report(9)
        original = self.output.read_bytes()
        with patch.object(classifier, "classify_qwen", side_effect=AssertionError("Unexpected API call")):
            self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6", "--dry-run"]), 0)
        self.assertEqual(self.output.read_bytes(), original)

    def test_old_root_checkpoint_is_found_without_api_or_settings(self):
        self.make_report(9)
        legacy = self.temp / "outputs" / self.output.name
        self.output.rename(legacy)
        original = legacy.read_bytes()
        self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6", "--dry-run"]), 0)
        self.assertEqual(legacy.read_bytes(), original)
        self.assertFalse(self.output.exists())

    def test_conflicting_old_new_checkpoints_refuse_resume(self):
        self.make_report(9)
        original = self.output.read_bytes()
        legacy = self.temp / "outputs" / self.output.name
        legacy.write_text("conflicting checkpoint")
        self.assertEqual(self.run_main(["--mode", "qwen", "--resume", "--limit", "6", "--dry-run"]), 2)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(legacy.read_text(), "conflicting checkpoint")

    def test_synthetic_input_cannot_enter_real_outputs(self):
        self.assertEqual(self.run_main(["--dataset", "real", "--mode", "qwen", "--limit", "3"]), 2)
        self.assertFalse((self.temp / "outputs" / "real").exists())
        self.make_report(9, "mock")
        with patch.object(insights, "AGENT_DIR", self.temp), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(insights.main(["--dataset", "real", "--input", str(self.output)]), 2)
        self.assertFalse((self.temp / "outputs" / "real").exists())

    def test_real_input_requires_explicit_real_dataset(self):
        self.make_report(1, "qwen")
        report = json.loads(self.output.read_text())
        report["results"][0]["is_synthetic"] = False
        report["results"][0]["source_platform"] = "authorized-reviews"
        classifier.save_json(self.output, report)
        with patch.object(insights, "AGENT_DIR", self.temp), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(insights.main(["--input", str(self.output)]), 2)
        with patch.object(insights, "AGENT_DIR", self.temp), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(insights.main(["--dataset", "real", "--input", str(self.output)]), 0)
        self.assertTrue((self.temp / "outputs" / "real" / "insights_qwen.json").exists())


if __name__ == "__main__":
    unittest.main()
