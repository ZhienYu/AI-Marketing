import hashlib
import io
import json
import sqlite3
import tempfile
from urllib.error import URLError
import unittest
from pathlib import Path
from unittest.mock import patch

from test_automatic_research import batch, policy
import analysis_control as control
import automatic_research as auto
import classify_reviews as classifier
import multi_comment_research as multi


def batch_policy():
    return {**policy(), "budget_mode": control.BATCH_BUDGET_MODE, "token_bound_verified": False,
            "token_estimate_risk_acknowledged": True, "analysis_schema_version": multi.VERSION,
            "analysis_prompt_sha256": hashlib.sha256(multi.BATCH_PROMPT.encode()).hexdigest(),
            "max_calls": 3, "max_input_tokens": 11000, "max_output_tokens": 3000,
            "run_token_limit": 42000, "run_cny_limit": "0.0444"}


def rows():
    first = auto.normalize_batch(batch())[0]
    items = []
    for n in range(10):
        video_id = f"TESTvideo{n % 3 + 1:02d}"
        cid = f"comment-{n}"
        items.append({**first, "comment_id": cid, "review_id": "youtube:" + cid,
                      "video_id": video_id, "source_url": f"https://www.youtube.com/watch?v={video_id}&lc={cid}",
                      "review_text": f"What price should I pay for the version {n} cleaner?"})
    return items


def inquiry():
    return {"schema_version": multi.VERSION, "sentiment": "Neutral", "facts": [], "potential_needs": [],
            "brand": {"name": "unknown", "evidence_ids": []}, "product_model": {"name": "unknown", "evidence_ids": []},
            "feedback_types": [{"type": "Purchase Inquiry", "evidence_ids": ["S01"]}]}


