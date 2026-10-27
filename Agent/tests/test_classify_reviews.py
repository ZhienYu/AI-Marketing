import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib import error


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
SPEC = importlib.util.spec_from_file_location("classify_reviews", AGENT_DIR / "classify_reviews.py")
classifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(classifier)


class ClassifyReviewsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.review = {"review_id": "1", "review_text": "Good cleaning"}
        self.classification = {
            "sentiment": "Positive", "positive_aspects": ["Good cleaning"], "pain_points": [],
            "product_aspects": [{"aspect": "Cleaning Performance", "sentiment": "Positive", "feedback": "Good cleaning"}],
        }
        self.settings = {"DASHSCOPE_API_KEY": "fake-test-credential"}
        self.network = patch.object(classifier.request, "build_opener")
        self.opener_factory = self.network.start()
        self.addCleanup(self.network.stop)

    def respond(self, body):
        self.opener_factory.return_value.open.return_value.__enter__.side_effect = lambda: io.StringIO(json.dumps(body))

    def response_body(self):
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.classification)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "unexpected": "private"},
        }

    def run_main(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return classifier.main(arguments)

    def test_default_mock_nine_reviews_without_settings_or_network(self):
        fixture_path = AGENT_DIR / "tests" / "fixtures" / "mock_classifications.json"
        (self.temp / "tests" / "fixtures").mkdir(parents=True)
        (self.temp / "tests" / "fixtures" / fixture_path.name).write_bytes(fixture_path.read_bytes())
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.object(classifier, "load_local_settings") as settings:
            self.assertEqual(self.run_main([]), 0)
            settings.assert_not_called()
        self.opener_factory.assert_not_called()
        result = json.loads((self.temp / "outputs" / "test" / "classification_mock.json").read_text())
        self.assertEqual(result["classified_records"], 9)
        self.assertEqual([row["review_id"] for row in result["results"]], [str(number) for number in range(1, 10)])
        self.assertEqual([row["sentiment"] for row in result["results"]], ["Negative", "Positive", "Negative", "Mixed", "Positive", "Negative", "Positive", "Negative", "Mixed"])
        self.assertEqual(result["mode"], "mock")
        self.assertEqual(result["usage"], {})
        self.assertEqual([row["brand"] for row in result["results"]], ["Brand A"] * 3 + ["Brand B"] * 3 + ["Brand C"] * 3)
        self.assertTrue(all(row["is_synthetic"] for row in result["results"]))
        self.assertEqual(result["validation"]["evidence_eligible_records"], 0)
        expected = [
            [("Battery Life", "Negative")], [("Cleaning Performance", "Positive")],
            [("Maintenance", "Negative")], [("Ease of Use", "Positive"), ("Price", "Negative")],
            [("Battery Life", "Positive")], [("Reliability", "Negative")],
            [("Cleaning Performance", "Positive"), ("Maintenance", "Positive")],
            [("Customer Support", "Negative"), ("Price", "Negative")],
            [("Maintenance", "Positive"), ("Battery Life", "Negative")],
        ]
        for row, aspects in zip(result["results"], expected):
            self.assertEqual([(aspect["aspect"], aspect["sentiment"]) for aspect in row["product_aspects"]], aspects)
            self.assertTrue(all(aspect["feedback"].strip() for aspect in row["product_aspects"]))

    def test_live_mode_requires_explicit_capped_limit(self):
        for arguments in (["--mode", "qwen"], ["--mode", "qwen", "--limit", "21"], ["--limit", "0"]):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as failure:
                self.run_main(arguments)
            self.assertEqual(failure.exception.code, 2)
        self.opener_factory.assert_not_called()

    def test_qwen_request_and_schema(self):
        self.respond(self.response_body())
        classification, usage = classifier.classify_qwen(self.review, self.settings, "qwen-plus")
        self.assertEqual(classification, self.classification)
        self.assertEqual(usage, {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30})
        call = self.opener_factory.return_value.open.call_args
        self.assertEqual(call.args[0].full_url, classifier.BEIJING_BASE_URL + "/chat/completions")
        payload = json.loads(call.args[0].data)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["enable_thinking"])
        self.assertEqual(payload["max_tokens"], 1000)
        self.assertNotIn("fake-test-credential", call.args[0].data.decode())
        self.assertEqual(call.kwargs["timeout"], 60)
        self.opener_factory.return_value.open.assert_called_once()

    def test_live_main_calls_once_and_preserves_input_id(self):
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.object(classifier, "load_local_settings", return_value=self.settings):
            self.respond(self.response_body())
            self.assertEqual(self.run_main(["--mode", "qwen", "--limit", "1"]), 0)
        self.opener_factory.return_value.open.assert_called_once()
        output = (self.temp / "outputs" / "test" / "classification_qwen_one.json").read_text()
        self.assertNotIn("fake-test-credential", output)
        result = json.loads(output)
        self.assertEqual(result["results"][0]["review_id"], "1")
        self.assertEqual(result["classified_records"], 1)
        self.assertEqual(result["validation"]["valid_records"], 9)

    def test_invalid_and_duplicate_rows_are_not_sent(self):
        input_path = self.temp / "input.csv"
        with input_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["review_id", "review_text", "source_platform", "source_url", "brand"])
            writer.writerows([
                ["bad", "", "synthetic", "", "A"],
                ["kept", "Good cleaning", "synthetic", "", "A"],
                ["kept", "Good cleaning", "synthetic", "", "A"],
            ])
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.object(classifier, "load_local_settings", return_value=self.settings):
            self.respond(self.response_body())
            self.assertEqual(self.run_main(["--mode", "qwen", "--limit", "1", "--input", str(input_path)]), 0)
        result = json.loads((self.temp / "outputs" / "test" / "classification_qwen_one.json").read_text())
        self.assertEqual(result["results"][0]["review_id"], "kept")
        self.assertEqual(result["validation"]["invalid_records"], 1)
        self.assertEqual(result["validation"]["duplicate_records"], 1)

    def test_mock_refuses_changed_review(self):
        fixtures = json.loads((AGENT_DIR / "tests" / "fixtures" / "mock_classifications.json").read_text())
        with self.assertRaises(classifier.ClassificationError):
            classifier.classify_mock(self.review, fixtures)
        self.opener_factory.assert_not_called()

    def test_neutral_and_bad_schema(self):
        neutral = {"sentiment": "Neutral", "positive_aspects": [], "pain_points": [], "product_aspects": []}
        self.assertEqual(classifier.check_classification(neutral), neutral)
        invalid = [None, [], {}, {**neutral, "sentiment": "Happy"},
                   {**neutral, "sentiment": []}, {**neutral, "review_id": "invented"},
                   {**neutral, "positive_aspects": "Good"},
                   {**neutral, "pain_points": [2]}, {**neutral, "pain_points": [""]},
                   {**neutral, "sentiment": "Mixed"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(classifier.ClassificationError):
                classifier.check_classification(value)

    def test_missing_key_or_wrong_region_never_calls_network(self):
        for settings in ({}, {**self.settings, "DASHSCOPE_BASE_URL": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"},
                         {**self.settings, "DASHSCOPE_BASE_URL": "https://example.com"}):
            with self.subTest(settings=settings), self.assertRaises(classifier.ClassificationError):
                classifier.classify_qwen(self.review, settings, "qwen-plus")
        self.opener_factory.assert_not_called()

    def test_beijing_workspace_url(self):
        self.respond(self.response_body())
        classifier.classify_qwen(self.review, {**self.settings, "DASHSCOPE_BASE_URL": "https://test-workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"}, "qwen-plus")
        self.assertIn("test-workspace.cn-beijing", self.opener_factory.return_value.open.call_args.args[0].full_url)

    def test_errors_are_sanitized_and_not_retried(self):
        for failure in (error.HTTPError("https://example.com", 401, "private-body", {}, io.BytesIO(b"private-body")),
                        error.URLError("private-body"), TimeoutError("private-body")):
            with self.subTest(failure=type(failure)):
                self.opener_factory.return_value.open.reset_mock()
                self.opener_factory.return_value.open.side_effect = failure
                with self.assertRaises(classifier.ClassificationError) as raised:
                    classifier.classify_qwen(self.review, self.settings, "qwen-plus")
                self.assertNotIn("private-body", str(raised.exception))
                self.opener_factory.return_value.open.assert_called_once()

    def test_malformed_response_and_truncation_are_rejected(self):
        for body in ({}, {"choices": []}, {"choices": [{"finish_reason": "length"}]},
                     {"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]}):
            with self.subTest(body=body), self.assertRaises(classifier.ClassificationError):
                self.respond(body)
                classifier.classify_qwen(self.review, self.settings, "qwen-plus")

    def test_failed_live_run_saves_failure_without_inventing_result(self):
        output = self.temp / "outputs" / "test" / "classification_qwen_one.json"
        output.parent.mkdir(parents=True)
        self.respond({})
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.object(classifier, "load_local_settings", return_value=self.settings):
            self.assertEqual(self.run_main(["--mode", "qwen", "--limit", "1"]), 1)
        report = json.loads(output.read_text())
        self.assertEqual(report["results"], [])
        self.assertEqual(report["failed_records"], 1)
        self.assertEqual(report["failures"][0]["review_id"], "1")

    def test_settings_loader_uses_only_fake_temporary_file(self):
        (self.temp / ".env").write_text('export DASHSCOPE_API_KEY="fake-file-value"\nUNRELATED=ignored\n')
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.dict(classifier.os.environ, {}, clear=True):
            self.assertEqual(classifier.load_local_settings(), {"DASHSCOPE_API_KEY": "fake-file-value"})
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.dict(classifier.os.environ, {"DASHSCOPE_API_KEY": "fake-env-value"}, clear=True):
            self.assertEqual(classifier.load_local_settings()["DASHSCOPE_API_KEY"], "fake-env-value")

    def test_redirect_refused(self):
        with self.assertRaises(classifier.ClassificationError):
            classifier.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_empty_input_fails_before_settings_or_network(self):
        input_path = self.temp / "empty.csv"
        input_path.write_text("review_id,review_text,source_platform,source_url,brand\n")
        with patch.object(classifier, "load_local_settings") as settings:
            self.assertEqual(self.run_main(["--input", str(input_path), "--mode", "qwen", "--limit", "1"]), 2)
            settings.assert_not_called()
        self.opener_factory.assert_not_called()

    def sample_reviews(self):
        return classifier.load_reviews(classifier.DEFAULT_CSV)

    def test_multiple_qwen_requests_respect_limit_and_sum_usage(self):
        self.respond(self.response_body())
        with patch.object(classifier, "AGENT_DIR", self.temp), patch.object(classifier, "load_local_settings", return_value=self.settings):
            self.assertEqual(self.run_main(["--mode", "qwen", "--limit", "3"]), 0)
        self.assertEqual(self.opener_factory.return_value.open.call_count, 3)
        report = json.loads((self.temp / "outputs" / "test" / "classification_qwen_batch.json").read_text())
        self.assertEqual(report["usage"], {"prompt_tokens": 30, "completion_tokens": 60, "total_tokens": 90})
        self.assertEqual(report["usage_complete_records"], 3)
        self.assertEqual(report["usage_unknown_records"], 0)
        self.assertEqual(report["classified_records"], 3)
        self.assertEqual(report["unprocessed_records"], 0)
        self.assertEqual(report["status"], "completed")

    def test_malformed_classification_retains_tokens_and_continues(self):
        validation, reviews = self.sample_reviews()
        invalid = self.response_body()
        invalid["choices"][0]["message"]["content"] = "{}"
        responses = [self.response_body(), invalid, self.response_body()]

        def open_response(*args, **kwargs):
            response = Mock()
            response.__enter__ = Mock(return_value=io.StringIO(json.dumps(responses.pop(0))))
            response.__exit__ = Mock(return_value=False)
            return response

        self.opener_factory.return_value.open.side_effect = open_response
        report = classifier.analyze_batch(reviews[:3], validation, "qwen", "qwen-plus", self.temp / "batch.json", settings=self.settings)
        self.assertEqual([row["review_id"] for row in report["results"]], ["1", "3"])
        self.assertEqual(report["failures"][0]["review_id"], "2")
        self.assertNotIn("sentiment", report["failures"][0])
        self.assertEqual(report["usage"]["total_tokens"], 90)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["failed_records"], 1)

    def test_network_failure_stops_batch_and_keeps_prior_results(self):
        validation, reviews = self.sample_reviews()
        output = self.temp / "batch.json"
        with patch.object(classifier, "classify_qwen", side_effect=[
            (self.classification, {"total_tokens": 30}),
            classifier.ClassificationError("Connection timed out", stop_batch=True),
        ]) as classify:
            report = classifier.analyze_batch(reviews, validation, "qwen", "qwen-plus", output, settings=self.settings)
        self.assertEqual(classify.call_count, 2)
        self.assertEqual(report["classified_records"], 1)
        self.assertEqual(report["failed_records"], 1)
        self.assertEqual(report["unprocessed_records"], 7)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["usage_unknown_records"], 2)
        self.assertEqual(json.loads(output.read_text()), report)

    def test_http_errors_stop_batch_without_retry(self):
        validation, reviews = self.sample_reviews()
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.opener_factory.return_value.open.reset_mock()
                self.opener_factory.return_value.open.side_effect = error.HTTPError("https://example.com", status, "private", {}, io.BytesIO())
                report = classifier.analyze_batch(reviews, validation, "qwen", "qwen-plus", self.temp / "batch.json", settings=self.settings)
                self.opener_factory.return_value.open.assert_called_once()
                self.assertEqual(report["unprocessed_records"], 8)
                self.assertEqual(report["results"], [])

    def test_interrupt_leaves_checkpoint_of_finished_records(self):
        validation, reviews = self.sample_reviews()
        output = self.temp / "checkpoint.json"
        with patch.object(classifier, "classify_qwen", side_effect=[(self.classification, {}), KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                classifier.analyze_batch(reviews, validation, "qwen", "qwen-plus", output, settings=self.settings)
        report = json.loads(output.read_text())
        self.assertEqual(report["classified_records"], 1)
        self.assertEqual(report["status"], "running")

    def test_output_write_failure_prevents_further_requests(self):
        validation, reviews = self.sample_reviews()
        with patch.object(classifier, "save_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                classifier.analyze_batch(reviews, validation, "qwen", "qwen-plus", self.temp / "batch.json", settings=self.settings)
        self.opener_factory.assert_not_called()

    def test_product_aspect_schema_rejects_invalid_categories_and_polarities(self):
        valid = self.classification["product_aspects"][0]
        invalid_aspects = [
            "Battery Life", ["Battery Life"], [{**valid, "aspect": "Battery"}],
            [{**valid, "sentiment": "Mixed"}], [{**valid, "sentiment": []}],
            [{**valid, "feedback": " "}], [{**valid, "feedback": ["Good"]}],
            [{**valid, "extra": "field"}], [valid, valid], [],
        ]
        for aspects in invalid_aspects:
            with self.subTest(aspects=aspects), self.assertRaises(classifier.ClassificationError):
                classifier.check_classification({**self.classification, "product_aspects": aspects})

    def test_cleaning_positive_and_battery_negative(self):
        mixed = {
            "sentiment": "Mixed", "positive_aspects": ["Great cleaning"], "pain_points": ["Short battery life"],
            "product_aspects": [
                {"aspect": "Cleaning Performance", "sentiment": "Positive", "feedback": "Great cleaning"},
                {"aspect": "Battery Life", "sentiment": "Negative", "feedback": "Battery dies too quickly"},
            ],
        }
        self.assertEqual(classifier.check_classification(mixed), mixed)

    def test_neutral_other_and_opposite_sentiments_on_same_aspect(self):
        neutral = {
            "sentiment": "Neutral", "positive_aspects": [], "pain_points": [],
            "product_aspects": [{"aspect": "Other", "sentiment": "Neutral", "feedback": "Mentions product color without evaluation"}],
        }
        self.assertEqual(classifier.check_classification(neutral), neutral)
        mixed = {
            "sentiment": "Mixed", "positive_aspects": ["Good on floors"], "pain_points": ["Poor on walls"],
            "product_aspects": [
                {"aspect": "Cleaning Performance", "sentiment": "Positive", "feedback": "Good on floors"},
                {"aspect": "Cleaning Performance", "sentiment": "Negative", "feedback": "Poor on walls"},
            ],
        }
        self.assertEqual(classifier.check_classification(mixed), mixed)


if __name__ == "__main__":
    unittest.main()
