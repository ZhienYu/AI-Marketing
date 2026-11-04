"""Synthetic responses only; no real APIs or credentials."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrator as o


class MultiVideoTests(unittest.TestCase):
    def setUp(self):
        self.videos = o.youtube_search.normalize_videos(o.read_fixture("youtube_search_mock.json"), synthetic=True)
        self.comments = o.youtube_comments.normalize_comments(o.read_fixture("pipeline_synthetic.json")["comment_threads"], "TESTvideo01", synthetic=True)

    def run_batch(self, responses=None, videos=None):
        with patch.object(o.youtube_comments, "load_youtube_key", return_value="FAKE"), patch.object(o.youtube_search, "search_videos", return_value=self.videos if videos is None else videos) as search, patch.object(o.youtube_comments, "fetch_comments", side_effect=responses or [self.comments] * 5) as fetch, patch.object(o.qualify_feedback, "qualify_batch", side_effect=AssertionError("No analysis")), patch.object(o.classify_reviews, "analyze_batch", side_effect=AssertionError("No Qwen")), patch.object(o.classify_reviews, "save_json", side_effect=AssertionError("No storage")):
            result = o.multi_video_research("Pool Cleaner", live=True)
        return result, search, fetch

    def test_limits_and_global_deduplication(self):
        result, search, fetch = self.run_batch()
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual(result["comment_count"], 10)
        self.assertEqual(result["videos_with_comments"], 1)
        self.assertIn("published_after", search.call_args.kwargs)
        self.assertTrue(all(row["brand"] == "unknown" for row in result["videos"][0]["comments"]))

    def test_partial_failures_and_empty_pages(self):
        error = o.youtube_comments.YouTubeReadError
        result, _, fetch = self.run_batch([self.comments, error("commentsDisabled"), [], error("category=timeout secret=FAKE"), []])
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual([row["status"] for row in result["videos"]], ["success", "failed", "empty", "failed", "empty"])
        self.assertNotIn("FAKE", str(result))

    def test_quota_stops_following_requests_and_preserves_results(self):
        result, _, fetch = self.run_batch([self.comments, o.youtube_comments.YouTubeReadError("http=403;quotaExceeded")])
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(result["stopped_early"])
        self.assertEqual(result["comment_count"], 10)
        self.assertEqual(result["videos"][-1]["status"], "not_requested")

    def test_duplicate_videos_are_not_requested_twice(self):
        result, _, fetch = self.run_batch(videos=[self.videos[0]] * 5)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["unique_videos"], 1)

    def test_empty_search_makes_no_comment_request(self):
        result, _, fetch = self.run_batch(videos=[])
        fetch.assert_not_called()
        self.assertEqual(result["comment_count"], 0)

    def test_gates_before_key_access(self):
        with patch.object(o.youtube_comments, "load_youtube_key", side_effect=AssertionError("No key")):
            for kwargs in ({}, {"live": True, "months": 4}):
                with self.assertRaises(ValueError):
                    o.multi_video_research("Cleaner", **kwargs)

    def test_calendar_month_end_and_leap_year(self):
        self.assertEqual(o.video_cutoff(6, datetime(2024, 8, 31, tzinfo=timezone.utc)), "2024-02-29T00:00:00Z")
        self.assertEqual(o.video_cutoff(12, datetime(2024, 2, 29, tzinfo=timezone.utc)), "2023-02-28T00:00:00Z")

    def test_optional_normalizers_remove_duplicates(self):
        payload = o.read_fixture("youtube_search_mock.json")
        payload["items"][1] = payload["items"][0]
        self.assertEqual(len(o.youtube_search.normalize_videos(payload, deduplicate=True)), 4)
        payload = o.read_fixture("pipeline_synthetic.json")["comment_threads"]
        payload["items"][1] = payload["items"][0]
        self.assertEqual(len(o.youtube_comments.normalize_comments(payload, "TESTvideo01", deduplicate=True)), 9)


if __name__ == "__main__":
    unittest.main()
