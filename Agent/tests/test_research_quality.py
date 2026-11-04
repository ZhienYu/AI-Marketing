"""Challenging self-authored corpus; no network, model or real comment data."""
import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import classify_reviews as classification
import consumer_needs as needs
import research_quality as quality
import orchestrator


class ReportQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        with patch.object(classification, "classify_qwen", side_effect=AssertionError("No paid model")), patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No keys")), contextlib.redirect_stdout(io.StringIO()):
            cls.paths = quality.run_expanded(output_root=Path(cls.temp.name))
        cls.root = cls.paths[0].parent
        cls.research = json.loads((cls.root / "consumer_needs.json").read_text())
        cls.classified = json.loads((cls.root / "classifications.json").read_text())
        import csv
        with (cls.root / "synthetic_reviews.csv").open(newline="") as handle:
            cls.reviews = list(csv.DictReader(handle))
        cls.improvement, cls.competitor = (p.read_text() for p in cls.paths)

    def test_shared_41_record_corpus_and_qualification_boundary(self):
        self.assertEqual(len(self.reviews), 41)
        self.assertEqual(len(self.classified["results"]), 32)
        self.assertEqual(self.paths[0].parent, self.paths[1].parent)
        ids = {r["review_id"] for r in self.classified["results"]}
        self.assertNotIn("synthetic:needs-032", ids)  # ambiguous comparison target
        self.assertTrue(all(f"synthetic:needs-{i:03d}" not in ids for i in range(34, 42)))

    def test_reports_have_distinct_analysis_not_generic_appendix(self):
        self.assertIn("需求分析链", self.improvement)
        self.assertNotIn("需求分析链", self.competitor)
        self.assertIn("相同功能维度", self.competitor)
        self.assertNotIn("相同功能维度", self.improvement)
        for report in (self.improvement, self.competitor):
            self.assertNotIn("# Product Insight Agent — Market Research Report", report)
            self.assertEqual(report.count("## Executive Summary"), 1)
            self.assertEqual(report.count("## Evidence Appendix"), 1)
            self.assertLess(report.index("## 研究建议"), report.index("## Evidence Appendix"))
            body, appendix = report.split("## Evidence Appendix")
            for row in self.classified["results"]:
                original = next(r for r in self.reviews if r["review_id"] == row["review_id"])
                self.assertNotIn(original["review_text"], body)
                self.assertEqual(appendix.count(original["review_text"]), 1)

    def test_refined_attributes_do_not_conflate_motor_and_navigation(self):
        groups = quality.evidence_groups(self.research, self.classified)
        self.assertEqual(len(groups[quality.NAV]["Negative"]), 9)
        self.assertEqual(len(groups[quality.NAV]["Positive"]), 6)
        self.assertEqual(groups["Reliability"]["Negative"], {"synthetic:needs-019"})
        self.assertNotIn("synthetic:needs-019", groups[quality.NAV]["Negative"])

    def test_duplicate_aspect_does_not_double_count_mixed(self):
        classified = copy.deepcopy(self.classified)
        mixed = next(r for r in classified["results"] if r["sentiment"] == "Mixed")
        mixed["product_aspects"] *= 2
        before = quality.evidence_groups(self.research, self.classified)
        after = quality.evidence_groups(self.research, classified)
        self.assertEqual(before, after)

    def test_explicit_demands_are_not_all_negative_feedback(self):
        group = quality.evidence_groups(self.research, self.classified)[quality.NAV]
        self.assertEqual(len(group["explicit"]), 3)
        self.assertLess(len(group["explicit"]), len(group["Negative"]))
        self.assertIn("单条反馈支持的探索性假设，证据不足", self.improvement)
        self.assertIn("人工 Mock 推断", self.improvement)

    def test_no_placeholder_brands_or_unknown_comparison_column(self):
        body = self.competitor.split("## Evidence Appendix")[0]
        for name in ("Brand A", "Brand B", "Brand C", "| unknown |"):
            self.assertNotIn(name, body)
        self.assertIn("未知品牌记录 2 条", body)
        self.assertIn("小样本无法进行可靠竞品比较", body)

    def test_comparison_requires_shared_scenario(self):
        research = copy.deepcopy(self.research)
        for rid, ann in research["annotations"].items():
            ann["scenario_quote"] = rid  # isolated group labels for comparison unit test only
        report = quality.render_specialist("competitor", research, self.classified, self.reviews)
        self.assertIn("无共同场景的可比较证据", report)
        self.assertNotIn("的样本认知：", report)

    def test_all_links_have_unique_evidence_anchor(self):
        for report in (self.improvement, self.competitor):
            anchors = re.findall(r'<a id="(e\d+)"', report)
            self.assertEqual(len(anchors), 32)
            self.assertEqual(len(anchors), len(set(anchors)))
            self.assertTrue(set(re.findall(r'\]\(#(e\d+)\)', report)) <= set(anchors))
            self.assertNotIn("https://www.youtube.com", report)

    def test_shared_battery_direction_is_not_called_a_brand_advantage(self):
        section = self.competitor.split("### 续航", 1)[1].split("### 清洁效果", 1)[0]
        self.assertIn("方向一致，未观察到品牌认知差异", section)
        self.assertIn("共同需求研究问题（非差异化机会）", section)
        self.assertNotIn("人工 Mock 差异化假设", section)

    def test_fabricated_quote_and_false_explicit_demand_rejected(self):
        for value in ("invented quote", "near steps"):
            annotations = copy.deepcopy(self.research["annotations"])
            annotations["synthetic:needs-001"]["explicit_need_quote"] = value
            with self.assertRaises(classification.ClassificationError):
                needs.research_insights(self.classified, self.reviews, self.research["envelopes"], self.research["qualification"], annotations=annotations)

    def test_refinement_cannot_relabel_unrelated_attribute(self):
        annotations = copy.deepcopy(self.research["annotations"])
        annotations["synthetic:needs-019"]["attribute"] = quality.NAV
        with self.assertRaises(classification.ClassificationError):
            needs.research_insights(self.classified, self.reviews, self.research["envelopes"], self.research["qualification"], annotations=annotations)

    def test_real_data_guard_remains_closed(self):
        reviews = copy.deepcopy(self.reviews)
        reviews[0]["source_platform"] = "youtube"
        with self.assertRaises(classification.ClassificationError):
            needs.render_research_report("improvement", self.research, self.classified, reviews)


if __name__ == "__main__":
    unittest.main()
