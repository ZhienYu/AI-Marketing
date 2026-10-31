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
import qualify_feedback as qualification


class QualifyFeedbackTests(unittest.TestCase):
    def qualify(self, text, **fields):
        return qualification.qualify_feedback({"review_id": "synthetic-unit-1", "review_text": text, "is_synthetic": True, **fields})

    def test_explicit_use_is_self_reported_not_verified_purchase(self):
        result = self.qualify("I used DemoAqua R1 for a week. Its battery is excellent.")
        self.assertEqual(result["primary_type"], "Actual Usage Experience")
        self.assertEqual(result["usage_evidence"]["status"], "self_reported")
        self.assertFalse(result["usage_evidence"]["verified_purchase"])
        self.assertTrue(result["eligible_as_usage_review"])
        self.assertEqual(result["brand"], "DemoAqua")
        self.assertEqual(result["feedback_scope"], "product")
        self.assertEqual(result["product_sentiment"], "Positive")

    def test_price_and_expensive_questions_are_not_negative(self):
        for text in ("price?", "How much?", "Is DemoAqua R1 expensive?", "Does the battery last long?", "Where can I buy DemoPool X2?"):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertIn("Purchase Inquiry", result["feedback_types"])
                self.assertEqual(result["product_sentiment"], "Not Expressed")
                self.assertFalse(result["eligible_for_product_insights"])
                self.assertEqual(result["usage_evidence"]["status"], "none")

    def test_explicit_product_opinion_does_not_imply_usage(self):
        result = self.qualify("DemoAqua R1 is overpriced.")
        self.assertEqual(result["product_sentiment"], "Negative")
        self.assertEqual(result["primary_type"], "Product Discussion")
        self.assertTrue(result["eligible_for_product_insights"])
        self.assertFalse(result["eligible_as_usage_review"])

    def test_negated_use_ownership_and_purchase_are_not_usage_or_valid_feedback(self):
        for text in ("I have not used DemoAqua R1.", "I never used DemoAqua R1.", "I bought DemoAqua R1 yesterday.", "I own DemoAqua R1."):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertFalse(result["eligible_as_usage_review"])
                self.assertFalse(result["eligible_for_product_insights"])
                self.assertEqual(result["usage_evidence"]["status"], "none")

    def test_hypothetical_and_hearsay_are_not_first_person_usage(self):
        for text in ('The reviewer said "I used DemoAqua R1 for a month".', "If I used DemoAqua R1 it might be good.", "My neighbor's DemoAqua R1 gets stuck.", "My friend says DemoAqua R1 is excellent."):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertFalse(result["eligible_as_usage_review"])
                self.assertNotEqual(result["usage_evidence"]["status"], "self_reported")

    def test_brand_category_and_unknown_scopes(self):
        brand = self.qualify("DemoAqua is expensive.")
        self.assertEqual(brand["feedback_scope"], "brand")
        self.assertEqual(brand["product_model"], "unknown")
        category = self.qualify("Robotic pool cleaners are expensive.")
        self.assertEqual(category["feedback_scope"], "category")
        self.assertEqual(category["brand"], "unknown")
        self.assertTrue(category["eligible_for_product_insights"])
        unknown = self.qualify("I used it for a month.", video_title="DemoAqua R1 review")
        self.assertEqual(unknown["brand"], "unknown")
        self.assertEqual(unknown["qualification_status"], "ambiguous")
        self.assertFalse(unknown["eligible_as_usage_review"])

    def test_multiple_explicit_brands_abstain_from_attribution(self):
        result = self.qualify("DemoAqua R1 is great but DemoPool X2 is terrible.")
        self.assertEqual(result["brand"], "unknown")
        self.assertEqual(result["qualification_status"], "ambiguous")
        self.assertEqual(len(result["entity_candidates"]), 2)
        self.assertFalse(result["eligible_for_product_insights"])
        result = self.qualify("DemoAqua R1 is better than DemoPool.")
        self.assertEqual(result["brand"], "unknown")
        self.assertEqual(result["qualification_status"], "ambiguous")

    def test_content_sentiment_is_separate_from_product_sentiment(self):
        result = self.qualify("Great video. My DemoPool X2 broke after a week.")
        self.assertIn("Content Feedback", result["feedback_types"])
        self.assertIn("Actual Usage Experience", result["feedback_types"])
        self.assertEqual(result["content_sentiment"], "Positive")
        self.assertEqual(result["product_sentiment"], "Negative")
        self.assertTrue(result["eligible_as_usage_review"])

    def test_irrelevant_emoji_and_blank_are_insufficient(self):
        for text in ("First! Hello everyone!", "👍", "", "   "):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertEqual(result["primary_type"], "Irrelevant/Unclear")
                self.assertEqual(result["qualification_status"], "insufficient evidence")

    def test_question_and_explicit_statement_can_coexist(self):
        result = self.qualify("DemoAqua R1 is overpriced. Where can I buy it?")
        self.assertIn("Purchase Inquiry", result["feedback_types"])
        self.assertIn("Product Discussion", result["feedback_types"])
        self.assertEqual(result["product_sentiment"], "Negative")
        self.assertTrue(result["eligible_for_product_insights"])

    def test_negation_and_ambiguity_are_conservative(self):
        self.assertEqual(self.qualify("DemoPool X2 is not good.")["product_sentiment"], "Negative")
        self.assertEqual(self.qualify("DemoPool X2 is not bad.")["product_sentiment"], "Positive")
        for text in ("I do not think DemoAqua R1 is good.", "Maybe DemoAqua R1 is good.", "Great video about the DemoAqua R1."):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertEqual(result["qualification_status"], "ambiguous")
                self.assertFalse(result["eligible_for_product_insights"])

    def test_evidence_quotes_are_substrings_of_input(self):
        text = "My DemoPool X2 gets stuck. Great video."
        result = self.qualify(text)
        self.assertTrue(result["reasons"])
        self.assertIn(result["evidence_strength"], {"strong", "moderate", "weak", "insufficient evidence"})
        for item in result["evidence"]:
            self.assertIn(item["text"], text)

    def test_real_or_unmarked_input_is_rejected(self):
        for record in ({"review_id": "x", "review_text": "Do not analyze real data"}, {"review_id": "x", "review_text": "Unit test", "is_synthetic": False}):
            with self.assertRaises(ValueError):
                qualification.qualify_feedback(record)

    def test_batch_counts_are_derived_and_ids_are_unique(self):
        payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "feedback_qualification_synthetic.json").read_text())
        before = copy.deepcopy(payload)
        report = qualification.qualify_batch(payload["reviews"])
        self.assertEqual(payload, before)
        rows = report["results"]
        summary = report["summary"]
        self.assertEqual(summary["total_records"], 20)
        self.assertEqual(summary["valid_product_feedback"], sum(row["eligible_for_product_insights"] for row in rows))
        self.assertEqual(summary["usage_review_candidates"], sum(row["eligible_as_usage_review"] for row in rows))
        self.assertEqual(summary["purchase_inquiries"], sum("Purchase Inquiry" in row["feedback_types"] for row in rows))
        self.assertEqual(summary["sample_warning"], "Insufficient Data")
        self.assertEqual(summary["valid_product_feedback"], 8)
        self.assertEqual(summary["usage_review_candidates"], 3)
        self.assertEqual(summary["purchase_inquiries"], 5)
        self.assertEqual(summary["irrelevant_or_unclear"], 2)
        self.assertEqual(sum(summary["qualified_by_brand"].values()) + summary["qualified_unknown_brand"], summary["valid_product_feedback"])
        with self.assertRaises(ValueError):
            qualification.qualify_batch(payload["reviews"] + [payload["reviews"][0]])

    def test_empty_batch_returns_zero_with_warning(self):
        report = qualification.qualify_batch([])
        self.assertEqual(report["summary"]["total_records"], 0)
        self.assertEqual(report["summary"]["sample_warning"], "Insufficient Data")

    def test_buying_intentions_and_unpunctuated_questions_are_not_usage(self):
        for text in ("I want to buy a robotic pool cleaner.", "I am planning to buy DemoAqua R1.", "I wonder how long the DemoAqua R1 battery lasts"):
            with self.subTest(text=text):
                result = self.qualify(text)
                self.assertIn("Purchase Inquiry", result["feedback_types"])
                self.assertEqual(result["product_sentiment"], "Not Expressed")
                self.assertFalse(result["eligible_for_product_insights"])
                self.assertFalse(result["eligible_as_usage_review"])

    def test_mixed_product_sentiment_does_not_imply_personal_use(self):
        result = self.qualify("DemoAqua R1 cleans well but its battery life is too short.")
        self.assertEqual(result["product_sentiment"], "Mixed")
        self.assertTrue(result["eligible_for_product_insights"])
        self.assertFalse(result["eligible_as_usage_review"])

    def test_cli_reads_only_synthetic_fixture_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            fixture = temp / "tests" / "fixtures" / "feedback_qualification_synthetic.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes((AGENT_DIR / "tests" / "fixtures" / fixture.name).read_bytes())
            before = sorted(path.relative_to(temp) for path in temp.rglob("*"))
            output = io.StringIO()
            with patch.object(qualification, "AGENT_DIR", temp), patch("urllib.request.build_opener", side_effect=AssertionError("No network")), contextlib.redirect_stdout(output):
                self.assertEqual(qualification.main(["--summary-only"]), 0)
            self.assertEqual(before, sorted(path.relative_to(temp) for path in temp.rglob("*")))
            self.assertEqual(json.loads(output.getvalue())["mode"], "synthetic-rules")


if __name__ == "__main__":
    unittest.main()
