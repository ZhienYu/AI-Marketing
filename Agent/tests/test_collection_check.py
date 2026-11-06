"""Source integrity checks using existing substitute responses, never live comments."""
import copy
import json
import unittest
from unittest.mock import patch

from test_automatic_research import batch
import automatic_research as auto


class CollectionCheckTests(unittest.TestCase):
    def test_standard_json_preserves_sources_without_analysis(self):
        source = batch()
        before = copy.deepcopy(source)
        result = auto.inspect_collection(source)
        record = json.loads(json.dumps(result))["records"][0]
        comment = source["videos"][0]["comments"][0]
        self.assertFalse(result["audit"]["issues"])
        for key in ("comment_id", "video_id", "published_at", "review_text", "source_url"):
            self.assertEqual(record[key], comment[key])
        self.assertEqual(record["video_published_at"], source["videos"][0]["video"]["published_at"])
        self.assertEqual(record["collected_at"], source["collected_at"])
        self.assertEqual(record["brand"], "unknown")
        self.assertEqual(source, before)

    def test_wrong_parent_video_is_rejected(self):
        source = batch()
        source["videos"][0]["comments"][0]["video_id"] = "OTHERvideo1"
        result = auto.inspect_collection(source)
        self.assertFalse(result["records"])
        self.assertIn("parent_mismatch", [x["reason"] for x in result["audit"]["issues"]])

    def test_multiple_videos_keep_individual_comment_ownership(self):
        source = batch()
        second = copy.deepcopy(source["videos"][0])
        second["video"].update(video_id="TESTvideo02", video_url="https://www.youtube.com/watch?v=TESTvideo02")
        second["comments"][0].update(comment_id="second-id", video_id="TESTvideo02", source_url="https://www.youtube.com/watch?v=TESTvideo02&lc=second-id")
        source["videos"].append(second)
        source["comment_count"] = 2
        result = auto.inspect_collection(source)
        self.assertFalse(result["audit"]["issues"])
        self.assertEqual([r["video_id"] for r in result["records"]], ["TESTvideo01", "TESTvideo02"])
        self.assertEqual(result["records"][1]["comment_id"], "second-id")

    def test_wrong_comment_link_is_rejected(self):
        source = batch()
        source["videos"][0]["comments"][0]["source_url"] += "wrong"
        self.assertFalse(auto.inspect_collection(source)["records"])

    def test_missing_or_invalid_fields_are_reported(self):
        for field, value in (("published_at", "invalid"), ("source_platform", "other"), ("review_text", ""), ("comment_id", "")):
            with self.subTest(field=field):
                source = batch()
                source["videos"][0]["comments"][0][field] = value
                result = auto.inspect_collection(source)
                self.assertFalse(result["records"])
                self.assertIn(field, [x["field"] for x in result["audit"]["issues"]])

    def test_duplicate_ids_and_incorrect_total_are_reported(self):
        source = batch()
        source["videos"][0]["comments"].append(copy.deepcopy(source["videos"][0]["comments"][0]))
        result = auto.inspect_collection(source)
        self.assertEqual(result["audit"]["received_comments"], 2)
        self.assertEqual(len(result["records"]), 1)
        self.assertIn("count_mismatch", [x["reason"] for x in result["audit"]["issues"]])

    def test_readonly_converts_without_qwen_or_settings(self):
        with patch.object(auto.orchestrator, "multi_video_research", return_value=batch()), patch.object(auto.classifier, "load_local_settings", side_effect=AssertionError("No credentials")), patch.object(auto.classifier, "classify_qwen", side_effect=AssertionError("No Qwen")):
            result = auto.start_research("Pool cleaner", "improvement", 6)
        self.assertEqual(result["mode"], "live-read-only")
        self.assertIsNone(result["report"])
        self.assertEqual(result["audit"]["valid_records"], 1)

    def test_video_timestamp_requires_timezone(self):
        source = batch()
        source["videos"][0]["video"]["published_at"] = "2026-01-01T00:00:00"
        self.assertFalse(auto.inspect_collection(source)["records"])

    def test_failed_video_without_comments_has_no_fake_records(self):
        source = batch()
        source["videos"][0].update(comments=[], failure_reason="评论已关闭")
        source["comment_count"] = 0
        result = auto.inspect_collection(source)
        self.assertFalse(result["records"])
        self.assertFalse(result["audit"]["issues"])

