"""Offline reference checks on previously collected original comments."""
import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence_analysis import VERSION, evidence_message, evidence_spans, process_evidence_analysis


class EvidenceAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / ".runtime/phase35-batch.pending.json"
        if not path.exists():
            raise unittest.SkipTest("Private source comments unavailable.")
        data = json.loads(path.read_text())
        deadline = datetime.fromisoformat(data["delete_by"])
        if datetime.now(deadline.tzinfo) >= deadline:
            raise unittest.SkipTest("Private source comments expired.")
        cls.items = data["items"]

    def source(self, number):
        return self.items[number - 1]["review"]

    def span(self, review, substring):
        return next(s for s in evidence_spans(review["review_text"]) if substring in s["text"])

    def base(self, label, spans):
        return {"schema_version": VERSION, "feedback_types": [{"type": label, "evidence_ids": [s["id"] for s in spans]}],
                "brand": {"name": "unknown", "evidence_ids": []}, "product_model": {"name": "unknown", "evidence_ids": []},
                "sentiment": "Neutral", "facts": [], "potential_needs": []}

    def fact(self, kind, span, summary=None, **extra):
        return {"id": "f1", "kind": kind, "summary": summary or span["text"].strip(),
                "evidence_ids": [span["id"]], **extra}

    def test_every_span_preserves_unicode_offsets_and_full_context(self):
        for item in self.items:
            original = item["review"]["review_text"]
            spans = evidence_spans(original)
            self.assertEqual(spans, evidence_spans(original))
            self.assertEqual("".join(s["text"] for s in evidence_message(original)["evidence"]), original)
            for span in spans:
                self.assertEqual(original[span["start"]:span["end"]], span["text"])

    def test_dolphin_and_docking_reports_use_python_extracted_text(self):
        from analysis_control import Execution
        from research_quality import render_live_specialist
        from test_automatic_research import policy
        execution = Execution(policy(), "improvement", paid_confirmed=True, run_id="offline-evidence")
        for number, use, pain, aspect in (
            (4, "We liked the way it cleaned", "But the second the warranty", "Reliability"),
            (10, "i did everything", "pull it out of the pull", "Ease of Use"),
        ):
            with self.subTest(number=number):
                review = self.source(number)
                usage_span, pain_span = self.span(review, use), self.span(review, pain)
                value = self.base("Actual Usage Experience", [usage_span])
                value.update(sentiment="Negative", facts=[self.fact("pain_point", pain_span, aspect=aspect)])
                if number == 4:
                    value["brand"] = {"name": "Dolphin", "evidence_ids": [self.span(review, "done with Dolphin")["id"]]}
                    value["facts"].append({**self.fact("positive_feedback", usage_span, aspect="Cleaning Performance"), "id": "f2"})
                    value["sentiment"] = "Mixed"
                    self.assertTrue(pain_span["text"].startswith("  "))
                raw = copy.deepcopy(value)
                result = process_evidence_analysis(value, review)
                self.assertEqual(result["status"], "Valid", result["issues"])
                self.assertEqual(raw, value)
                self.assertEqual(result["normalized"]["facts"][0]["quotes"], [pain_span["text"]])
                row = {**review, "brand": value["brand"]["name"], "analysis": result["normalized"], "processing": result}
                state = {"purpose":"improvement","results":[row],"collected":1,"unprocessed":0,"failures":[],
                         "model":"qwen-plus-2025-12-01","status":"completed","run_id":execution.run_id,"collected_at":review["collected_at"]}
                report = render_live_specialist(state, execution=execution)
                self.assertIn(pain_span["text"], report)
                self.assertIn("有效自述使用反馈 1 条", report)

    def test_five_spans_survive_wire_and_projection_without_truncation(self):
        review = self.source(4)
        spans = evidence_spans(review["review_text"])[:5]
        value = self.base("Actual Usage Experience", spans)
        pain = self.span(review, "But the second the warranty")
        value.update(sentiment="Negative", facts=[self.fact("pain_point", pain, aspect="Reliability")])
        value["facts"][0]["id"] = "F01"
        raw = copy.deepcopy(value)
        result = process_evidence_analysis(value, review)
        self.assertEqual(result["status"], "Valid", result["issues"])
        self.assertEqual(raw, value)
        self.assertEqual(result["normalized"]["facts"][0]["id"], "f01")
        self.assertEqual(result["normalized"]["feedback_types"][0]["quotes"], [s["text"] for s in spans])
        self.assertEqual(result["normalizations"], [{"path": ["facts", 0, "id"], "from": "F01", "to": "f01"}])

    def test_normalized_id_collisions_and_oversized_evidence_are_rejected(self):
        review = self.source(4)
        span = self.span(review, "We liked the way it cleaned")
        value = self.base("Actual Usage Experience", [span])
        first = self.fact("positive_feedback", span, aspect="Cleaning Performance")
        value["facts"] = [{**first, "id": "F01"}, {**first, "id": "f01"}]
        result = process_evidence_analysis(value, review)
        self.assertEqual(result["status"], "Invalid")
        self.assertIn("colliding", result["issues"][0]["reason"])
        value["facts"] = []
        value["feedback_types"][0]["evidence_ids"] = [f"S{i:02}" for i in range(1, 18)]
        result = process_evidence_analysis(value, review)
        self.assertEqual(result["status"], "Invalid")
        self.assertEqual(result["issues"][0]["rule"], "maxItems")

    def test_report_labels_wire_projection_and_display_even_with_no_results(self):
        from analysis_control import Execution
        from research_quality import render_live_specialist
        from test_automatic_research import policy
        execution = Execution(policy(), "improvement", paid_confirmed=True, run_id="offline-version")
        state = {"purpose": "improvement", "schema_version": VERSION, "results": [], "collected": 1,
                 "unprocessed": 0, "failures": [], "model": "qwen-plus-2025-12-01", "status": "completed",
                 "run_id": execution.run_id, "collected_at": self.source(1)["collected_at"]}
        report = render_live_specialist(state, execution=execution)
        self.assertIn("模型响应契约：real-analysis-4", report)
        self.assertIn("内部证据投影：real-analysis-3", report)
        self.assertIn("报告展示版本：research-report-1", report)

    def test_missing_and_wrong_evidence_and_model_quotes_rejected(self):
        review = self.source(10)
        use, pain = self.span(review, "i did everything"), self.span(review, "pull it out of the pull")
        value = self.base("Actual Usage Experience", [use])
        value.update(sentiment="Negative", facts=[self.fact("pain_point", pain, aspect="Ease of Use")])
        for ids in ([], ["S999"], [use["id"]]):
            candidate = copy.deepcopy(value)
            candidate["facts"][0]["evidence_ids"] = ids
            self.assertEqual(process_evidence_analysis(candidate, review)["status"], "Invalid")
        value["facts"][0]["quotes"] = [pain["text"]]
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Invalid")

    def test_japanese_original_and_chinese_summary_are_separate(self):
        review = self.source(1)
        span = evidence_spans(review["review_text"])[0]
        value = self.base("Purchase Inquiry", [span])
        value["facts"] = [self.fact("explicit_need", span, "询问能否在热水中使用")]
        result = process_evidence_analysis(value, review)
        self.assertEqual(result["status"], "Partial")
        self.assertEqual(result["normalized"]["facts"][0]["quotes"], [span["text"]])
        self.assertTrue(any(x["code"] == "semantic_review_required" for x in result["issues"]))

    def test_irrelevant_unclear_and_conflicting_labels_are_distinct(self):
        review = self.source(8)
        spans = evidence_spans(review["review_text"])
        value = self.base("Irrelevant", spans)
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Excluded")
        value["feedback_types"][0]["type"] = "Unclear"
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Partial")
        value["feedback_types"].append({"type": "Product Discussion", "evidence_ids": [spans[0]["id"]]})
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Invalid")

    def test_hypothesis_must_reference_fact_evidence_and_cannot_invent_cause(self):
        review = self.source(10)
        use, pain = self.span(review, "i did everything"), self.span(review, "pull it out of the pull")
        value = self.base("Actual Usage Experience", [use])
        value.update(sentiment="Negative", facts=[self.fact("pain_point", pain, aspect="Ease of Use")],
                     potential_needs=[{"summary":"More reliable docking", "evidence_ids":[pain["id"]],
                                       "uncertainty":"medium","validation_method":"Test docking cycles"}])
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Valid")
        value["potential_needs"][0]["evidence_ids"] = [use["id"]]
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Invalid")
        value["potential_needs"][0].update(evidence_ids=[pain["id"]], summary="A faulty sensor caused it")
        self.assertEqual(process_evidence_analysis(value, review)["status"], "Invalid")
