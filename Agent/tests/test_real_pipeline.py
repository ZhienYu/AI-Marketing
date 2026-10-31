"""No live data: every review and API response in these tests is synthetic."""

import contextlib
import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import orchestrator
import real_pipeline


class RealPipelineTests(unittest.TestCase):
    def setUp(self):
        self.preview = {
            "mode": "live-read-only", "video_id": "TESTvideo01", "collected_at": "2026-10-31T12:00:00+00:00",
            "comments": [{
                "comment_id": "synthetic-contract-" + str(index),
                "review_text": "SYNTHETIC: price? I used DemoAqua R1. " + "x" * 300,
                "published_at": "2026-01-01T00:00:00Z",
                "source_url": "https://www.youtube.com/watch?v=TESTvideo01&lc=synthetic-contract-" + str(index),
                "is_synthetic": True, "brand": "DemoAqua",
            } for index in range(10)],
        }

    def test_status_cannot_be_enabled_by_mutating_return_value(self):
        status = real_pipeline.analysis_status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["code"], "youtube_analysis_not_authorized")
        status["enabled"] = True
        self.assertFalse(real_pipeline.analysis_status()["enabled"])

    def test_analysis_rejected_before_input_is_accessed(self):
        class Untouchable:
            def __iter__(self):
                raise AssertionError("Must not inspect records")
            def __len__(self):
                raise AssertionError("Must not count records")
        with self.assertRaises(real_pipeline.AnalysisNotAuthorized):
            real_pipeline.run_real_analysis(Untouchable())

    def test_analysis_cannot_be_enabled_by_input_or_environment(self):
        with patch.dict(os.environ, {"YOUTUBE_ANALYSIS_APPROVED": "true", "ALLOW_REAL_ANALYSIS": "1"}):
            for records in ([], [{"approval": True, "is_synthetic": False}], self.preview["comments"]):
                with self.assertRaises(real_pipeline.AnalysisNotAuthorized):
                    real_pipeline.run_real_analysis(records, model="qwen-plus", max_reviews=1)

    def test_blocked_analysis_has_no_key_processing_or_file_side_effects(self):
        mocks = []
        with contextlib.ExitStack() as stack:
            for module, name in (
                (orchestrator.youtube_comments, "load_youtube_key"),
                (orchestrator.classify_reviews, "load_local_settings"),
                (orchestrator.classify_reviews, "classify_qwen"),
                (orchestrator.classify_reviews, "analyze_batch"),
                (orchestrator.qualify_feedback, "qualify_batch"),
                (orchestrator.generate_insights, "generate_insights"),
                (orchestrator.generate_report, "render_report"),
                (orchestrator.classify_reviews, "save_json"),
                (orchestrator.generate_report, "save_report"),
            ):
                mocks.append(stack.enter_context(patch.object(module, name, side_effect=AssertionError("Forbidden side effect"))))
            opening = stack.enter_context(patch("pathlib.Path.open", side_effect=AssertionError("No file access")))
            with self.assertRaises(real_pipeline.AnalysisNotAuthorized):
                real_pipeline.run_real_analysis(self.preview["comments"])
            for mock in mocks + [opening]:
                mock.assert_not_called()

    def test_preview_preserves_factual_evidence_and_does_not_mutate_response(self):
        original = copy.deepcopy(self.preview)
        result = real_pipeline.build_read_only_preview(self.preview)
        self.assertEqual(self.preview, original)
        self.assertEqual(result["count"], 10)
        self.assertEqual(len(result["comments"]), 3)
        row = result["comments"][0]
        for field in ("source_url", "published_at", "comment_id"):
            self.assertEqual(row[field], original["comments"][0][field])
        self.assertEqual(row["collected_at"], original["collected_at"])
        self.assertEqual(row["source_platform"], "youtube")
        self.assertEqual(row["review_id"], "youtube:synthetic-contract-0")
        self.assertTrue(row["is_synthetic"])
        self.assertEqual(len(row["review_text"]), 240)
        self.assertTrue(row["text_is_preview"])

    def test_preview_does_not_infer_brand_sentiment_or_usage(self):
        row = real_pipeline.build_read_only_preview(self.preview)["comments"][0]
        self.assertEqual(row["brand"], "unknown")
        self.assertEqual(row["brand_attribution"], {"status": "unverified", "method": "none", "evidence": []})
        self.assertEqual(row["evidence_quality"]["status"], "not_assessed")
        self.assertIsNone(row["evidence_quality"]["usage_evidence"])
        self.assertFalse(row["evidence_quality"]["verified_purchase"])
        self.assertIsNone(row["feedback_type"])
        self.assertNotIn("sentiment", row)
        self.assertEqual(row["analysis_status"], "not_analyzed")

    def test_empty_preview_is_valid_without_invented_evidence(self):
        result = real_pipeline.build_read_only_preview({**self.preview, "comments": []})
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["comments"], [])

    def test_preview_rejects_missing_collection_time_or_wrong_mode(self):
        for changes in ({"collected_at": None}, {"mode": "mock"}):
            with self.assertRaises(ValueError):
                real_pipeline.build_read_only_preview({**self.preview, **changes})

    def test_orchestrator_adds_utc_collection_time_without_processing(self):
        before = datetime.now(timezone.utc)
        with patch.object(orchestrator.youtube_comments, "load_youtube_key", return_value="FAKE_TEST_KEY"), patch.object(orchestrator.youtube_comments, "fetch_comments", return_value=self.preview["comments"]) as fetch:
            result = orchestrator.preview_live_video({"mode": "live-read-only", "videos": [{"video_id": "TESTvideo01"}]}, "TESTvideo01", live=True)
        after = datetime.now(timezone.utc)
        collected = datetime.fromisoformat(result["collected_at"])
        self.assertLessEqual(before, collected)
        self.assertLessEqual(collected, after)
        self.assertEqual(collected.utcoffset().total_seconds(), 0)
        self.assertEqual(result["comments"], self.preview["comments"])
        fetch.assert_called_once_with("TESTvideo01", "FAKE_TEST_KEY")


if __name__ == "__main__":
    unittest.main()
