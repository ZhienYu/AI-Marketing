import contextlib
import io
import json
import socket
import ssl
import sys
import tempfile
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib import error, parse


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import orchestrator
import youtube_comments as comments
import youtube_search as search


class YouTubeRetryTests(unittest.TestCase):
    def setUp(self):
        self.key = "fake-retry-unit-key"
        self.comment_payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_comments_mock.json").read_text())
        self.search_payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_search_mock.json").read_text())
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.open = self.stack.enter_context(patch.object(comments.request, "build_opener")).return_value.open
        self.sleep = self.stack.enter_context(patch.object(comments.time, "sleep"))
        self.stderr = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stderr(self.stderr))
        self.stack.enter_context(patch.object(comments, "load_youtube_key", side_effect=AssertionError("Unexpected key file read")))

    def reset(self):
        self.open.reset_mock()
        self.sleep.reset_mock()
        self.stderr.seek(0)
        self.stderr.truncate()

    def response(self, kind, *, read_failure=None, raw=None, close_failure=None):
        payload = self.comment_payload if kind == "comments" else self.search_payload
        context = MagicMock()
        response = MagicMock()
        response.read.side_effect = read_failure
        response.read.return_value = raw if raw is not None else json.dumps(payload).encode()
        context.__enter__.return_value = response
        context.__exit__.side_effect = close_failure
        return context

    def call(self, kind):
        return comments.fetch_comments("TESTvideo01", self.key) if kind == "comments" else search.search_videos("Robotic Pool Cleaner", self.key)

    def assert_safe(self, message=""):
        output = self.stderr.getvalue() + message
        self.assertNotIn(self.key, output)
        self.assertNotIn("https://", output)
        self.assertNotIn("Authorization", output)

    def test_first_attempt_success_never_waits(self):
        for kind in ("comments", "search"):
            self.reset()
            self.open.side_effect = [self.response(kind)]
            self.assertTrue(self.call(kind))
            self.open.assert_called_once()
            self.sleep.assert_not_called()
            self.assertIn("attempt=1/2", self.stderr.getvalue())
            self.assertNotIn("attempt=2/2", self.stderr.getvalue())
            self.assert_safe()

    def test_connection_reset_then_success_uses_one_delay_and_same_page(self):
        for kind in ("comments", "search"):
            self.reset()
            self.open.side_effect = [error.URLError(ConnectionResetError(self.key)), self.response(kind)]
            results = self.call(kind)
            self.assertEqual(self.open.call_count, 2)
            self.sleep.assert_called_once_with(0.5)
            urls = [call.args[0].full_url for call in self.open.call_args_list]
            self.assertEqual(urls[0], urls[1])
            query = parse.parse_qs(parse.urlsplit(urls[0]).query)
            self.assertNotIn("pageToken", query)
            self.assertEqual(query["maxResults"], ["10" if kind == "comments" else "5"])
            self.assertLessEqual(len(results), 10 if kind == "comments" else 5)
            self.assertIn("category=connection_reset", self.stderr.getvalue())
            self.assertIn("Retrying once", self.stderr.getvalue())
            self.assertIn("attempt=2/2", self.stderr.getvalue())
            self.assert_safe()

    def test_two_failures_stop_at_two_and_keep_diagnostics(self):
        for kind in ("comments", "search"):
            self.reset()
            self.open.side_effect = error.URLError(ConnectionResetError(self.key))
            with self.assertRaises(comments.YouTubeReadError) as raised:
                self.call(kind)
            message = str(raised.exception)
            self.assertEqual(self.open.call_count, 2)
            self.sleep.assert_called_once_with(0.5)
            self.assertIn("attempt=2/2", message)
            self.assertIn("Retry limit reached", message)
            self.assertIn("stage=open", message)
            self.assertIn("URLError(ConnectionResetError)", message)
            self.assert_safe(message)

    def test_open_and_read_timeouts_can_recover(self):
        for kind in ("comments", "search"):
            for stage in ("open", "read"):
                self.reset()
                first = TimeoutError(self.key) if stage == "open" else self.response(kind, read_failure=TimeoutError(self.key))
                self.open.side_effect = [first, self.response(kind)]
                self.assertTrue(self.call(kind))
                self.assertEqual(self.open.call_count, 2)
                self.sleep.assert_called_once_with(0.5)
                self.assertIn("stage=" + stage, self.stderr.getvalue())
                self.assertIn("category=" + ("open_timeout" if stage == "open" else "read_timeout"), self.stderr.getvalue())
                self.assert_safe()

    def test_incomplete_body_is_discarded_and_never_merged(self):
        for kind in ("comments", "search"):
            self.reset()
            first = self.response(kind, read_failure=IncompleteRead(self.key.encode(), 100))
            self.open.side_effect = [first, self.response(kind)]
            results = self.call(kind)
            expected = len(self.comment_payload["items"]) if kind == "comments" else len(self.search_payload["items"])
            self.assertEqual(len(results), expected)
            self.assertEqual(self.open.call_count, 2)
            self.assert_safe()

    def test_http_api_errors_never_retry(self):
        for kind in ("comments", "search"):
            for status, reason in ((400, "API_KEY_INVALID"), (401, "keyInvalid"), (403, "forbidden"), (403, "commentsDisabled"), (403, "quotaExceeded"), (404, "videoNotFound"), (429, "rateLimitExceeded"), (503, "backendError")):
                self.reset()
                body = {"error": {"message": self.key, "errors": [{"reason": reason}]}}
                failure = error.HTTPError("https://example.com/?key=" + self.key, status, self.key, {"Authorization": self.key}, io.BytesIO(json.dumps(body).encode()))
                self.open.side_effect = failure
                with self.assertRaises(comments.YouTubeReadError) as raised:
                    self.call(kind)
                self.open.assert_called_once()
                self.sleep.assert_not_called()
                self.assertIn(f"http={status}", str(raised.exception))
                self.assertIn("reason=" + reason, str(raised.exception))
                self.assert_safe(str(raised.exception))

    def test_known_http_failure_with_error_body_timeout_still_never_retries(self):
        body = MagicMock()
        body.read.side_effect = TimeoutError(self.key)
        self.open.side_effect = error.HTTPError("https://example.com/?key=" + self.key, 403, self.key, {}, body)
        with self.assertRaises(comments.YouTubeReadError) as raised:
            self.call("comments")
        self.open.assert_called_once()
        self.sleep.assert_not_called()
        self.assertIn("http=403", str(raised.exception))
        self.assertIn("stage=read_error_body", str(raised.exception))
        self.assert_safe(str(raised.exception))

    def test_temporary_dns_retries_but_permanent_dns_and_ssl_do_not(self):
        for kind in ("comments", "search"):
            self.reset()
            self.open.side_effect = [error.URLError(socket.gaierror(socket.EAI_AGAIN, self.key)), self.response(kind)]
            self.assertTrue(self.call(kind))
            self.assertEqual(self.open.call_count, 2)
            for failure in (error.URLError(socket.gaierror(socket.EAI_NONAME, self.key)), ssl.SSLCertVerificationError(1, self.key), ssl.SSLError(1, self.key), ConnectionRefusedError(self.key), error.URLError(self.key), RuntimeError(self.key)):
                self.reset()
                self.open.side_effect = failure
                with self.assertRaises(comments.YouTubeReadError) as raised:
                    self.call(kind)
                self.open.assert_called_once()
                self.sleep.assert_not_called()
                self.assert_safe(str(raised.exception))

    def test_invalid_json_oversized_or_invalid_schema_never_retries(self):
        for kind in ("comments", "search"):
            for raw in (b"not-json", b"x" * (comments.MAX_RESPONSE_BYTES + 1), b"{}"):
                self.reset()
                self.open.side_effect = [self.response(kind, raw=raw)]
                with self.assertRaises(comments.YouTubeReadError):
                    self.call(kind)
                self.open.assert_called_once()
                self.sleep.assert_not_called()

    def test_close_failure_does_not_resend_successfully_read_body(self):
        self.open.side_effect = [self.response("comments", close_failure=TimeoutError(self.key))]
        with self.assertRaises(comments.YouTubeReadError) as raised:
            self.call("comments")
        self.open.assert_called_once()
        self.sleep.assert_not_called()
        self.assertIn("stage=close", str(raised.exception))
        self.assert_safe(str(raised.exception))

    def test_orchestrator_directly_reuses_bounded_retry_without_analysis_or_persistence(self):
        self.open.side_effect = [self.response("search"), error.URLError(ConnectionResetError(self.key)), self.response("comments")]
        with tempfile.TemporaryDirectory() as directory, patch.object(orchestrator, "AGENT_DIR", Path(directory)), patch.object(comments, "load_youtube_key", return_value=self.key), patch.object(orchestrator.qualify_feedback, "qualify_batch", side_effect=AssertionError("No qualification")), patch.object(orchestrator.classify_reviews, "analyze_batch", side_effect=AssertionError("No Qwen")), patch.object(orchestrator.generate_report, "save_report", side_effect=AssertionError("No report")):
            discovery = orchestrator.discover_live_videos("Cleaner", live=True)
            self.assertEqual(self.open.call_count, 1)
            preview = orchestrator.preview_live_video(discovery, discovery["videos"][0]["video_id"], live=True)
            self.assertEqual(self.open.call_count, 3)
            self.assertEqual(len(preview["comments"]), len(self.comment_payload["items"]))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.sleep.assert_called_once_with(0.5)
        self.assert_safe()


if __name__ == "__main__":
    unittest.main()
