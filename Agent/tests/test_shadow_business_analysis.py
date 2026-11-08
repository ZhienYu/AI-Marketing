import copy
import json
import unittest

from jsonschema import ValidationError

from analysis_control import QWEN_MODEL
from evidence_analysis import VERSION as EVIDENCE_VERSION
from shadow_business_analysis import (
    LEGACY_VERSION, VERSION, audit_shadow_response, build_evidence_pack, build_shadow_request,
    render_shadow_report, validate_shadow_response,
)
from research_focus import research_axes


def review(ident, text):
    return {"review_id": f"youtube:{ident}", "comment_id": ident, "video_id": "12345678901",
            "source_url": f"https://www.youtube.com/watch?v=12345678901&lc={ident}",
            "source_platform": "youtube", "is_synthetic": False, "review_text": text,
            "published_at": "2026-10-01T00:00:00Z", "collected_at": "2026-11-07T00:00:00Z"}


def example():
    return {"schema_version": VERSION, "insights": [
        {"id": "I01", "kind": "explicit_need", "summary": "Budget and dust removal both matter to this shopper",
         "product": None, "evidence_ids": ["E001", "E002"], "evidence_facts": []},
        {"id": "I02", "kind": "purchase_concern", "summary": "One shopper asked about noise",
         "product": None, "evidence_ids": ["E003"], "evidence_facts": []}],
        "implications": [{"id": "O01", "insight_id": "I01", "proposal": "Compare dust removal at the same purchase budget",
                          "validation": "Measure dust levels in the same room with the same baseline dust load",
                          "decision_question": "Which option removes more dust at the same budget?",
                          "decision_type": "product_performance", "method_type": "performance_test",
                          "measurement_type": "measured_performance", "expected_measurement": "Change in airborne dust level",
                          "research_parameters": [], "evidence_ids": ["E001", "E002"]}], "omissions": []}


class ResearchAxisRegressionTests(unittest.TestCase):
    def test_real_phrase_triggers_are_blocked(self):
        self.assertNotIn("指定使用场景下的持续时间", research_axes("highest CADR of 702m3/hr"))
        self.assertNotIn("机身厚度或重量", research_axes("simple things like dust trigger reactions"))
        self.assertIn("指定使用场景下的持续时间", research_axes("I used it for 3 hours"))

    def test_cross_domain_axis_context(self):
        self.assertEqual(research_axes("A 50W motor moves water at 18 L per hour."), [])
        self.assertEqual(research_axes("The software filter fit my budget and cancels noise."), [])
        self.assertEqual(research_axes("I want to cancel my subscription."), ["取消或续订的步骤与实际扣费"])
        self.assertIn("连续使用后的舒适度与贴合度", research_axes("The ear tips fit snugly."))
        self.assertIn("不同污物条件下的清洁效果", research_axes("I want a finer filter for debris."))
        self.assertEqual(research_axes("I want a thinner phone.", topic="价格与预算"), [])
        self.assertIn("机身厚度或重量", research_axes("I want a thinner phone.", topic="续航与充电"))


