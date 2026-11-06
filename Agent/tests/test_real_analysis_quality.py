"""Actual-response regressions and a private human oracle; no API or report files."""
import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classify_reviews import ClassificationError, check_classification
from real_analysis_schema import SCHEMA, VERSION, FACT, VALIDATOR, validate, compatibility_view, process_analysis, inquiry_gaps, supports_usage
from jsonschema import Draft202012Validator


class RealAnalysisQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / ".runtime/regression/first_qwen_response.json"
        if not path.exists():
            raise unittest.SkipTest("Private real regression fixture absent; never fetch automatically.")
        cls.case = json.loads(path.read_text())
        deadline = datetime.fromisoformat(cls.case["delete_by"])
        if datetime.now(deadline.tzinfo) >= deadline:
            raise unittest.SkipTest("Private real fixture expired; delete or refresh it before use.")
        cls.review = cls.case["review"]

    def reference(self):
        return copy.deepcopy(self.case["reference_contract_v3"])

    def second(self):
        return json.loads(self.case["second_response"]["response"]["choices"][0]["message"]["content"])

    def third(self):
        return json.loads(self.case["third_response_raw_json"])

    def batch_source(self, index):
        path = Path(__file__).resolve().parents[1] / ".runtime/phase35-batch.pending.json"
        if not path.exists():
            self.skipTest("Private Phase 3.5 sources unavailable.")
        plan = json.loads(path.read_text())
        deadline = datetime.fromisoformat(plan["delete_by"])
        if datetime.now(deadline.tzinfo) >= deadline:
            self.skipTest("Private Phase 3.5 sources expired.")
        return plan["items"][index - 1]["review"]

    def test_phase35_source_usage_and_attribution_boundaries(self):
        for index, fragment in ((4, "We liked the way it cleaned"), (5, "mine lasted 4 years full time"),
                                (10, "i did everything I could do to make it easy to dock")):
            text = self.batch_source(index)["review_text"]
            self.assertIn(fragment, text)
            self.assertTrue(supports_usage(fragment, text))
        text = self.batch_source(3)["review_text"]
        self.assertFalse(supports_usage(text, text))

    def test_phase35_japanese_label_and_exact_scalar_quote_normalize(self):
        review = self.batch_source(1)
        # Validator boundary input, never a reconstruction of the lost model response.
        value = self.reference()
        value.update(feedback_types=[{"type": "Product Inquiry", "quotes": review["review_text"]}],
                     brand={"name": "unknown", "quotes": []}, product_model={"name": "unknown", "quotes": []},
                     sentiment="Neutral", facts=[], potential_needs=[])
        result = process_analysis(value, review)
        self.assertEqual(result["normalized"]["feedback_types"][0]["type"], "Purchase Inquiry")
        self.assertEqual(len(result["normalizations"]), 2)
        self.assertEqual(result["raw"], value)
        value["feedback_types"][0]["quotes"] = review["review_text"] + " "
        self.assertEqual(process_analysis(value, review)["status"], "Invalid")

    def test_phase35_media_aside_has_distinct_excluded_status(self):
        review = self.batch_source(8)
        value = self.reference()
        value.update(feedback_types=[{"type": "Irrelevant/Unclear", "quotes": [review["review_text"]]}],
                     brand={"name": "unknown", "quotes": []}, product_model={"name": "unknown", "quotes": []},
                     sentiment="Neutral", facts=[], potential_needs=[])
        result = process_analysis(value, review)
        self.assertEqual(result["status"], "Excluded")
        self.assertEqual(result["normalized"]["facts"], [])

    def test_phase35_skimmer_experience_cannot_be_assigned_to_other_brand(self):
        review = self.batch_source(5)
        value = self.reference()
        value.update(feedback_types=[{"type": "Actual Usage Experience", "quotes": ["mine lasted 4 years full time"]}],
                     brand={"name": "Beatbot", "quotes": ["Beatbot"]}, product_model={"name": "unknown", "quotes": []},
                     sentiment="Neutral", facts=[], potential_needs=[])
        self.assertEqual(process_analysis(value, review)["status"], "Invalid")
        value["brand"] = {"name": "Betta", "quotes": ["Betta"]}
        self.assertEqual(process_analysis(value, review)["status"], "Valid")

    def test_third_response_normalizes_only_ids_and_keeps_verified_findings(self):
        raw = self.third()
        quality = process_analysis(raw, self.review)
        self.assertEqual(quality["status"], "Partial")
        self.assertEqual(quality["raw"], raw)
        self.assertEqual(len(quality["normalizations"]), 4)
        normalized = quality["normalized"]
        self.assertEqual(normalized["potential_needs"][0]["based_on"], [f["id"] for f in normalized["facts"]])
        reconstructed = copy.deepcopy(normalized)
        for change in quality["normalizations"]:
            target = reconstructed
            for part in change["path"][:-1]:
                target = target[part]
            target[change["path"][-1]] = change["from"]
        self.assertEqual(reconstructed, raw)
        self.assertEqual({i["code"] for i in quality["issues"]},
                         {"missing_purchase_inquiry", "missing_explicit_need", "unsupported_frequency"})
        view = compatibility_view(normalized, self.review, allow_incomplete=True)
        self.assertEqual(view["brand"]["name"], "Aiper")
        self.assertFalse(view["consumer_needs"]["explicit_needs"])
        quote = view["consumer_needs"]["specific_pain_points"][0]["quote"]
        self.assertIn("drain", quote)
        self.assertIn("slope transition", quote)

    def test_unsafe_id_references_and_quotes_remain_invalid(self):
        for defect in ("duplicate", "collision", "missing", "boolean", "quote"):
            with self.subTest(defect=defect):
                raw = self.third()
                if defect == "duplicate":
                    raw["facts"][1]["id"] = raw["facts"][0]["id"]
                elif defect == "collision":
                    raw["facts"][1]["id"] = "fact-001"
                elif defect == "missing":
                    raw["potential_needs"][0]["based_on"] = [99]
                elif defect == "boolean":
                    raw["potential_needs"][0]["based_on"] = [True]
                else:
                    raw["facts"][0]["quotes"] = [self.review["video_title"]]
                self.assertEqual(process_analysis(raw, self.review)["status"], "Invalid")

    def test_question_coverage_checks_evidence_and_ignores_unrelated_question(self):
        value = self.reference()
        self.assertEqual(process_analysis(value, self.review)["status"], "Valid")
        self.assertFalse(inquiry_gaps(value, "Why did it stop working?"))
        value["facts"] = [f for f in value["facts"] if f["kind"] != "explicit_need"]
        self.assertEqual([issue["code"] for issue in inquiry_gaps(value, self.review["review_text"])], ["missing_explicit_need"])

    def test_third_response_partial_single_sample_preview(self):
        from research_quality import render_live_specialist
        from analysis_control import Execution
        from test_automatic_research import policy
        execution = Execution(policy(), "improvement", paid_confirmed=True, run_id="offline-third-preview")
        quality = process_analysis(self.third(), self.review)
        row = {**self.review, "brand": "Aiper", "analysis": quality["normalized"], "processing": quality}
        state = {"purpose": "improvement", "results": [row], "collected": 1, "failures": [],
                 "model": "qwen-plus-2025-12-01", "run_id": execution.run_id,
                 "status": "completed", "unprocessed": 0, "collected_at": self.review["collected_at"]}
        report = render_live_specialist(state, execution=execution)
        for fragment in ("单样本技术验收预览", "Incomplete Analysis", "购买咨询遗漏", "明确需求遗漏",
                         "Aiper", "drain", "slope transition"):
            self.assertIn(fragment, report)
        self.assertNotIn("repeatedly got stuck", report)

    def reject(self, value):
        before = copy.deepcopy(value)
        with self.assertRaises(ClassificationError):
            validate(value, self.review)
        self.assertEqual(value, before)

    def test_first_actual_response_still_fails_without_repair(self):
        raw = self.case["first_response"]["response"]["choices"][0]["message"]["content"]
        value = json.loads(raw)
        self.reject(value)
        with self.assertRaisesRegex(ClassificationError, "polarities disagree"):
            check_classification(value["classification"])
        self.assertEqual(self.case["first_response"]["response"]["choices"][0]["message"]["content"], raw)

    def test_second_actual_response_is_preserved_and_not_silently_upgraded(self):
        value = self.second()
        self.assertEqual(self.case["second_response"]["usage"], {"prompt_tokens": 739, "completion_tokens": 1087, "total_tokens": 1826})
        self.assertIsNone(value["product_model"]["name"])
        self.assertIn("...", value["consumer_needs"]["usage_scenarios"][0]["quote"])
        self.reject(value)

    def test_schema_and_private_human_reference(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.assertFalse(list(VALIDATOR.iter_errors(self.reference())))
        self.assertEqual(validate(self.reference(), self.review), self.reference())

    def test_wire_contract_does_not_repeat_legacy_pains(self):
        value = self.reference()
        for name in ("classification", "consumer_needs", "product_aspects"):
            self.assertNotIn(name, SCHEMA["required"])
            self.assertNotIn(name, value)
        self.assertEqual(sum(f["kind"] == "pain_point" for f in value["facts"]), 2)

    def test_pain_summaries_are_projected_once_without_model_repetition(self):
        value = self.reference()
        view = compatibility_view(value, self.review)
        pains = [f for f in value["facts"] if f["kind"] == "pain_point"]
        self.assertEqual(view["classification"]["pain_points"], [f["summary"] for f in pains])
        self.assertEqual([p["text"] for p in view["consumer_needs"]["specific_pain_points"]], [f["summary"] for f in pains])
        self.assertEqual([(a["aspect"], a["feedback"]) for a in view["classification"]["product_aspects"]], [(f["aspect"], f["summary"]) for f in pains])

    def test_multilabel_usage_is_not_excluded_by_inquiry(self):
        view = compatibility_view(self.reference(), self.review)
        self.assertEqual(view["feedback_type"], "Actual Usage Experience")
        self.assertIn("Purchase Inquiry", view["feedback_types"])
        value = self.reference()
        value["feedback_types"] = value["feedback_types"][1:]
        self.reject(value)

    def test_inquiry_and_duplicate_labels_are_checked(self):
        value = self.reference()
        value["feedback_types"] = value["feedback_types"][:1]
        self.reject(value)
        value = self.reference()
        value["feedback_types"].append(copy.deepcopy(value["feedback_types"][0]))
        self.reject(value)

    def test_pool_ownership_is_not_product_use(self):
        value = self.reference()
        value["feedback_types"][0]["quotes"] = [value["facts"][0]["quotes"][0]]
        self.reject(value)

    def test_brand_evidence_and_unknown_model_are_strict(self):
        value = self.reference()
        self.assertEqual(value["product_model"], {"name": "unknown", "quotes": []})
        value["brand"] = {"name": "unknown", "quotes": []}
        self.reject(value)
        for name in (None, "unk", ""):
            value = self.reference()
            value["product_model"]["name"] = name
            self.reject(value)

    def test_video_title_cannot_supply_entity_or_fact_evidence(self):
        value = self.reference()
        value["brand"] = {"name": self.review["video_title"], "quotes": [self.review["video_title"]]}
        self.reject(value)
        value = self.reference()
        value["facts"][0]["quotes"] = [self.review["video_title"]]
        self.reject(value)

    def test_multiple_independent_quotes_remain_separate(self):
        value = self.reference()
        quotes = [value["facts"][0]["quotes"][0], value["facts"][2]["quotes"][0]]
        value["facts"][0]["quotes"] = quotes
        before = copy.deepcopy(value)
        view = compatibility_view(value, self.review)
        self.assertEqual(value, before)
        self.assertEqual(view["consumer_needs"]["usage_scenarios"][0]["quotes"], quotes)
        self.assertEqual(view["consumer_needs"]["usage_scenarios"][0]["quote"], quotes[0])

    def test_joining_sentences_or_normalizing_spaces_is_rejected(self):
        value = self.reference()
        value["feedback_types"][0]["quotes"] = [self.second()["usage_quote"]]
        self.assertNotIn(value["feedback_types"][0]["quotes"][0], self.review["review_text"])
        self.reject(value)

    def test_inserted_ellipsis_is_rejected(self):
        value = self.reference()
        value["facts"][0]["quotes"] = [self.second()["consumer_needs"]["usage_scenarios"][0]["quote"]]
        self.reject(value)

    def test_paraphrased_summary_is_not_treated_as_a_raw_quote(self):
        value = self.reference()
        view = compatibility_view(value, self.review)
        pain = view["consumer_needs"]["specific_pain_points"][0]
        self.assertNotEqual(pain["text"], pain["quote"])
        self.assertEqual(pain["claim_type"], "evidence_summary")

    def test_factual_findings_need_no_uncertainty_or_validation_fields(self):
        self.assertNotIn("uncertainty", FACT["required"])
        self.assertNotIn("validation_method", FACT["required"])
        for fact in self.reference()["facts"]:
            self.assertNotIn("validation_step", fact)
            self.assertNotIn("uncertainty", fact)
        validate(self.reference(), self.review)

    def test_potential_needs_require_basis_uncertainty_and_method(self):
        for field, bad in (("based_on", []), ("uncertainty", False), ("validation_method", "")):
            value = self.reference()
            value["potential_needs"][0][field] = bad
            self.reject(value)

    def test_missing_or_inferred_evidence_ids_are_not_accepted(self):
        value = self.reference()
        value["potential_needs"][0]["based_on"] = ["missing"]
        self.reject(value)

    def test_technical_speculation_is_not_accepted_as_fact_or_functional_need(self):
        technical = self.second()["consumer_needs"]["potential_unmet_needs"][0]["text"]
        value = self.reference()
        value["facts"][1]["summary"] = technical
        self.reject(value)
        value = self.reference()
        value["potential_needs"][0]["summary"] = technical
        self.reject(value)

    def test_potential_interpretation_cannot_be_smuggled_into_facts(self):
        value = self.reference()
        value["facts"][1]["summary"] = value["potential_needs"][0]["summary"]
        self.reject(value)

    def test_explicit_need_requires_quoted_request(self):
        value = self.reference()
        explicit = next(f for f in value["facts"] if f["kind"] == "explicit_need")
        explicit["quotes"] = value["facts"][1]["quotes"]
        self.reject(value)

    def test_duplicate_facts_and_conflicting_sentiment_are_rejected(self):
        value = self.reference()
        value["facts"].append(copy.deepcopy(value["facts"][1]))
        self.reject(value)
        value = self.reference()
        value["sentiment"] = "Neutral"
        self.reject(value)

    def test_aspect_is_required_only_for_product_feedback_facts(self):
        value = self.reference()
        del value["facts"][1]["aspect"]
        self.reject(value)
        value = self.reference()
        value["facts"][0]["aspect"] = value["facts"][1]["aspect"]
        self.reject(value)

    def test_inference_quotes_are_derived_from_original_facts_without_joining(self):
        value = self.reference()
        view = compatibility_view(value, self.review)
        facts = {f["id"]: f for f in value["facts"]}
        expected = list(dict.fromkeys(q for ref in value["potential_needs"][0]["based_on"] for q in facts[ref]["quotes"]))
        inferred = view["consumer_needs"]["potential_unmet_needs"][0]
        self.assertEqual(inferred["quotes"], expected)
        self.assertEqual(inferred["claim_type"], "model_inference")
        self.assertTrue(all(q in self.review["review_text"] for q in inferred["quotes"]))

    def test_report_rejects_invalid_wire_or_conflicting_brand_before_rendering(self):
        from research_quality import render_live_specialist
        from analysis_control import Execution
        from test_automatic_research import policy
        execution = Execution(policy(), "improvement", paid_confirmed=True, run_id="offline-report-check")
        for problem in ("quote", "brand"):
            value = self.reference()
            row = {**self.review, "brand": value["brand"]["name"], "analysis": value}
            if problem == "quote":
                value["facts"][0]["quotes"] = [self.review["video_title"]]
            else:
                row["brand"] = "unknown"
            with self.assertRaises(ClassificationError):
                render_live_specialist({"purpose": "improvement", "results": [row]}, execution=execution)
