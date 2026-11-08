import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from business_report_live import build_business_view
from business_report_ui import render_business_report
import automatic_research as auto
from test_automatic_research import batch
from test_multi_comment_research import batch_policy
from multi_comment_research import batch_messages, evidence_spans, process_batch_comment
from test_multi_comment_research import rows, inquiry


def replay(query, observations):
    returned = []
    for row, (text, kind) in zip(rows(), observations):
        row["review_text"] = text
        response = inquiry()
        spans = evidence_spans(text)
        ids = [span["id"] for span in spans]
        if kind != "inquiry":
            response["feedback_types"] = [{"type": "Product Discussion", "evidence_ids": ids}]
            response["facts"] = [{"id": "f01", "kind": kind, "summary": text, "evidence_ids": ids}]
            if kind in {"positive_feedback", "pain_point"}:
                response["facts"][0]["aspect"] = "Performance"
        returned.append({**row, "processing": process_batch_comment(response, row)})
    state = {"results": returned, "submitted": len(returned), "selected_sources": returned}
    return build_business_view(query, state, [], returned)


class LiveBusinessReportTests(unittest.TestCase):
    def test_air_purchase_asks_without_barrier_and_rate_is_not_duration(self):
        view = replay("Air Purifier", [
            ("Which model is quiet enough for a bedroom?", "inquiry"),
            ("I want a budget purifier to remove dust from the air.", "explicit_need"),
            ("This purifier has good CADR of 602m3/hr and the price is reasonable.", "positive_feedback"),
            ("What can I buy if I cannot afford this price?", "inquiry"),
        ])
        self.assertEqual(view.coverage.submitted, 4)
        self.assertIn("选购咨询", {item.badge for item in view.purchase})
        self.assertIn("选购评价", {item.badge for item in view.purchase})
        self.assertIn("待解决障碍", {item.badge for item in view.purchase})
        self.assertNotIn("购买驱动", {item.badge for item in view.purchase})
        self.assertTrue(view.opportunities)
        self.assertNotIn("使用时长", repr(view.opportunities))
        self.assertNotIn("机身厚度", repr(view.opportunities))

    def test_phone_needs_are_separate_from_video_praise_and_ram(self):
        view = replay("Smartphone Battery", [
            ("I want a larger battery and faster charging.", "explicit_need"),
            ("Ingin baterai jumbo tapi desain hp tetap tipis.", "explicit_need"),
            ("I want RAM management to stop reloading apps.", "explicit_need"),
            ("Nice test!", "positive_feedback"),
        ])
        self.assertEqual(view.coverage.qualitative, 2)
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual(view.needs[0].sources, ("S01", "S02"))
        self.assertNotIn("RAM management", repr(view))
        self.assertNotIn("Nice test!", repr(view))

    def test_pool_product_roles_and_no_pair_by_inheritance(self):
        view = replay("Robotic Pool Cleaner", [
            ("I bought the AquaBot XR3 pool cleaner because the price was lower.", "usage_scenario"),
            ("Which model should I buy if I am considering the WaveBot R2 cleaner?", "inquiry"),
        ])
        self.assertTrue(any(item.detail == "已购买" for item in view.competitors))
        self.assertTrue(any(item.detail == "拟购买或考虑" for item in view.competitors))
        self.assertFalse(any(item.badge == "原文对比" for item in view.competitors))

    def test_no_results_never_promotes_selected_source(self):
        source = {**rows()[0], "review_text": "I want a larger battery and faster charging."}
        view = build_business_view("Smartphone Battery", {"submitted": 0, "results": [],
                                   "selected_sources": [source]}, [], [source])
        self.assertEqual(view.coverage.qualitative, 0)
        self.assertEqual(view.sources, ())
        self.assertEqual(view.opportunities, ())
        app = AppTest.from_string(
            "import streamlit as st\nfrom business_report_ui import render_business_report\n"
            "render_business_report(st.session_state.view)\n"
        )
        app.session_state["view"] = view
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("没有通过基本证据检查", app.info[0].value)

    def test_existing_batch_wire_contract_and_topic(self):
        messages = batch_messages(rows()[:1], "Smartphone Battery")
        self.assertIn('"research_topic": "Smartphone Battery"', messages[1]["content"])
        self.assertIn('"key": "R01"', messages[1]["content"])
        self.assertIn("potential_needs", messages[0]["content"])

    def test_keyword_pipeline_builds_view_with_one_existing_batch_request(self):
        collected = batch()
        comment = collected["videos"][0]["comments"][0]
        comment["review_text"] = "Which model should I buy if I need a quieter purifier?"
        content = {"reviews": [{"key": "R01", "analysis": inquiry()}]}
        policy = batch_policy()
        provider = {"model": policy["model"],
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
                    "usage": {"prompt_tokens": 800, "completion_tokens": 250, "total_tokens": 1050}}
        with tempfile.TemporaryDirectory() as temp, (
            patch.object(auto.orchestrator, "multi_video_research", return_value=collected)
        ) as collect, patch.object(auto.classifier, "load_local_settings", return_value={"QWEN_API_KEY": "FAKE"}), (
            patch.object(auto.classifier.request, "build_opener")
        ) as opener:
            opener.return_value.open.return_value = io.StringIO(json.dumps(provider))
            result = auto.start_research("Air Purifier", "improvement", 6, policy=policy,
                                         paid_confirmed=True, ledger_path=Path(temp) / "test.sqlite3")
            collect.assert_called_once()
            opener.return_value.open.assert_called_once()
        self.assertEqual(result["mode"], "research")
        view = result["business_view"]
        self.assertEqual((view.coverage.collected, view.coverage.submitted, view.coverage.qualitative), (1, 1, 1))
        self.assertEqual(view.purchase[0].badge, "选购咨询")
        self.assertEqual(view.sources[0].url, comment["source_url"])
        app = AppTest.from_string(
            "import streamlit as st\nfrom business_report_ui import render_business_report\n"
            "render_business_report(st.session_state.view)\n"
        )
        app.session_state["view"] = view
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("购买考虑", [heading.value for heading in app.header])

    def test_market_discussion_is_neither_product_fault_nor_unscoped_competitor(self):
        view = replay("Air Purifier", [
            ("Why pay for better engineering when marketing can make it sound great?", "pain_point"),
            ("I use the Aero X1 air purifier near my Laptop Pro 7.", "usage_scenario"),
            ("I bought the ClearAir T2 air purifier.", "usage_scenario"),
            ("Which model should I buy?", "inquiry"),
        ])
        self.assertIn("宣传可信度", {item.title for item in view.needs})
        self.assertFalse(any(item.badge.startswith("产品问题线索") for item in view.needs))
        self.assertNotIn("Laptop Pro 7", {item.title for item in view.competitors})
        self.assertIn("ClearAir T2", {item.title for item in view.competitors})
        self.assertNotIn("未进一步分类", {item.title for item in view.summary})
        self.assertFalse(view.opportunities)

    def test_no_competitor_for_explicitly_unrelated_model_output(self):
        row = rows()[0]
        row["review_text"] = "My Atlas Notebook R7 laptop overheats when I play."
        response = inquiry()
        response["feedback_types"] = [{"type": "Irrelevant", "evidence_ids": ["S01"]}]
        result = {**row, "processing": process_batch_comment(response, row)}
        view = build_business_view("Air Purifier", {"results": [result], "submitted": 1}, [], [row])
        self.assertFalse(view.competitors)
        self.assertEqual(view.coverage.qualitative, 0)

    def test_accessory_cost_is_a_purchase_observation_not_competitor_evidence(self):
        view = replay("Air Purifier", [
            ("Bought the Breeze Q3. The filter costs more than I expected.", "usage_scenario"),
        ])
        self.assertIn("滤芯获取与费用", {item.title for item in view.purchase})
        self.assertEqual([item.badge for item in view.competitors], ["原文购买自述"])
        self.assertEqual(view.coverage.formal, 0)

    def test_named_choice_preserves_area_and_filter_cost_without_inflating_coverage(self):
        view = replay("Air Purifier", [
            ("170sq ft ka room hai, should I buy Airstar Lite 4 or Cleara by Mi 4 compact? "
             "Consider a filter cost also..", "inquiry"),
        ])
        self.assertEqual(view.coverage.qualitative, 1)
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual({item.title for item in view.topics}, {"适用面积", "型号选择", "滤芯获取与费用"})
        self.assertEqual({item.title for item in view.purchase}, {"适用面积", "滤芯获取与费用"})
        self.assertIn("170sq ft", view.purchase[0].detail)
        self.assertEqual(view.competitors[0].title, "Airstar Lite 4 / Cleara by Mi 4 compact")
        self.assertEqual(view.competitors[0].badge, "原文选购候选")
        self.assertEqual(view.opportunities[0].badge, "单条来源 · 探索性机会")
        self.assertEqual(view.summary[0].sources, ("S01",))
        self.assertIn("未提供实际购买决定", view.summary[0].detail)

    def test_two_comments_must_each_support_the_combined_opportunity(self):
        view = replay("Air Purifier", [
            ("For my 160 sq ft room, should I buy Air Max 2 or Clean Pro 8? Filter costs matter.", "inquiry"),
            ("Should I buy Clean Pro 8 or Air Max 2?", "inquiry"),
            ("For my 21 m² room, should I buy Clean Pro 8 or Air Max 2? Consider filter cost.", "inquiry"),
        ])
        self.assertEqual(view.competitors[0].sources, ("S01", "S02", "S03"))
        self.assertEqual(view.opportunities[0].sources, ("S01", "S03"))
        self.assertEqual(view.opportunities[0].badge, "多条评论支持 · 小样本")

    def test_non_model_numeric_options_are_not_competitor_names(self):
        from business_purchase_signals import purchase_choice

        self.assertIsNone(purchase_choice("Should I buy 100 sq ft or 200 sq ft?"))
        self.assertIsNone(purchase_choice("Should I buy Air Max 2 or Air Max 2?"))
        self.assertIsNone(purchase_choice("I bought Air Max 2. My 160 sq ft room is small."))

    def test_budget_and_ozone_are_literal_constraints_not_product_claims(self):
        view = replay("Air Purifier", [
            ("For my room air purifier, should I buy one if I don't want to spend more than 110£ "
             "and I don't want any ozone release?", "inquiry"),
        ])
        self.assertEqual({item.title for item in view.purchase}, {"明确预算上限", "臭氧释放要求"})
        self.assertIn("110£", next(item.detail for item in view.purchase if item.title == "明确预算上限"))
        self.assertEqual(view.coverage.qualitative, 1)
        self.assertEqual(view.coverage.formal, 0)

    def test_reported_price_and_ozone_claim_do_not_become_personal_constraints(self):
        from business_purchase_signals import purchase_constraints

        self.assertEqual(purchase_constraints("It cleans without ozone. I can spend more than 110£."),
                         (None, False))

    def test_literal_preference_does_not_become_a_fault(self):
        view = replay("Air Purifier", [
            ("Not requiring an account is a selling point. I'm sick of having accounts for everything.", "pain_point"),
        ])
        self.assertEqual([(card.badge, card.sources) for card in view.needs], [("正面产品偏好", ("S01",))])
        self.assertNotIn("修复", repr(view.summary))
        self.assertEqual(view.coverage.qualitative, 1)

    def test_literal_named_alternatives_preserve_scope_and_do_not_rank(self):
        from evidence_analysis import evidence_spans
        from report_evidence import literal_claims

        cases = (
            ("May I know why Vega 3200 isn't on the recommendation together with night 2 and calm 200s?",
             "recommendation", ("Vega 3200", "night 2", "calm 200s")),
            ("Clear One vs light 4 can you please suggest", "choice", ("Clear One", "light 4")),
            ("Whats your thoughts on the edge vs light 2? I am stuck between these two",
             "choice", ("edge", "light 2")),
        )
        for text, kind, names in cases:
            with self.subTest(text=text):
                claims = literal_claims("Air Purifier", evidence_spans(text))
                self.assertEqual([(item.kind, item.names) for item in claims], [(kind, names)])
        self.assertFalse(literal_claims("Air Purifier", evidence_spans("Purchase links: https://example.com")))

    def test_invalid_consultation_label_preserves_purchase_and_accessory_cost(self):
        row = rows()[0]
        row["review_text"] = "Bought Cloud Mini for 6k from a shop. The filter is available and costs 2k."
        raw = inquiry()
        raw["feedback_types"][0]["evidence_ids"] = ["S01", "S02"]
        failure = process_batch_comment(raw, row)
        self.assertEqual(failure["status"], "Invalid")
        view = build_business_view("Air Purifier", {
            "results": [], "submitted": 1, "failures": [{"review_id": row["review_id"], "processing": failure}],
        }, [], [row])
        self.assertEqual(view.coverage.qualitative, 1)
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual(view.competitors[0].badge, "原文购买自述")
        self.assertIn("2k", view.purchase[0].detail)
        self.assertNotIn("6k", view.purchase[0].detail)

    def test_history_preview_labels_collection_and_replay_separately(self):
        view = replay("Air Purifier", [("Which model should I buy?", "inquiry")])
        app = AppTest.from_string(
            "import streamlit as st\nfrom business_report_ui import render_business_report\n"
            "render_business_report(st.session_state.view, original_collection=(27, 4))\n"
        )
        app.session_state["view"] = view
        app.run()
        self.assertFalse(app.exception)
        html = " ".join(item.proto.body for item in app.get("html"))
        self.assertIn("原轮采集 · 4 个视频", html)
        self.assertIn("本次回放 · 1 个视频", html)
        self.assertIn("历史离线回放", html)
