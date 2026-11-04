"""Synthetic-only needs discovery and opt-in Qwen contract tests."""
import copy
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import consumer_needs as needs
import classify_reviews as classifier
import orchestrator


class NeedsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(classifier, "classify_qwen", side_effect=AssertionError("No paid calls")), patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No keys")):
            self.path = needs.run_mock_research("improvement", output_root=Path(self.temp.name))
        root = self.path.parent
        self.research = json.loads((root / "consumer_needs.json").read_text())
        self.classified = json.loads((root / "classifications.json").read_text())
        with (root / "synthetic_reviews.csv").open(newline="") as handle:
            self.reviews = list(csv.DictReader(handle))
        self.review = next(r for r in self.reviews if r["review_id"] == "youtube:pipeline-02")
        self.value = self.research["envelopes"]["youtube:pipeline-02"]

    def test_two_templates_reuse_existing_report_and_evidence(self):
        for purpose in needs.PURPOSES:
            report = needs.render_research_report(purpose, self.research, self.classified, self.reviews)
            self.assertIn(needs.PURPOSES[purpose], report)
            for text in ("SYNTHETIC DATA", "Sources & Methodology", "Insufficient Data", "youtube:pipeline-02", "ai_inference", "raw_feedback"):
                self.assertIn(text, report)
            self.assertNotIn("https://www.youtube.com", report)

    def test_empty_dimensions_are_not_fabricated(self):
        self.assertTrue(all(not v for v in self.research["envelopes"]["youtube:pipeline-01"]["consumer_needs"].values()))
        self.assertEqual(self.research["coverage"], {"classified": 3, "needs_reviewed": 3})

    def test_invalid_quote_or_missing_uncertainty_rejected(self):
        for field, text in (("quote", "invented quotation"), ("uncertainty", ""), ("validation_step", "")):
            value = copy.deepcopy(self.value)
            value["consumer_needs"]["unmet_needs"][0][field] = text
            with self.assertRaises(classifier.ClassificationError):
                needs.check_research_output(value, self.review)

    def test_inference_cannot_masquerade_as_original(self):
        value = copy.deepcopy(self.value)
        value["consumer_needs"]["unmet_needs"][0]["claim_type"] = "raw_feedback"
        with self.assertRaises(classifier.ClassificationError):
            needs.check_research_output(value, self.review)

    def test_tampered_report_findings_rejected(self):
        value = copy.deepcopy(self.research)
        value["findings"][0]["text"] = "Invented commercial conclusion"
        with self.assertRaises(classifier.ClassificationError):
            needs.render_research_report("competitor", value, self.classified, self.reviews)

    def test_missing_or_unqualified_evidence_rejected(self):
        for rid in ("absent-id", "youtube:pipeline-03"):
            envelopes = {rid: self.value}
            with self.assertRaises(classifier.ClassificationError):
                needs.research_insights(self.classified, self.reviews, envelopes, self.research["qualification"])

    def test_real_research_qwen_rejected_before_credentials_or_http(self):
        with patch.object(classifier.request, "build_opener", side_effect=AssertionError("No HTTP")) as opener:
            with self.assertRaises(classifier.ClassificationError):
                classifier.classify_qwen({**self.review, "source_platform": "youtube"}, {}, "qwen-plus", research=True)
            opener.assert_not_called()

    def test_opt_in_qwen_envelope_and_token_usage_with_mock_transport(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.value)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}
        with patch.object(classifier.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            result, usage = classifier.classify_qwen(self.review, {"DASHSCOPE_API_KEY": "FAKE_TEST_KEY"}, "qwen-plus", research=True)
            sent = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(result, self.value)
        self.assertEqual(usage["total_tokens"], 30)
        self.assertIn(needs.RESEARCH_PROMPT, sent["messages"][0]["content"])
        self.assertEqual(json.loads(sent["messages"][1]["content"]), {"review_text": self.review["review_text"]})

    def test_duplicate_claim_not_counted_twice_and_unknown_preserved(self):
        envelopes = copy.deepcopy(self.research["envelopes"])
        claims = envelopes["youtube:pipeline-02"]["consumer_needs"]["specific_pain_points"]
        claims.append(copy.deepcopy(claims[0]))
        result = needs.research_insights(self.classified, self.reviews, envelopes, self.research["qualification"])
        self.assertEqual(len(result["findings"]), len(self.research["findings"]))


if __name__ == "__main__":
    unittest.main()
