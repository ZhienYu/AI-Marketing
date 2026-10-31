import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import orchestrator


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.payload = orchestrator.read_fixture("pipeline_synthetic.json")
        self.videos = orchestrator.youtube_search.normalize_videos(orchestrator.read_fixture("youtube_search_mock.json"))

    def mock_run(self):
        with patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No credentials in Mock")), patch.object(orchestrator.youtube_search, "search_videos", side_effect=AssertionError("No live search in Mock")), patch.object(orchestrator.youtube_comments, "fetch_comments", side_effect=AssertionError("No live comments in Mock")), patch.object(orchestrator.classify_reviews, "classify_qwen", side_effect=AssertionError("No Qwen")):
            return orchestrator.run_mock_pipeline("Robotic Pool Cleaner", output_root=self.temp)

    def test_complete_mock_pipeline_uses_all_stages(self):
        summary = self.mock_run()
        self.assertEqual(summary["discovered_videos"], 5)
        self.assertEqual(summary["read_comments"], 10)
        self.assertEqual(summary["analyzed_usage_reviews"], 3)
        root = Path(summary["run_directory"])
        for name in ("discovery.json", "qualification.json", "feedback_groups.json", "classifications.json", "insights.json", "synthetic_reviews.csv", "pipeline_summary.json", "market_research_report.md"):
            self.assertTrue((root / name).exists(), name)
        report = Path(summary["report_path"]).read_text()
        self.assertIn("DEMO — SYNTHETIC DATA", report)
        self.assertIn("Pipeline Feedback Qualification", report)
        self.assertIn("Insufficient Data", report)
        self.assertNotIn("https://", report)
        self.assertIn("| DemoAqua | 1 | Insufficient Data |", report)
        self.assertIn("| DemoPool | 2 | Insufficient Data |", report)

    def test_feedback_groups_are_kept_separate_and_unknown_not_promoted(self):
        summary = self.mock_run()
        groups = summary["feedback_groups"]
        self.assertEqual(len(groups["general_product_feedback"]), 2)
        self.assertEqual(len(groups["feedback_types"]["Purchase Inquiry"]), 2)
        self.assertEqual(len(groups["feedback_types"]["Content Feedback"]), 1)
        self.assertEqual(len(groups["feedback_types"]["Irrelevant/Unclear"]), 1)
        self.assertIn("youtube:pipeline-07", groups["needs_review"])
        classified = json.loads((Path(summary["run_directory"]) / "classifications.json").read_text())
        self.assertEqual({row["review_id"] for row in classified["results"]}, {"youtube:pipeline-01", "youtube:pipeline-02", "youtube:pipeline-09"})
        self.assertTrue(all(row["is_synthetic"] for row in classified["results"]))
        qualification = json.loads((Path(summary["run_directory"]) / "qualification.json").read_text())
        by_id = {row["review_id"]: row for row in qualification["results"]}
        self.assertEqual(by_id["youtube:pipeline-06"]["brand"], "unknown")
        self.assertEqual(by_id["youtube:pipeline-03"]["product_sentiment"], "Not Expressed")

    def test_mock_repeated_runs_preserve_previous_report(self):
        first = self.mock_run()
        report = Path(first["report_path"])
        before = report.read_bytes()
        second = self.mock_run()
        self.assertNotEqual(first["run_directory"], second["run_directory"])
        self.assertEqual(report.read_bytes(), before)

    def test_mock_command_entry_point_runs_complete_pipeline(self):
        original_run = orchestrator.run_mock_pipeline
        output = io.StringIO()
        with patch.object(orchestrator, "run_mock_pipeline", side_effect=lambda query: original_run(query, output_root=self.temp)), patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No key in Mock")), contextlib.redirect_stdout(output):
            self.assertEqual(orchestrator.main(["Robotic Pool Cleaner"]), 0)
        self.assertIn("DEMO — SYNTHETIC DATA", output.getvalue())
        self.assertEqual(len(list(self.temp.glob("mock-*/market_research_report.md"))), 1)

    def test_no_usage_candidates_produces_insufficient_evidence_without_inventing(self):
        payload = copy.deepcopy(self.payload)
        for item in payload["comment_threads"]["items"]:
            item["snippet"]["topLevelComment"]["snippet"]["textDisplay"] = "price?"
        original_read = orchestrator.read_fixture
        with patch.object(orchestrator, "read_fixture", side_effect=lambda name: payload if name == "pipeline_synthetic.json" else original_read(name)):
            summary = self.mock_run()
        self.assertEqual(summary["analyzed_usage_reviews"], 0)
        self.assertIn("Insufficient Evidence", Path(summary["report_path"]).read_text())

    def test_classification_failure_is_recorded_without_fabrication(self):
        payload = copy.deepcopy(self.payload)
        del payload["classifications"]["youtube:pipeline-02"]
        original_read = orchestrator.read_fixture
        with patch.object(orchestrator, "read_fixture", side_effect=lambda name: payload if name == "pipeline_synthetic.json" else original_read(name)):
            summary = self.mock_run()
        self.assertEqual(summary["classification_failures"], 1)
        self.assertEqual(summary["analyzed_usage_reviews"], 2)
        classified = json.loads((Path(summary["run_directory"]) / "classifications.json").read_text())
        self.assertNotIn("youtube:pipeline-02", {row["review_id"] for row in classified["results"]})

    def test_non_synthetic_pipeline_fixture_rejected_before_writing(self):
        payload = copy.deepcopy(self.payload)
        payload["is_synthetic"] = False
        original_read = orchestrator.read_fixture
        with patch.object(orchestrator, "read_fixture", side_effect=lambda name: payload if name == "pipeline_synthetic.json" else original_read(name)):
            with self.assertRaises(ValueError):
                self.mock_run()
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_live_functions_require_explicit_permission(self):
        with patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No key read")):
            with self.assertRaises(ValueError):
                orchestrator.discover_live_videos("Cleaner")
            with self.assertRaises(ValueError):
                orchestrator.preview_live_video({"mode": "mock", "videos": self.videos}, "TESTvideo01", live=True)

    def run_live_cli(self, arguments, selection="1", videos=None, fetch_failure=None):
        comments = orchestrator.youtube_comments.normalize_comments(self.payload["comment_threads"], "TESTvideo01")
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "AGENT_DIR", self.temp))
            key_loader = stack.enter_context(patch.object(orchestrator.youtube_comments, "load_youtube_key", return_value="fake-test-key"))
            search = stack.enter_context(patch.object(orchestrator.youtube_search, "search_videos", return_value=self.videos if videos is None else videos))
            fetch = stack.enter_context(patch.object(orchestrator.youtube_comments, "fetch_comments", return_value=comments, side_effect=fetch_failure))
            stack.enter_context(patch("builtins.input", return_value=selection))
            stack.enter_context(patch.object(orchestrator.qualify_feedback, "qualify_batch", side_effect=AssertionError("Live qualification forbidden")))
            stack.enter_context(patch.object(orchestrator.classify_reviews, "analyze_batch", side_effect=AssertionError("Live classification forbidden")))
            stack.enter_context(patch.object(orchestrator.generate_insights, "generate_insights", side_effect=AssertionError("Live insights forbidden")))
            stack.enter_context(patch.object(orchestrator.generate_report, "render_report", side_effect=AssertionError("Live report forbidden")))
            stack.enter_context(patch.object(orchestrator.classify_reviews, "save_json", side_effect=AssertionError("Live persistence forbidden")))
            stack.enter_context(patch.object(orchestrator.generate_report, "save_report", side_effect=AssertionError("Live persistence forbidden")))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(output))
            code = orchestrator.main(arguments)
        self.assertEqual(list(self.temp.iterdir()), [])
        self.assertNotIn("fake-test-key", output.getvalue())
        return code, output.getvalue(), search.call_count, fetch.call_count, key_loader.call_count

    def test_live_search_only_never_reads_comments_or_qualifies(self):
        code, output, searches, reads, keys = self.run_live_cli(["Cleaner", "--live", "--search-only"])
        self.assertEqual((code, searches, reads, keys), (0, 1, 0, 1))
        self.assertIn("LIVE READ-ONLY", output)

    def test_live_manual_selection_only_previews_three(self):
        code, output, searches, reads, keys = self.run_live_cli(["Cleaner", "--live"])
        self.assertEqual((code, searches, reads, keys), (0, 1, 1, 2))
        self.assertEqual(output.count("comment_id="), 3)
        self.assertIn("Read 10 public top-level comments", output)
        self.assertNotIn("I used it for a month", output)

    def test_live_explicit_video_selection(self):
        code, _, searches, reads, _ = self.run_live_cli(["Cleaner", "--live", "--video-id", "TESTvideo01"])
        self.assertEqual((code, searches, reads), (0, 1, 1))

    def test_live_cancel_invalid_or_non_member_selection_does_not_fetch(self):
        for choice, expected in (("q", 0), ("99", 2)):
            code, _, searches, reads, _ = self.run_live_cli(["Cleaner", "--live"], selection=choice)
            self.assertEqual((code, searches, reads), (expected, 1, 0))
        code, _, searches, reads, _ = self.run_live_cli(["Cleaner", "--live", "--video-id", "NOTinList01"])
        self.assertEqual((code, searches, reads), (2, 1, 0))

    def test_live_empty_search_stops_without_comments(self):
        code, output, searches, reads, _ = self.run_live_cli(["Cleaner", "--live"], videos=[])
        self.assertEqual((code, searches, reads), (0, 1, 0))
        self.assertIn("No videos returned", output)

    def test_live_limits_remain_five_videos_and_ten_comments(self):
        extra = copy.deepcopy(self.videos[0])
        extra["video_id"] = "TESTvideo06"
        code, output, searches, reads, _ = self.run_live_cli(["Cleaner", "--live", "--search-only"], videos=self.videos + [extra])
        self.assertEqual((code, searches, reads), (0, 1, 0))
        self.assertEqual(output.count("video_id="), 5)
        discovery = {"mode": "live-read-only", "videos": self.videos}
        with patch.object(orchestrator.youtube_comments, "load_youtube_key", return_value="fake-test-key"), patch.object(orchestrator.youtube_comments, "fetch_comments", return_value=[{"unit": "synthetic response"}] * 11):
            preview = orchestrator.preview_live_video(discovery, "TESTvideo01", live=True)
        self.assertEqual(len(preview["comments"]), 10)

    def test_live_comment_error_is_not_retried_or_analyzed(self):
        failure = orchestrator.youtube_comments.YouTubeReadError("http=403; reason=commentsDisabled")
        code, output, searches, reads, _ = self.run_live_cli(["Cleaner", "--live"], fetch_failure=failure)
        self.assertEqual((code, searches, reads), (2, 1, 1))
        self.assertIn("commentsDisabled", output)

    def test_invalid_query_or_mode_options_make_no_requests(self):
        with patch.object(orchestrator.youtube_comments, "load_youtube_key", side_effect=AssertionError("No key read")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(orchestrator.main(["   ", "--live"]), 2)
            for arguments in (["--live"], ["Cleaner", "--search-only"], ["Cleaner", "--video-id", "TESTvideo01"]):
                with self.assertRaises(SystemExit):
                    orchestrator.main(arguments)


if __name__ == "__main__":
    unittest.main()
