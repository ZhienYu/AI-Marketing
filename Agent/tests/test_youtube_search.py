import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib import error, parse


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
import youtube_comments as comments
import youtube_search as search


class YouTubeSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_search_mock.json").read_text())
        self.key = "fake-youtube-search-key"
        network = patch.object(search.request, "build_opener")
        self.opener = network.start()
        self.addCleanup(network.stop)
        sleeper = patch.object(comments.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)
        stderr = patch("sys.stderr", new=io.StringIO())
        stderr.start()
        self.addCleanup(stderr.stop)

    def respond(self, payload):
        self.opener.return_value.open.return_value.__enter__.side_effect = lambda: io.BytesIO(json.dumps(payload).encode())

    def test_default_mock_is_offline_and_does_not_read_key(self):
        output = io.StringIO()
        with patch.object(search, "load_youtube_key", side_effect=AssertionError("Unexpected key read")), patch.object(comments, "fetch_comments", side_effect=AssertionError("Unexpected comment request")), contextlib.redirect_stdout(output):
            self.assertEqual(search.main([]), 0)
        self.opener.assert_not_called()
        self.assertIn("MOCK — SYNTHETIC DATA", output.getvalue())
        self.assertEqual(output.getvalue().count("video_id="), 5)
        self.assertNotIn('--live "TESTvideo', output.getvalue())

    def test_single_request_parameters(self):
        self.respond(self.payload)
        videos = search.search_videos("  Robotic Pool Cleaner  ", self.key)
        call = self.opener.return_value.open.call_args
        req = call.args[0]
        url = parse.urlsplit(req.full_url)
        query = parse.parse_qs(url.query)
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.hostname, "www.googleapis.com")
        self.assertEqual(url.path, "/youtube/v3/search")
        self.assertEqual(req.method, "GET")
        self.assertEqual(query["q"], ["Robotic Pool Cleaner"])
        self.assertEqual(query["type"], ["video"])
        self.assertEqual(query["order"], ["relevance"])
        self.assertEqual(query["maxResults"], ["5"])
        self.assertEqual(query["part"], ["snippet"])
        self.assertEqual(query["key"], [self.key])
        self.assertNotIn("pageToken", query)
        self.assertEqual(call.kwargs["timeout"], 30)
        self.opener.return_value.open.assert_called_once()
        self.assertEqual(len(videos), 5)
        self.assertFalse(videos[0]["is_synthetic"])

    def test_result_fields_and_original_order_preserved(self):
        self.payload["items"].reverse()
        videos = search.normalize_videos(self.payload, synthetic=True)
        self.assertEqual([row["video_id"] for row in videos], [f"TESTvideo0{index}" for index in range(5, 0, -1)])
        row = videos[0]
        self.assertEqual(row["title"], self.payload["items"][0]["snippet"]["title"])
        self.assertEqual(row["channel_title"], "Synthetic Hardware Channel E")
        self.assertEqual(row["published_at"], "2026-01-05T00:00:00Z")
        self.assertEqual(row["video_url"], "https://www.youtube.com/watch?v=TESTvideo05")
        self.assertTrue(row["is_synthetic"])
        self.assertNotIn("brand", row)

    def test_max_five_even_if_server_returns_more(self):
        extra = copy.deepcopy(self.payload["items"][0])
        extra["id"]["videoId"] = "TESTvideo06"
        self.payload["items"].append(extra)
        self.assertEqual(len(search.normalize_videos(self.payload)), 5)

    def test_invalid_queries_rejected_before_key_read(self):
        with patch.object(search, "load_youtube_key", side_effect=AssertionError("Unexpected key read")), contextlib.redirect_stderr(io.StringIO()):
            for query in ("", "   ", "x" * 201, "keyword\x1b"):
                with self.subTest(query=query):
                    self.assertEqual(search.main([query, "--live"]), 2)
            with self.assertRaises(SystemExit):
                search.main(["--live"])
        self.opener.assert_not_called()

    def test_unicode_keyword_and_operators_are_url_encoded(self):
        self.respond(self.payload)
        keyword = "泳池机器人 & cleaner|robot -toy"
        search.search_videos(keyword, self.key)
        query = parse.parse_qs(parse.urlsplit(self.opener.return_value.open.call_args.args[0].full_url).query)
        self.assertEqual(query["q"], [keyword])

    def test_live_cli_displays_five_without_fetching_comments_or_writing_files(self):
        self.respond(self.payload)
        output = io.StringIO()
        with patch.object(search, "AGENT_DIR", self.temp), patch.object(search, "load_youtube_key", return_value=self.key), patch.object(comments, "fetch_comments", side_effect=AssertionError("Unexpected comments")), contextlib.redirect_stdout(output):
            self.assertEqual(search.main(["Robotic Pool Cleaner", "--live"]), 0)
        self.assertIn("LIVE — official YouTube search response", output.getvalue())
        self.assertEqual(output.getvalue().count("video_id="), 5)
        self.assertIn("CHOSEN_VIDEO_ID", output.getvalue())
        self.assertNotIn(self.key, output.getvalue())
        self.assertEqual(list(self.temp.iterdir()), [])
        self.opener.return_value.open.assert_called_once()

    def test_manual_second_command_reuses_comment_module(self):
        comment_payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_comments_mock.json").read_text())

        def response(payload):
            handle = Mock()
            handle.__enter__ = Mock(return_value=io.BytesIO(json.dumps(payload).encode()))
            handle.__exit__ = Mock(return_value=False)
            return handle

        self.opener.return_value.open.side_effect = [response(self.payload), response(comment_payload)]
        videos = search.search_videos("Robotic Pool Cleaner", self.key)
        self.assertEqual(self.opener.return_value.open.call_count, 1)
        selected_id = videos[0]["video_id"]
        with patch.object(comments, "load_youtube_key", return_value=self.key), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(comments.main(["--live", selected_id]), 0)
        self.assertEqual(self.opener.return_value.open.call_count, 2)
        second_url = self.opener.return_value.open.call_args.args[0].full_url
        self.assertEqual(parse.parse_qs(parse.urlsplit(second_url).query)["videoId"], [selected_id])
        self.assertEqual(parse.urlsplit(second_url).path, "/youtube/v3/commentThreads")

    def test_empty_results_are_success_not_fabricated(self):
        self.respond({"items": []})
        output = io.StringIO()
        with patch.object(search, "load_youtube_key", return_value=self.key), contextlib.redirect_stdout(output):
            self.assertEqual(search.main(["Rare product", "--live"]), 0)
        self.assertIn("no videos were returned", output.getvalue())
        self.assertNotIn("CHOSEN_VIDEO_ID", output.getvalue())

    def test_missing_duplicate_or_non_video_result_is_rejected(self):
        duplicate = copy.deepcopy(self.payload)
        duplicate["items"][1] = copy.deepcopy(duplicate["items"][0])
        channel = copy.deepcopy(self.payload)
        channel["items"][0]["id"] = {"kind": "youtube#channel", "videoId": "TESTvideo01"}
        invalid_id = copy.deepcopy(self.payload)
        invalid_id["items"][0]["id"]["videoId"] = "invalid"
        for payload in ({}, {"items": None}, {"items": [{}]}, duplicate, channel, invalid_id):
            with self.subTest(payload=payload), self.assertRaises(search.YouTubeReadError):
                search.normalize_videos(payload)

    def test_http_errors_hide_key_and_do_not_retry(self):
        for status, reason in ((400, "keyInvalid"), (403, "quotaExceeded"), (403, "accessNotConfigured"), (429, "rateLimitExceeded"), (503, "backendError")):
            body = {"error": {"message": self.key, "errors": [{"reason": reason}]}}
            self.opener.return_value.open.reset_mock()
            self.opener.return_value.open.side_effect = error.HTTPError("https://example.com?key=" + self.key, status, self.key, {}, io.BytesIO(json.dumps(body).encode()))
            stderr = io.StringIO()
            with patch.object(search, "load_youtube_key", return_value=self.key), contextlib.redirect_stderr(stderr):
                self.assertEqual(search.main(["Cleaner", "--live"]), 2)
            self.assertNotIn(self.key, stderr.getvalue())
            self.opener.return_value.open.assert_called_once()

    def test_network_failure_and_timeout_sanitized(self):
        for failure in (error.URLError(self.key), TimeoutError(self.key)):
            self.opener.return_value.open.reset_mock()
            self.opener.return_value.open.side_effect = failure
            with self.assertRaises(search.YouTubeReadError) as raised:
                search.search_videos("Cleaner", self.key)
            self.assertNotIn(self.key, str(raised.exception))
            self.assertEqual(self.opener.return_value.open.call_count, 2 if isinstance(failure, TimeoutError) else 1)

    def test_invalid_json_and_oversized_response(self):
        for raw in (b"not-json", b"x" * (search.MAX_RESPONSE_BYTES + 1)):
            self.opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(raw)
            with self.assertRaises(search.YouTubeReadError):
                search.search_videos("Cleaner", self.key)


if __name__ == "__main__":
    unittest.main()
