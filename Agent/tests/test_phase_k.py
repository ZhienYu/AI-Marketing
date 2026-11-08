from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic

import unittest

from streamlit.testing.v1 import AppTest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import analysis_control as control
import automatic_research as automatic
from business_report_live import _phase_k_groups
from business_report_view import ReportItem
import multi_comment_research as multi
import orchestrator
from session_memory import SessionResult
from test_multi_comment_research import batch_policy, inquiry
import youtube_comments
import youtube_search


PROFILE = control.BATCH_PROFILES[control.PHASE_K]
STAMP = "2026-10-01T00:00:00Z"
TOPIC = "Air Purifier"


def policy_for_test():
    base = {**batch_policy(), "_config_digest": "offline-only", "phase_k_scope": {
        "approved": True, "approval_reference": "OFFLINE FIXTURE ONLY",
        "videos": 20, "comments_per_video": 50, "model_comments": 80,
    }}
    return base, control.with_batch_profile(base, control.PHASE_K)


def video_id(index):
    return f"kVideo{index:05}"


def text_for(video, comment):
    return f"Room {video}-{comment} air purifier: which model would you recommend for my office?"


def source_rows(videos=20, per_video=50):
    return [{
        "review_id": f"youtube:k-{v}-{c}", "comment_id": f"k-{v}-{c}",
        "review_text": text_for(v, c), "video_id": video_id(v),
        "source_url": f"https://www.youtube.com/watch?v={video_id(v)}&lc=k-{v}-{c}",
        "published_at": STAMP, "collected_at": STAMP, "source_platform": "youtube",
        "is_synthetic": False,
    } for v in range(videos) for c in range(per_video)]


