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
import generate_report as reporter
from generate_insights import generate_insights


class GenerateReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        _, self.reviews = classifier.load_reviews(classifier.DEFAULT_CSV)
        fixtures = json.loads((AGENT_DIR / "tests" / "fixtures" / "mock_classifications.json").read_text())
        self.classified = {
            "mode": "mock", "model": "offline-fixtures", "failures": [],
            "results": [{
                "review_id": row["review_id"], "brand": row["brand"],
                "source_platform": row["source_platform"], "source_url": row["source_url"],
                "is_synthetic": True, "input_sha256": classifier.review_fingerprint(row),
                **copy.deepcopy(fixtures[row["review_id"]]["classification"]),
            } for row in self.reviews],
        }
        for name in ("load_local_settings", "classify_qwen"):
            mocked = patch.object(classifier, name, side_effect=AssertionError("Unexpected settings/API access"))
            mocked.start()
            self.addCleanup(mocked.stop)

    def render(self):
        return reporter.render_report(generate_insights(self.classified), self.classified, self.reviews)

    def test_six_sections_warning_brand_counts_and_original_evidence(self):
        content = self.render()
        for title in ("Executive Summary", "Consumer Pain Points", "Consumer Sentiment", "Competitive Intelligence", "Business Opportunities", "Sources & Methodology"):
            self.assertIn(title, content)
        self.assertEqual(content.count("\n## "), 6)
        self.assertIn("DEMO — SYNTHETIC DATA", content[:250])
        for brand in ("Brand A", "Brand B", "Brand C"):
            self.assertIn(f"| {brand} | 3 | Insufficient Data |", content)
        self.assertIn("| Battery Life | 0 / 1 | 1 / 0 | 0 / 1 |", content)
        self.assertIn("| Maintenance | 0 / 1 | 0 / 0 | 2 / 0 |", content)
        self.assertIn(self.reviews[0]["review_text"], content)
        self.assertIn("| 9 | Brand C | synthetic |", content)
        self.assertIn("| Mixed | 2 |", content)
        self.assertNotIn("https://", content)
        self.assertNotIn("http://", content)
        self.assertIn("零提及不代表满意", content)

    def test_summary_and_opportunities_have_evidence_and_hypothesis_labels(self):
        content = self.render()
        summary = content.split("## 1. Executive Summary")[1].split("## 2.")[0]
        self.assertEqual(sum(line.startswith(("1.", "2.", "3.")) for line in summary.splitlines()), 3)
        self.assertIn("review_id=1", summary)
        self.assertIn("review_id=9", summary)
        opportunities = content.split("## 5. Business Opportunities")[1].split("## 6.")[0]
        self.assertLessEqual(opportunities.count("### "), 3)
        self.assertIn("数据事实", opportunities)
        self.assertIn("分析假设", opportunities)
        self.assertIn("演示假设", opportunities)

    def test_duplicate_attribute_mentions_count_once(self):
        aspect = self.classified["results"][0]["product_aspects"][0]
        self.classified["results"][0]["product_aspects"].extend([
            copy.deepcopy(aspect), {**aspect, "feedback": "Another description of short battery life"},
        ])
        self.assertIn("| Battery Life | 0 / 1 | 1 / 0 | 0 / 1 |", self.render())

    def test_stale_statistics_are_rejected(self):
        insights = generate_insights(self.classified)
        insights["brands"]["Brand A"]["aspect_counts"]["Battery Life"]["Negative"] = 99
        with self.assertRaises(classifier.ClassificationError):
            reporter.render_report(insights, self.classified, self.reviews)

    def test_duplicate_classification_id_is_rejected(self):
        self.classified["results"].append(copy.deepcopy(self.classified["results"][0]))
        with self.assertRaises(classifier.ClassificationError):
            self.render()

    def test_missing_evidence_changed_brand_and_changed_text_are_rejected(self):
        for field in ("review_text", "brand"):
            changed = copy.deepcopy(self.reviews)
            changed[0][field] += " changed"
            with self.subTest(field=field), self.assertRaises(classifier.ClassificationError):
                reporter.render_report(generate_insights(self.classified), self.classified, changed)
        with self.assertRaises(classifier.ClassificationError):
            reporter.render_report(generate_insights(self.classified), self.classified, self.reviews[1:])

    def test_insufficient_evidence_does_not_invent_opportunities(self):
        self.classified["results"] = self.classified["results"][:1]
        content = self.render()
        self.assertIn("可支持的独立发现不足三项", content)
        opportunity = content.split("## 5. Business Opportunities")[1].split("## 6.")[0]
        self.assertIn("Insufficient Evidence", opportunity)
        self.assertNotIn("### ", opportunity)

    def test_empty_successes_are_rejected(self):
        self.classified["results"] = []
        with self.assertRaisesRegex(classifier.ClassificationError, "No classified reviews"):
            self.render()

    def test_synthetic_data_cannot_generate_real_report(self):
        with self.assertRaises(classifier.ClassificationError):
            reporter.render_report(generate_insights(self.classified), self.classified, self.reviews, "real")

    def test_markdown_text_is_escaped(self):
        self.assertEqual(reporter.markdown("line|one\n[x](fake)<script>"), "line\\|one \\[x\\]\\(fake\\)&lt;script&gt;")

    def test_cli_writes_only_report_and_preserves_inputs(self):
        insight_path = self.temp / "insights.json"
        classified_path = self.temp / "classifications.json"
        insight_path.write_text(json.dumps(generate_insights(self.classified)))
        classified_path.write_text(json.dumps(self.classified))
        before = (insight_path.read_bytes(), classified_path.read_bytes(), classifier.DEFAULT_CSV.read_bytes())
        arguments = ["--insights", str(insight_path), "--classifications", str(classified_path), "--reviews", str(classifier.DEFAULT_CSV)]
        with patch.object(reporter, "AGENT_DIR", self.temp), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reporter.main(arguments), 0)
        output = self.temp / "outputs" / "test" / "market_research_report.md"
        self.assertTrue(output.exists())
        self.assertIn("DEMO — SYNTHETIC DATA", output.read_text())
        self.assertEqual(before, (insight_path.read_bytes(), classified_path.read_bytes(), classifier.DEFAULT_CSV.read_bytes()))

    def test_missing_inputs_have_clear_error_and_no_report(self):
        error = io.StringIO()
        with patch.object(reporter, "AGENT_DIR", self.temp), contextlib.redirect_stderr(error):
            self.assertEqual(reporter.main([]), 2)
        self.assertIn("Missing input", error.getvalue())
        self.assertFalse((self.temp / "outputs").exists())


if __name__ == "__main__":
    unittest.main()
