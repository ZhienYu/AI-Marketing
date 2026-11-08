import unittest

from business_report_live import build_business_view
from multi_comment_research import evidence_spans, process_batch_comment
from report_evidence import independent_claims
from test_multi_comment_research import inquiry, rows


class IndependentEvidenceTests(unittest.TestCase):
    def test_choice_preserves_candidate_quotes_and_untied_context(self):
        view = self.report(
            "What would you recommend between the North Star X5 (180€) and the Echo Wave R4 (160€)? "
            "I just connect them to my phone and listen to music.",
            "Purchase Inquiry",
        )
        self.assertEqual(view.coverage.qualitative, 1)
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual(view.competitors[0].title, "North Star X5 / Echo Wave R4")
        self.assertIn("180€ / 160€", view.competitors[0].detail)
        self.assertTrue(any(item.title == "连接手机听歌" for item in view.purchase))
        self.assertNotIn("明确预算上限", {item.title for item in view.purchase})

    def test_bad_brand_does_not_erase_usage_or_turn_friend_into_user(self):
        view = self.report(
            "I am not happy with my Echo Wave R4, friends complain about call quality "
            "and I keep having the earbuds cutting the sound when I listen to music "
            "and I don't like how they sit in my ear.",
            "Product Discussion", "Echo Wave R4", "Uncited Brand", expected_invalid=True,
        )
        self.assertEqual(view.coverage.qualitative, 1)
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual({item.title for item in view.needs}, {"听音乐时断音", "佩戴贴合感", "通话质量反馈"})
        self.assertIn("转述他人反馈", {item.badge for item in view.needs})
        self.assertNotIn("Uncited Brand", repr(view))

    def test_battery_repair_is_one_observation_without_runtime(self):
        view = self.report(
            "Good product, but when the battery starts to wane down - irreparable. Consumers buy again, bank breaker.",
            "Product Discussion",
        )
        self.assertEqual([item.title for item in view.needs], ["电池老化后的维修与换新"])
        self.assertIn("换新会带来额外支出", view.summary[0].detail)
        self.assertNotIn("续航与充电", {item.title for item in view.topics})

    def test_quotes_returns_and_subscription_questions_have_distinct_roles(self):
        for source, model, expected in (
            ("You can get the Wave 5 in Malaysia as low as RM 400.", "Wave 5", "regional_quote"),
            ("I bought the Wave 5 and returned it because I couldn't get a seal in my ears and switched to Echo 2.",
             "", "return_choice"),
            ("Is it true you need a paid subscription for case features?", "", "access_question"),
            ("Price???", "", "price_question"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual([c.kind for c in independent_claims(evidence_spans(source), model)], [expected])
        self.assertFalse(independent_claims(evidence_spans("This feature requires a paid subscription.")))
        self.assertFalse(independent_claims(evidence_spans("I bought the Wave 5 and returned it because I couldn't find the receipt and switched to Echo 2.")))

    def test_media_criticism_does_not_erase_a_separate_access_question(self):
        view = self.report(
            'Is it true you need a paid subscription to record? This is omitted from every "professional" review.',
            "Product Discussion",
        )
        self.assertIn("使用功能前是否需要付费订阅", {item.title for item in view.purchase})
        self.assertIn("功能要付费吗？", {item.title for item in view.opportunities})
        self.assertNotIn("第三方协议", repr(view.purchase))

    def test_unrelated_or_missing_result_does_not_gain_evidence(self):
        view = self.report("Price???", "Irrelevant")
        self.assertFalse(view.sources)
        self.assertFalse(view.opportunities)

    def report(self, source, label, model="unknown", brand="unknown", *, expected_invalid=False):
        row = {**rows()[0], "review_text": source}
        wire = inquiry()
        ids = [span["id"] for span in evidence_spans(source)]
        wire.update(feedback_types=[{"type": label, "evidence_ids": ids}])
        for field, name in (("brand", brand), ("product_model", model)):
            if name != "unknown":
                wire[field] = {"name": name, "evidence_ids": ids}
        processed = process_batch_comment(wire, row)
        result = {**row, "processing": processed}
        self.assertEqual(processed["status"] == "Invalid", expected_invalid)
        state = {"results": [] if expected_invalid else [result],
                 "failures": [result] if expected_invalid else [], "submitted": 1}
        return build_business_view("Wireless Earbuds", state, [], [row])