class PhaseKTests(unittest.TestCase):
    def test_official_one_page_collection_caps_and_raw_count(self):
        def search(request, *, operation):
            params = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(params["maxResults"], ["20"])
            self.assertIn("publishedAfter", params)
            self.assertNotIn("pageToken", params)
            return {"items": [{
                "id": {"kind": "youtube#video", "videoId": video_id(v)},
                "snippet": {"title": f"Purifier demonstration {v}", "channelTitle": f"Channel {v}",
                            "channelId": f"channel-{v}", "publishedAt": STAMP},
            } for v in range(22)]}
        def comments(request, *, operation):
            params = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(params["maxResults"], ["50"])
            self.assertNotIn("pageToken", params)
            self.assertNotIn("publishedAfter", params)
            video = params["videoId"][0]
            index = int(video[-5:])
            return {"items": [{"snippet": {"videoId": video, "topLevelComment": {
                "id": f"k-{index}-{c}", "snippet": {"textDisplay": text_for(index, c),
                                                    "publishedAt": STAMP}}}} for c in range(52)]}
        with patch.object(youtube_comments, "load_youtube_key", return_value="OFFLINE"), (
            patch.object(youtube_search, "request_json", side_effect=search)
        ) as search_mock, patch.object(youtube_comments, "request_json", side_effect=comments) as comments_mock:
            batch = orchestrator.multi_video_research(TOPIC, live=True, phase_k=True)
        self.assertEqual((search_mock.call_count, comments_mock.call_count), (1, 20))
        self.assertEqual((batch["raw_comments_received"], batch["comment_count"], batch["channel_count"]), (1000, 1000, 20))
        audit = automatic.inspect_collection(batch)["audit"]
        self.assertEqual((audit["valid_records"], audit["issues"]), (1000, []))

    def test_video_diversity(self):
        videos = [{"video_id": video_id(i), "title": title, "channel_title": channel}
                  for i, (title, channel) in enumerate([
                      ("Quiet review", "a"), ("Cleaning", "a"), ("Night use", "a"),
                      ("Review quiet", "b"), ("Filter costs", "b")])]
        selected, exclusions = orchestrator._diverse_videos(videos)
        self.assertEqual([v["video_id"] for v in selected], [video_id(i) for i in (0, 1, 4)])
        self.assertEqual(exclusions, {"频道上限": 1, "标题高度重复": 1})

    def test_no_collection_without_scale_authorization(self):
        base, _ = policy_for_test()
        base.pop("phase_k_scope")
        phase = control.with_batch_profile(base, control.PHASE_K)
        with patch.object(automatic, "load_policy", return_value=base), (
            patch.object(orchestrator, "multi_video_research")
        ) as collect:
            result = automatic.start_research(TOPIC, "improvement", 6, policy=phase, paid_confirmed=True)
        self.assertEqual(result["mode"], "blocked")
        collect.assert_not_called()

    def test_page_exposes_locked_pilot_and_keeps_standard_modes(self):
        base, _ = policy_for_test()
        base.pop("phase_k_scope")
        with patch.object(control, "load_config", return_value=base), (
            patch.object(orchestrator, "multi_video_research")
        ) as collect:
            app = AppTest.from_file(str(Path(control.__file__).with_name("web_app.py"))).run()
            self.assertFalse(app.exception)
            mode = app.radio(key="batch_profile")
            self.assertEqual(len(mode.options), 3)
            mode.set_value(control.PHASE_K).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key="start_research").disabled)
            self.assertTrue(any("扩容授权" in warning.value for warning in app.warning))
            collect.assert_not_called()

    def test_thousand_rows_select_eighty_without_engagement(self):
        rows = source_rows()
        rows[2]["review_text"] = rows[1]["review_text"]
        rows[4]["review_text"] = "Nice video!!!"
        batches, audit = multi.select_comments(TOPIC, rows, control.BATCH_INPUT, profile=PROFILE)
        self.assertEqual([len(batch) for batch in batches], [4] * 20)
        self.assertEqual(len({row["video_id"] for batch in batches for row in batch}), 20)
        counts = Counter(item["decision"] for item in audit)
        self.assertEqual(counts["入选"], 80)
        self.assertEqual(counts["正文重复或高度相似"], 1)
        self.assertEqual(counts["仅视频评价或无上下文数字比较"], 1)

    def test_token_packing_and_no_padding(self):
        rows = source_rows(4, 50)
        rows[0]["review_text"] += " " + "large " * 145
        for row in rows[1:]:
            row["review_text"] += " " + "ample " * 100
        # Use a ceiling just below four moderately long comments, but above one.
        limit = control.message_token_estimate(multi.batch_messages(rows[1:5], TOPIC)) - 10
        batches, audit = multi.select_comments(TOPIC, rows, limit, profile=PROFILE)
        self.assertLess(sum(map(len, batches)), 80)
        self.assertTrue(batches)
        self.assertLessEqual(len(batches), 20)
        self.assertTrue(all(control.message_token_estimate(multi.batch_messages(batch, TOPIC)) <= limit
                            for batch in batches))
        few, _ = multi.select_comments(TOPIC, source_rows(1, 3), control.BATCH_INPUT, profile=PROFILE)
        self.assertEqual(sum(map(len, few)), 3)

    def run_with_mocks(self, *, seed="0", broken=False, deadline=None):
        base, phase = policy_for_test()
        with TemporaryDirectory() as temp:
            ledger = Path(temp) / "budget.sqlite"
            if seed != "0":
                with closing(sqlite3.connect(ledger)) as db, db:
                    db.execute("CREATE TABLE reservations(day TEXT, run TEXT, cost TEXT, tokens INTEGER)")
                    db.execute("INSERT INTO reservations VALUES(?, 'other', ?, 0)",
                               (datetime.now(timezone.utc).date().isoformat(), seed))
            calls = 0
            def respond(request, **kwargs):
                nonlocal calls
                calls += 1
                payload = json.loads(request.data)
                items = json.loads(payload["messages"][1]["content"])["reviews"]
                text = "{" if broken and calls in (2, 11) else json.dumps({"reviews": [
                    {"key": item["key"], "analysis": inquiry()} for item in items
                    if not (broken and calls == 3 and item["key"] == "R01")
                ]})
                return io.StringIO(json.dumps({"model": control.QWEN_MODEL,
                    "choices": [{"finish_reason": "length" if broken and calls == 13 else "stop",
                                 "message": {"content": text}}],
                    "usage": {"prompt_tokens": 1800, "completion_tokens": 500, "total_tokens": 2300}}))
            with patch.object(control, "load_policy", return_value=base), (
                patch.object(multi.classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "OFFLINE"})
            ), patch.object(multi.classifier.request, "build_opener") as opener:
                opener.return_value.open.side_effect = respond
                result = multi.run_batch_research(TOPIC, source_rows(), phase, "improvement",
                                                  paid_confirmed=True, ledger_path=ledger, deadline=deadline)
            if ledger.exists():
                with closing(sqlite3.connect(ledger)) as db:
                    costs = [Decimal(row[0]) for row in db.execute(
                        "SELECT cost FROM reservations WHERE run <> 'other'")]
            else:
                costs = []
            return result, calls, sum(costs, Decimal(0))

    def test_isolates_batch_json_and_missing_item(self):
        result, calls, reserved = self.run_with_mocks(broken=True)
        self.assertEqual((calls, reserved, result["submitted"]), (20, Decimal("0.2960"), 80))
        self.assertEqual(result["status"], "partially_completed")
        self.assertEqual(list(result["outcomes"].values()).count("批次输出截断"), 4)
        self.assertEqual(len(result["results"]), 67)
        self.assertEqual(len({row["review_id"] for row in result["results"]}), 67)
        self.assertFalse(any("raw_model_text" in row for row in result["responses"]))
        view = result["business_view"]
        self.assertEqual(view.coverage.formal, 0)
        self.assertEqual(view.coverage.qualitative, 67)
        self.assertLess(len(view.purchase), 8)

    def test_budget_and_deadline_stop_before_qwen(self):
        for kwargs, reason in (({"seed": ".71"}, "permission_or_budget_stopped"),
                               ({"deadline": monotonic()-1}, "time_limited")):
            result, calls, reserved = self.run_with_mocks(**kwargs)
            self.assertEqual((result["status"], calls, reserved), (reason, 0, 0))

    def test_same_topic_merges_unique_sources_and_price_values_stay_separate(self):
        items = [ReportItem("续航", "原文示例甲", ("S01", "S02"), "体验"),
                 ReportItem("续航", "原文示例乙", ("S02", "S03"), "体验"),
                 ReportItem("成交价", "20 元", ("S01",), "自述"),
                 ReportItem("成交价", "30 元", ("S02",), "自述")]
        output = _phase_k_groups(items, by_topic=True)
        self.assertEqual(output[0].sources, ("S01", "S02", "S03"))
        self.assertEqual(len(output), 3)

    def test_phase_k_result_lifetime_clears(self):
        stored = SessionResult({"mode": "research", "body": source_rows()}, ttl=.01)
        stored._timer.join(1)
        self.assertEqual(stored.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