class ShadowBusinessTests(unittest.TestCase):
    def setUp(self):
        self.rows = [review("a", "I want dust removal. The price matters."), review("b", "Which one is quiet?")]
        self.pack = build_evidence_pack("Air Purifier", self.rows)

    def test_request_is_bounded_and_source_metadata_stays_local(self):
        policy = {"model": QWEN_MODEL, "enable_thinking": False, "max_input_tokens": 11000, "max_output_tokens": 1500}
        payload = build_shadow_request(self.pack, policy)
        data = json.loads(payload["messages"][1]["content"])
        self.assertEqual(data["evidence"][1]["text"], " The price matters.")
        self.assertNotIn("youtube.com", payload["messages"][1]["content"])
        self.assertNotIn("review_id", data["evidence"][0])
        self.assertEqual(payload["max_tokens"], 1500)
        with self.assertRaises(ValueError):
            build_shadow_request(self.pack, {**policy, "max_input_tokens": 1})

    def test_local_renderer_counts_unique_comments_and_keeps_empty_path(self):
        output = render_shadow_report(self.pack, example())
        self.assertIn("依据 1 条独立评论", output)
        self.assertIn("E002", output)
        self.assertIn("暂无足够证据提出建议", render_shadow_report(self.pack))
        self.assertIn("离线构造", output)

    def test_rejects_bad_ids_wrong_attribution_unknown_numbers_and_malformed_results(self):
        mutations = [
            ("insights", "evidence_ids", ["E999"]), ("insights", "product", "Acer Aspire 7"),
            ("insights", "summary", "Demand rose 25%"), ("implications", "evidence_ids", ["E003"]),
            ("implications", "insight_id", "I09"), ("implications", "id", "I09"),
        ]
        for section, key, value in mutations:
            result = example()
            result[section][0][key] = value
            with self.subTest(value=value), self.assertRaises((ValueError, ValidationError)):
                validate_shadow_response(self.pack, result)
        result = example()
        result["insights"].append(copy.deepcopy(result["insights"][0]))
        with self.assertRaises(ValueError):
            validate_shadow_response(self.pack, result)

    def test_replays_accepted_product_without_leaking_attribution_across_sources(self):
        row = review("c", "I used Acme X2.")
        raw = {"schema_version": EVIDENCE_VERSION,
               "feedback_types": [{"type": "Actual Usage Experience", "evidence_ids": ["S01"]}],
               "brand": {"name": "Acme", "evidence_ids": ["S01"]},
               "product_model": {"name": "Acme X2", "evidence_ids": ["S01"]},
               "sentiment": "Neutral", "facts": [], "potential_needs": []}
        pack = build_evidence_pack("Robot Pool Cleaner", [row, self.rows[1]], model_results={row["review_id"]: raw})
        self.assertEqual(pack.evidence[0].products, ("Acme X2",))
        response = {"schema_version": VERSION, "insights": [
            {"id": "I01", "kind": "usage_observation", "summary": "The author used the device",
             "product": "Acme X2", "evidence_ids": ["E001"], "evidence_facts": []}], "implications": [], "omissions": []}
        validate_shadow_response(pack, response)
        response["insights"][0]["evidence_ids"].append("E002")
        with self.assertRaises(ValueError):
            validate_shadow_response(pack, response)

    def test_coverage_keeps_missing_concrete_source_visible_without_inventing_insight(self):
        pack = build_evidence_pack("Air Purifier", [
            review("price", "This air purifier has a CADR of 702m3/hr and is reasonably priced between 185 and 195."),
            review("social", "Thanks for the air purifier review!"),
            review("budget", "I'm just looking for a budget air purifier that removes dust.")])
        result = {"schema_version": LEGACY_VERSION, "insights": [
            {"id": "I01", "kind": "explicit_need", "summary": "The shopper wants budget dust removal",
             "product": None, "evidence_ids": ["E003"]}], "implications": []}
        audit = audit_shadow_response(pack, result)
        self.assertEqual([item["evidence_id"] for item in audit["missed_coverage"]], ["E001"])
        self.assertFalse(audit["missed_coverage"][0]["model_reason"])
        self.assertEqual(len(audit["insights"]), 1)
        result["schema_version"] = VERSION
        result["insights"][0]["evidence_facts"] = []
        result["omissions"] = [{"evidence_id": "E001", "reason": "The figures are a single consumer account."}]
        self.assertTrue(audit_shadow_response(pack, result)["missed_coverage"][0]["model_reason"])

    def test_exact_facts_keep_price_separate_from_shopper_budget(self):
        source = "This air purifier has a CADR of 702m3/hr and is reasonably priced between 185 and 195."
        pack = build_evidence_pack("Air Purifier", [review("price", source),
            review("budget", "I'm just looking for a budget air purifier that removes dust.")])
        result = {"schema_version": VERSION, "insights": [
            {"id": "I01", "kind": "tradeoff", "summary": "One reviewer considers price alongside airflow",
             "product": None, "evidence_ids": ["E001"],
             "evidence_facts": [
                 {"evidence_id": "E001", "kind": "reported_price", "quote": "priced between 185 and 195"},
                 {"evidence_id": "E001", "kind": "reported_specification", "quote": "CADR of 702m3/hr"}]}],
            "implications": [], "omissions": []}
        self.assertEqual(len(audit_shadow_response(pack, result)["insights"]), 1)
        for key, altered in (("quote", "priced between 185 and 200"), ("kind", "stated_budget")):
            wrong = copy.deepcopy(result)
            wrong["insights"][0]["evidence_facts"][0][key] = altered
            self.assertFalse(audit_shadow_response(pack, wrong)["insights"])
        wrong = copy.deepcopy(result)
        wrong["insights"][0].update(summary="The other shopper has a budget of 195", evidence_ids=["E001", "E002"])
        self.assertFalse(audit_shadow_response(pack, wrong)["insights"])

    def test_only_bad_opportunities_rejected_and_raw_model_response_retained(self):
        result = example()
        item = result["implications"][0]
        item["research_parameters"] = [
            {"kind": "group_count", "value": 2, "unit": "groups", "rationale": "Compare the existing and proposed layout"},
            {"kind": "duration", "value": None, "unit": "hours", "rationale": None}]
        result["implications"] += [
            {**item, "id": "O02", "expected_measurement": "Count listings with HEPA claims"},
            {**item, "id": "O03", "proposal": "Show a price cap of SGD 200"},
            {**item, "id": "O04", "method_type": "message_test"},
            {**item, "id": "O05", "research_parameters": [
                {"kind": "sample_size", "value": 50, "unit": "participants", "rationale": None}]},
            {**item, "id": "O06", "decision_question": ""}]
        original = copy.deepcopy(result)
        audit = audit_shadow_response(self.pack, result)
        self.assertEqual(len(audit["insights"]), 2)
        self.assertEqual([item["id"] for item in audit["implications"]], ["O01"])
        self.assertEqual([item["id"] for item in audit["rejected"]], ["O02", "O03", "O04", "O05", "O06"])
        self.assertEqual(audit["raw"], original)
        self.assertEqual(result, original)
        report = render_shadow_report(self.pack, result)
        self.assertIn("拟定研究参数 · 待用户确认", report)
        self.assertIn("由研究人员确定", report)
        self.assertIn("O02 未采用", report)
        self.assertNotIn("SGD 200", report)

    def test_source_validation_rejects_mismatched_video_and_synthetic_rows(self):
        with self.assertRaises(ValueError):
            build_evidence_pack("Air Purifier", [{**self.rows[0], "video_id": "abcdefghijk"}])
        with self.assertRaises(ValueError):
            build_evidence_pack("Air Purifier", [{**self.rows[0], "is_synthetic": True}])
