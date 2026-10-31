"""UI regression tests. All API responses and text below are synthetic."""

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import orchestrator
import real_pipeline

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, "Install Agent/requirements.txt to run Streamlit interface tests")
class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.forbidden = []
        for module, function in (
            (orchestrator.youtube_comments, "load_youtube_key"),
            (orchestrator.youtube_search, "search_videos"),
            (orchestrator.youtube_comments, "fetch_comments"),
            (orchestrator.qualify_feedback, "qualify_feedback"),
            (orchestrator.qualify_feedback, "qualify_batch"),
            (orchestrator.classify_reviews, "load_local_settings"),
            (orchestrator.classify_reviews, "classify_qwen"),
            (orchestrator.classify_reviews, "analyze_batch"),
            (orchestrator.generate_insights, "generate_insights"),
            (orchestrator.generate_report, "render_report"),
            (orchestrator.classify_reviews, "save_json"),
            (orchestrator.generate_report, "save_report"),
            (orchestrator, "run_mock_pipeline"),
            (real_pipeline, "run_real_analysis"),
        ):
            self.forbidden.append(self.stack.enter_context(patch.object(module, function, side_effect=AssertionError("Forbidden processing in UI test: " + function))))
        self.addCleanup(self.assert_no_forbidden_calls)
        videos = orchestrator.youtube_search.normalize_videos(orchestrator.read_fixture("youtube_search_mock.json"), synthetic=True)
        self.discovery = {"mode": "live-read-only", "query": "Robotic Pool Cleaner", "videos": videos}
        self.live_search = self.stack.enter_context(patch.object(orchestrator, "discover_live_videos", return_value=self.discovery))
        self.preview = {
            "mode": "live-read-only", "video_id": "TESTvideo01", "collected_at": "2026-10-31T12:00:00+00:00",
            "comments": [{
                "comment_id": "synthetic-ui-" + str(index), "review_text": "SYNTHETIC UI TEST " + "x" * 300,
                "source_url": "https://www.youtube.com/watch?v=TESTvideo01&lc=synthetic-ui-" + str(index),
                "published_at": "2026-01-01T00:00:00Z", "brand": "unknown", "is_synthetic": True,
            } for index in range(10)],
        }
        self.live_read = self.stack.enter_context(patch.object(orchestrator, "preview_live_video", return_value=self.preview))
        self.app = AppTest.from_file(str(AGENT_DIR / "web_app.py"), default_timeout=15)

    def assert_no_forbidden_calls(self):
        for mock in self.forbidden:
            mock.assert_not_called()

    def ready(self):
        self.app.run()
        self.app.text_input(key="keyword").set_value("Robotic Pool Cleaner").run()
        self.app.checkbox(key="privacy_accepted").check().run()

    def search_and_read(self):
        self.ready()
        self.app.button(key="search_live").click().run()
        self.app.button(key="read_comments").click().run()

    def test_initial_page_has_real_search_without_demo_csv_or_requests(self):
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_input(key="keyword").value, "")
        self.assertIn("LIVE READ-ONLY", self.app.info[0].value)
        self.assertEqual(len(self.app.radio), 0)
        self.assertEqual(len(self.app.get("file_uploader")), 0)
        self.assertEqual(len(self.app.get("download_button")), 0)
        self.assertNotIn("Demo", " ".join(button.label for button in self.app.button))
        self.live_search.assert_not_called()
        self.live_read.assert_not_called()

    def test_privacy_notice_does_not_enable_analysis_or_send_request(self):
        self.app.run()
        self.assertTrue(self.app.button(key="search_live").disabled)
        self.ready()
        self.assertFalse(self.app.button(key="search_live").disabled)
        self.assertTrue(self.app.button(key="analyze_real").disabled)
        self.assertIn("许可", self.app.warning[0].value)
        self.live_search.assert_not_called()
        self.live_read.assert_not_called()

    def test_search_requires_click_and_read_requires_second_click(self):
        self.ready()
        self.app.run()
        self.live_search.assert_not_called()
        self.app.button(key="search_live").click().run()
        self.live_search.assert_called_once_with("Robotic Pool Cleaner", live=True)
        self.live_read.assert_not_called()
        self.assertEqual(len(self.app.radio(key="selected_video").options), 5)
        self.app.run()
        self.live_search.assert_called_once()
        self.live_read.assert_not_called()
        self.app.button(key="read_comments").click().run()
        self.live_read.assert_called_once_with(self.discovery, "TESTvideo01", live=True)
        self.assertFalse(self.app.exception)

    def test_preview_keeps_only_three_short_texts_and_no_files(self):
        self.search_and_read()
        stored = self.app.session_state["live_preview"]
        self.assertEqual(stored["count"], 10)
        self.assertEqual(len(stored["comments"]), 3)
        self.assertTrue(all(len(row["review_text"]) == 240 for row in stored["comments"]))
        self.assertEqual(list(self.temp.iterdir()), [])
        self.assertEqual(len(self.app.get("download_button")), 0)
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.tabs), 0)
        self.assertTrue(self.app.button(key="analyze_real").disabled)
        self.app.run()
        self.live_read.assert_called_once()

    def test_preview_provenance_preserves_source_time_and_unassessed_quality(self):
        self.search_and_read()
        row = self.app.session_state["live_preview"]["comments"][0]
        self.assertEqual(row["source_url"], self.preview["comments"][0]["source_url"])
        self.assertEqual(row["review_id"], "youtube:synthetic-ui-0")
        self.assertEqual(row["video_id"], self.preview["video_id"])
        self.assertEqual(row["collected_at"], self.preview["collected_at"])
        self.assertEqual(row["brand"], "unknown")
        self.assertEqual(row["evidence_quality"]["status"], "not_assessed")
        self.assertIsNone(row["feedback_type"])

    def test_keyword_change_clears_results_without_requests(self):
        self.search_and_read()
        self.app.text_input(key="keyword").set_value("Cordless Vacuum").run()
        self.assertNotIn("live_preview", self.app.session_state)
        self.assertNotIn("live_discovery", self.app.session_state)
        self.live_search.assert_called_once()
        self.live_read.assert_called_once()

    def test_selection_change_clears_preview_without_request(self):
        self.search_and_read()
        self.app.radio(key="selected_video").set_value("TESTvideo02").run()
        self.assertNotIn("live_preview", self.app.session_state)
        self.live_read.assert_called_once()

    def test_clear_drops_live_memory_without_requests(self):
        self.search_and_read()
        self.app.button(key="clear_session").click().run()
        self.assertNotIn("live_preview", self.app.session_state)
        self.assertNotIn("live_discovery", self.app.session_state)
        self.live_search.assert_called_once()
        self.live_read.assert_called_once()

    def test_revoking_notice_clears_results_and_disables_search(self):
        self.search_and_read()
        self.app.checkbox(key="privacy_accepted").uncheck().run()
        self.assertNotIn("live_preview", self.app.session_state)
        self.assertNotIn("live_discovery", self.app.session_state)
        self.assertTrue(self.app.button(key="search_live").disabled)
        self.live_search.assert_called_once()

    def test_old_demo_session_is_discarded_without_execution(self):
        self.app.session_state["demo_bundle"] = {"report": "SYNTHETIC OLD UI REPORT"}
        self.app.session_state["mode"] = "Demo Mode"
        self.app.run()
        self.assertNotIn("demo_bundle", self.app.session_state)
        self.assertNotIn("mode", self.app.session_state)
        self.assertEqual(len(self.app.get("download_button")), 0)

    def test_errors_are_friendly_without_secret_or_url(self):
        self.live_search.side_effect = orchestrator.youtube_comments.YouTubeReadError("category=connection_reset https://example.com/?key=FAKE_SECRET")
        self.ready()
        self.app.button(key="search_live").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn("网络波动", self.app.error[0].value)
        self.assertNotIn("FAKE_SECRET", self.app.error[0].value)
        self.assertNotIn("https://", self.app.error[0].value)
        self.assertNotIn("live_discovery", self.app.session_state)

    def test_comment_failure_drops_old_preview_and_keeps_search(self):
        self.search_and_read()
        self.live_read.side_effect = orchestrator.youtube_comments.YouTubeReadError("http=403; reason=commentsDisabled; key=FAKE_PRIVATE")
        self.app.button(key="read_comments").click().run()
        self.assertNotIn("live_preview", self.app.session_state)
        self.assertIn("live_discovery", self.app.session_state)
        self.assertIn("关闭评论", self.app.error[0].value)
        self.assertNotIn("FAKE_PRIVATE", self.app.error[0].value)

    def test_empty_search_and_comments_have_clear_messages(self):
        self.live_search.return_value = {**self.discovery, "videos": []}
        self.ready()
        self.app.button(key="search_live").click().run()
        self.assertIn("没有找到视频", self.app.info[-1].value)
        self.live_read.assert_not_called()
        self.live_search.return_value = self.discovery
        self.live_read.return_value = {**self.preview, "comments": []}
        self.app.button(key="search_live").click().run()
        self.app.button(key="read_comments").click().run()
        self.assertIn("没有返回", self.app.info[-1].value)

    def test_invalid_keyword_is_rejected_before_discovery(self):
        self.ready()
        for keyword in (" ", "x" * 201):
            self.app.text_input(key="keyword").set_value(keyword).run()
            self.app.button(key="search_live").click().run()
            self.assertIn("1–200", self.app.error[0].value)
        self.live_search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