class MultiCommentTests(unittest.TestCase):
    def test_balances_sources_and_audits_duplicates(self):
        source = rows()
        source += [{**source[0], "review_id": "copy"}, {**source[0], "review_id": "noise", "review_text": "Thanks!"}]
        batches, decisions = multi.select_comments("pool cleaner", source, 11000)
        self.assertEqual([len(group) for group in batches], [4, 4, 2])
        self.assertEqual(len({row["video_id"] for row in batches[0]}), 3)
        self.assertEqual(decisions[-2]["decision"], "正文重复或高度相似")
        self.assertEqual(decisions[-1]["decision"], "信息量不足或仅为互动")

    def test_rejects_unknown_and_duplicate_keys_but_isolates_missing_items(self):
        first = {"key": "R01", "analysis": inquiry()}
        source = rows()[:2]
        for items in ([first, first], [first, {**first, "key": "R03"}]):
            with self.assertRaises(ValueError):
                multi.map_response({"reviews": items}, source)
        self.assertEqual(multi.map_response({"reviews": [first]}, source), [(source[0], first["analysis"]), (source[1], None)])

    def test_uses_shared_transport_and_groups_multiple_real_shaped_sources(self):
        source = rows()
        for row in source:
            row["review_text"] = row["review_text"].replace("should I pay", "should I pay if I buy it")
        def respond(req, *, timeout):
            payload = json.loads(req.data)
            received = json.loads(payload["messages"][1]["content"])["reviews"]
            self.assertEqual(payload["max_tokens"], 3000)
            self.assertLessEqual(len(received), 4)
            self.assertTrue(all(set(item) == {"key", "evidence"} for item in received))
            data = [{"key": item["key"], "analysis": inquiry()} for item in received]
            if len(received) == 2:
                data[0]["analysis"]["feedback_types"][0]["evidence_ids"] = ["S99"]
            return io.StringIO(json.dumps({"model": control.QWEN_MODEL,
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"reviews": data})}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 400, "total_tokens": 1300}}))
        with tempfile.TemporaryDirectory() as temp, patch.object(classifier, "load_local_settings", return_value={"QWEN_API_KEY": "FAKE"}), patch.object(classifier.request, "build_opener") as opener:
            ledger = Path(temp) / "ledger.sqlite3"
            opener.return_value.open.side_effect = respond
            result = multi.run_batch_research("cleaner", source, batch_policy(), "improvement", paid_confirmed=True, ledger_path=ledger)
            self.assertEqual(opener.return_value.open.call_count, 3)
            with sqlite3.connect(ledger) as db:
                self.assertEqual(db.execute("SELECT cost FROM reservations").fetchall(), [("0.0148",)] * 3)
        self.assertEqual(result["status"], "partially_completed")
        self.assertEqual(result["submitted"], 10)
        self.assertEqual(len(result["results"]), 9)
        self.assertIn("价格与预算 · 9 条独立评论", result["report"])
        self.assertIn("**0** 条进入正式属性统计", result["report"])
        self.assertNotIn("S99", result["report"])
        self.assertEqual(result["estimated_cny"], "0.00456")

    def test_report_combines_durability_across_sections_without_counting_content_or_questions_as_faults(self):
        items = rows()[:4]
        examples = [
            ("It stopped working. It went completely kaput.", "facts", "pain_point"),
            ("How long is this expected to last?", "feedback_types", "Purchase Inquiry"),
            ("Your review was very helpful.", "facts", "positive_feedback"),
            ("Is the price higher with a paid subscription?", "facts", "pain_point"),
        ]
        for row, (source, field, kind) in zip(items, examples):
            row["review_text"] = source
            item = {"type": kind} if field == "feedback_types" else {"kind": kind, "summary": source, "aspect": "Reliability"}
            row["processing"] = {"status": "Partial", "raw": {field: [item]},
                "evidence_spans": [{"id": "S01", "text": source}],
                "claim_quality": [{"path": [field, 0], "status": "Needs Review", "evidence_ids": ["S01"]}]}
        state = {"results": items, "collected": 4, "selected": 4, "selected_videos": 3,
                 "submitted": 4, "failures": [], "unprocessed": 0}
        report = multi.render_consumer_report("cleaner", state, [])
        self.assertIn("使用寿命与耐用性** · 产品反馈／购买考虑 · 2 条独立评论", report)
        self.assertIn("待验证研究方向 · 使用寿命与耐用性", report)
        self.assertNotIn("Your review was very helpful", report)
        _, detail = report.split("## Product Experience", 1)
        experience, purchase = detail.split("## Purchase Considerations", 1)
        self.assertNotIn("paid subscription", experience)
        self.assertIn("paid subscription", purchase)

    def test_selection_prioritizes_substance_over_promotion_and_humor_in_earbuds(self):
        items = rows()
        items += [{**items[0], "review_id": "promo", "review_text": "Read more about these earbuds https://example.com/deal"},
                  {**items[1], "review_id": "joke", "review_text": "These earbuds should fly to the moon, just kidding 😂"},
                  {**items[2], "review_id": "video", "review_text": "Your review was very helpful. The link below no longer works."},
                  {**items[3], "review_id": "use", "review_text": "I wore the earbuds all day and the left speaker stopped working."}]
        batches, decisions = multi.select_comments("wireless earbuds", items, 11000)
        selected = {row["review_id"] for group in batches for row in group}
        self.assertIn("use", selected)
        self.assertFalse(selected.intersection({"promo", "joke", "video"}))
        reasons = {row["review_id"]: row["signals"] for row in decisions}
        self.assertIn("外链推广式表述", reasons["promo"])
        self.assertIn("玩笑或转述线索", reasons["joke"])

    def test_compatibility_is_local_and_does_not_move_labels(self):
        row = {**rows()[0], "review_text": "I used it at work."}
        raw = {**inquiry(), "feedback_types": [{"type": "Actual Usage Experience", "evidence_ids": ["S01"]}],
               "facts": [{"id": "f01", "kind": "Usage Scenario", "summary": row["review_text"], "evidence_ids": ["S01"]}]}
        processed = multi.process_batch_comment(raw, row)
        self.assertIn(processed["status"], {"Valid", "Partial"})
        self.assertEqual(processed["normalizations"][0]["to"], "usage_scenario")
        self.assertEqual(raw["facts"][0]["kind"], "Usage Scenario")
        for label in ("Irrelevant", "Unclear", "Usage Scenario"):
            invalid = {**raw, "feedback_types": [{"type": label, "evidence_ids": ["S01"]}]}
            self.assertEqual(multi.process_batch_comment(invalid, row)["status"], "Invalid")
        wrong_field = {**raw, "facts": [{**raw["facts"][0], "kind": "Product Discussion"}]}
        self.assertEqual(multi.process_batch_comment(wrong_field, row)["status"], "Invalid")

    def test_entity_error_can_preserve_exact_source_only(self):
        row = {**rows()[0], "review_text": "I used an Acme Alpha. It stopped working. The repair costs more than a replacement."}
        raw = {**inquiry(), "sentiment": "Negative", "brand": {"name": "Acne", "evidence_ids": ["S01"]},
               "feedback_types": [{"type": "Actual Usage Experience", "evidence_ids": ["S01"]}],
               "facts": [
                   {"id": "f01", "kind": "pain_point", "summary": "It stopped working.", "evidence_ids": ["S02"], "aspect": "Reliability"},
                   {"id": "f02", "kind": "pain_point", "summary": "The repair costs more than a replacement.", "evidence_ids": ["S03"], "aspect": "Repair Cost"},
               ]}
        strict = multi.process_batch_comment(raw, row)
        self.assertEqual(strict["status"], "Invalid")
        observation = multi.entity_source_observations(strict, row)
        self.assertIsNotNone(observation)
        state = {"results": [], "source_observations": [observation], "collected": 1, "selected": 1, "selected_videos": 1,
                 "submitted": 1, "failures": [{}], "unprocessed": 0}
        report = multi.render_consumer_report("smartphone", state, [])
        self.assertIn("It stopped working.", report)
        self.assertIn("维修与售后成本", report)
        self.assertIn("品牌／型号归属未确认", report)
        self.assertNotIn("Acne", report)
        self.assertIn("**0** 条进入正式属性统计", report)
        raw["facts"][0]["evidence_ids"] = ["S99"]
        self.assertIsNone(multi.entity_source_observations(multi.process_batch_comment(raw, row), row))

    def test_final_transport_failure_preserves_previous_results_and_cost(self):
        count = 0
        def respond(req, *, timeout):
            nonlocal count
            count += 1
            if count == 3:
                raise URLError(TimeoutError("private payload and URL"))
            request = json.loads(json.loads(req.data)["messages"][1]["content"])["reviews"]
            content = {"reviews": [{"key": item["key"], "analysis": inquiry()} for item in request]}
            return io.StringIO(json.dumps({"model": control.QWEN_MODEL,
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 400, "total_tokens": 1300}}))
        with tempfile.TemporaryDirectory() as temp, patch.object(classifier, "load_local_settings", return_value={"QWEN_API_KEY": "FAKE"}), patch.object(classifier.request, "build_opener") as opener:
            ledger = Path(temp) / "ledger.sqlite3"
            opener.return_value.open.side_effect = respond
            result = multi.run_batch_research("cleaner", rows(), batch_policy(), "improvement", paid_confirmed=True, ledger_path=ledger)
            with sqlite3.connect(ledger) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM reservations WHERE run = ?", (result["run_id"],)).fetchone()[0], 3)
        self.assertEqual(result["api_calls"], 3)
        self.assertEqual(len(result["results"]), 8)
        self.assertEqual(list(result["outcomes"].values()).count("请求失败，费用未知"), 2)
        self.assertEqual(result["known_cost_cny"], "0.00304")
        self.assertNotIn("estimated_cny", result)
        self.assertIn("stage=open", result["batch_runs"][-1]["reason"])
        self.assertNotIn("private payload", result["batch_runs"][-1]["reason"])

    def test_scoped_selection_prefers_concrete_expectations_and_language_variants(self):
        selected = rows()[:6]
        for row, text in zip(selected, (
            "Would love to see larger batteries and faster charging.",
            "Ingin baterai jumbo tapi desain hp tetap tipis..😂",
            "I used the phone for 7 hours on battery while travelling.",
            "I used the phone and its RAM management reloads apps.",
            "Nice test!",
            "185hz vs 120hz",
        )):
            row["review_text"] = text
        batches, audit = multi.select_comments("Smartphone Battery", selected, 11000)
        self.assertEqual({r["review_id"] for group in batches for r in group},
                         {r["review_id"] for r in selected[:3]})
        self.assertEqual(audit[3]["decision"], "正文未出现研究主题线索")
        self.assertIn("明确期待线索", audit[1]["signals"])
        for query, sample in (
            ("Robot Cleaner Filtration", "I wish it had a finer filter for small debris."),
            ("Wireless Earbuds Comfort", "I wore the earbuds and my ears hurt."),
            ("Software Subscription", "I want to cancel my subscription without calling support."),
        ):
            row = {**selected[0], "review_text": sample}
            picked, _ = multi.select_comments(query, [row], 11000)
            self.assertTrue(picked, query)

    def test_scoped_report_separates_self_reports_preferences_and_source_wishes(self):
        items = rows()[:8]
        texts = [
            "I used my Nova phone on battery for 9 hours of gaming.",
            "My phone dropped to 98% life battery.",
            "If a phone battery gets you through a full day it's a good battery.",
            "I want a 7000mAh battery. Nice test!",
            "I own it and the RAM management reloads apps.",
            "185hz vs 120hz",
            "Would love to see larger batteries and faster charging.",
            "Ingin baterai jumbo tapi desain hp tetap tipis..😂",
        ]
        for row, text in zip(items, texts):
            row["review_text"] = text
        for index, row in enumerate(items[:6]):
            spans = multi.evidence_spans(row["review_text"])
            item = {"kind": "positive_feedback", "summary": row["review_text"], "aspect": "Battery"}
            path = ["facts", 0]
            if index == 5:
                item, path = {"type": "Product Discussion"}, ["feedback_types", 0]
            row["processing"] = {"status": "Partial", "raw": {path[0]: [item]}, "evidence_spans": spans,
                "claim_quality": [{"path": path, "status": "Needs Review", "evidence_ids": [spans[-1]["id"]]}]}
        state = {"results": items[:6], "selected_sources": items, "collected": 8, "selected": 8, "selected_videos": 3,
                 "submitted": 8, "failures": [], "unprocessed": 0}
        hypothetical = {**rows()[8], "review_text": "Just imagine a phone with a 6000 mAh battery. It would be perfect."}
        hypothetical["processing"] = {"status": "Partial", "raw": {"facts": [
            {"kind": "positive_feedback", "summary": "Perfect phone", "aspect": "Battery"}]},
            "evidence_spans": multi.evidence_spans(hypothetical["review_text"]),
            "claim_quality": [{"path": ["facts", 0], "status": "Needs Review", "evidence_ids": ["S01", "S02"]}]}
        state["results"].append(hypothetical)
        state["submitted"] += 1
        report = multi.render_consumer_report("Smartphone Battery", state, [])
        self.assertNotIn("Just imagine", report)
        self.assertIn("9 hours of gaming", report)
        self.assertIn("电池健康度读数 · 自述，含义待核", report)
        self.assertIn("一般评价标准 · 无本人使用结论", report)
        self.assertIn("larger batteries and faster charging", report)
        self.assertIn("电池容量与机身厚度或重量", report)
        self.assertNotIn("RAM management", report)
        self.assertNotIn("185hz vs 120hz", report)
        self.assertNotIn("Nice test!", report)
        self.assertIn("**0** 条进入正式属性统计", report)

    def test_refuses_unpaid_or_changed_frozen_request(self):
        p = batch_policy()
        source = rows()[:2]
        with self.assertRaises(control.ControlError):
            multi.run_batch_research("cleaner", source, p, "improvement", paid_confirmed=False)
        frozen = multi.batch_messages(source)
        execution = control.Execution(p, "improvement", paid_confirmed=True, run_id="test", batch_messages=[frozen])
        with self.assertRaises(control.ControlError):
            execution.reserve({"messages": multi.batch_messages(source[:1])})
        self.assertEqual(execution.reserved_batch_count, 0)
