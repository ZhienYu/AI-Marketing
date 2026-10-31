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
import youtube_comments as youtube


class YouTubeCommentsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.temp = Path(self.directory.name)
        self.payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_comments_mock.json").read_text())
        self.key = "fake-youtube-unit-test-key"
        network = patch.object(youtube.request, "build_opener")
        self.opener_factory = network.start()
        self.addCleanup(network.stop)

    def response(self, payload):
        self.opener_factory.return_value.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())

    def test_supported_video_url_formats(self):
        for value in ("TESTvideo01", "https://www.youtube.com/watch?v=TESTvideo01&t=10",
                      "https://youtu.be/TESTvideo01?si=example", "https://youtube.com/shorts/TESTvideo01",
                      "youtube.com/watch?v=TESTvideo01", "https://m.youtube.com/watch?v=TESTvideo01",
                      "https://www.youtube.com/embed/TESTvideo01", "https://www.youtube.com/live/TESTvideo01"):
            with self.subTest(value=value):
                self.assertEqual(youtube.parse_video_id(value), "TESTvideo01")

    def test_invalid_video_rejected(self):
        for value in ("", "short", "https://youtube.com.evil.example/watch?v=TESTvideo01",
                      "https://example.com/watch?v=TESTvideo01", "https://youtube.com/playlist?list=TESTvideo01",
                      "https://youtube.com/watch?v=TESTvideo01&v=OTHERvideo1",
                      "https://evil@youtube.com/watch?v=TESTvideo01", "file:///TESTvideo01",
                      "https://youtube.com:443/watch?v=TESTvideo01"):
            with self.subTest(value=value), self.assertRaises(youtube.YouTubeReadError):
                youtube.parse_video_id(value)

    def test_fields_use_comment_id_not_thread_id_and_unknown_brand(self):
        comments = youtube.normalize_comments(self.payload, youtube.MOCK_VIDEO_ID, synthetic=True)
        row = comments[0]
        self.assertEqual(row["comment_id"], "synthetic-comment-1")
        self.assertEqual(row["brand"], "unknown")
        self.assertEqual(row["source_platform"], "youtube")
        self.assertTrue(row["is_synthetic"])
        self.assertEqual(parse.parse_qs(parse.urlsplit(row["source_url"]).query)["lc"], [row["comment_id"]])
        self.assertEqual(row["published_at"], "2026-01-01T00:00:00Z")
        self.assertIn("SYNTHETIC TEST", row["review_text"])

    def test_default_mock_reads_no_key_and_makes_no_network_request(self):
        output = io.StringIO()
        with patch.object(youtube, "load_youtube_key", side_effect=AssertionError("Must not read real key")), contextlib.redirect_stdout(output):
            self.assertEqual(youtube.main([]), 0)
        self.opener_factory.assert_not_called()
        self.assertIn("MOCK — SYNTHETIC DATA", output.getvalue())
        self.assertEqual(output.getvalue().count("comment_id="), 3)
        self.assertNotIn("synthetic-comment-4", output.getvalue())

    def test_request_is_one_official_get_with_ten_plaintext_top_level_comments(self):
        self.response(self.payload)
        comments = youtube.fetch_comments(youtube.MOCK_VIDEO_ID, self.key)
        call = self.opener_factory.return_value.open.call_args
        req = call.args[0]
        query = parse.parse_qs(parse.urlsplit(req.full_url).query)
        self.assertEqual(req.method, "GET")
        self.assertEqual(parse.urlsplit(req.full_url).hostname, "www.googleapis.com")
        self.assertEqual(query["key"], [self.key])
        self.assertEqual(query["maxResults"], ["10"])
        self.assertEqual(query["textFormat"], ["plainText"])
        self.assertEqual(query["part"], ["snippet"])
        self.assertNotIn("pageToken", query)
        self.assertNotIn("replies", query["fields"][0])
        self.assertEqual(call.kwargs["timeout"], 30)
        self.opener_factory.return_value.open.assert_called_once()
        self.assertFalse(comments[0]["is_synthetic"])

    def test_hard_cap_even_when_mock_service_returns_more(self):
        self.payload["items"] = []
        for index in range(12):
            row = {"snippet": {"videoId": youtube.MOCK_VIDEO_ID, "topLevelComment": {"id": f"comment-{index}", "snippet": {"textDisplay": "Unit test", "publishedAt": "2026-01-01T00:00:00Z"}}}}
            self.payload["items"].append(row)
        self.assertEqual(len(youtube.normalize_comments(self.payload, youtube.MOCK_VIDEO_ID)), 10)

    def test_live_main_previews_three_and_writes_no_files(self):
        self.response(self.payload)
        output = io.StringIO()
        with patch.object(youtube, "AGENT_DIR", self.temp), patch.object(youtube, "load_youtube_key", return_value=self.key), contextlib.redirect_stdout(output):
            self.assertEqual(youtube.main([youtube.MOCK_VIDEO_ID, "--live"]), 0)
        self.assertIn("LIVE — official API response", output.getvalue())
        self.assertEqual(output.getvalue().count("comment_id="), 3)
        self.assertNotIn(self.key, output.getvalue())
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_live_requires_video_before_loading_key(self):
        with patch.object(youtube, "load_youtube_key", side_effect=AssertionError("Must not read key")), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                youtube.main(["--live"])
            self.assertEqual(youtube.main(["invalid", "--live"]), 2)
        self.opener_factory.assert_not_called()

    def test_key_loader_uses_temporary_fake_env_and_only_youtube_setting(self):
        (self.temp / ".env").write_text('OTHER_SETTING=not-used\nexport YOUTUBE_API_KEY="fake-file-key"\n', encoding="utf-8")
        with patch.object(youtube, "AGENT_DIR", self.temp):
            self.assertEqual(youtube.load_youtube_key(), "fake-file-key")
        self.opener_factory.assert_not_called()

    def test_missing_bad_and_duplicate_key_settings(self):
        with patch.object(youtube, "AGENT_DIR", self.temp):
            with self.assertRaises(youtube.YouTubeReadError):
                youtube.load_youtube_key()
            for content in ("OTHER_KEY=fake\n", "YOUTUBE_API_KEY=\n", 'YOUTUBE_API_KEY="bad\n',
                            "YOUTUBE_API_KEY=bad key\n", "YOUTUBE_API_KEY=one\nYOUTUBE_API_KEY=two\n"):
                (self.temp / ".env").write_text(content)
                with self.subTest(content=content), self.assertRaises(youtube.YouTubeReadError):
                    youtube.load_youtube_key()

    def test_known_api_errors_are_sanitized_and_not_retried(self):
        for reason, expected in (("commentsDisabled", "disabled"), ("quotaExceeded", "quota"),
                                 ("accessNotConfigured", "Enable"), ("ipRefererBlocked", "restrictions"),
                                 ("keyInvalid", "key rejected"), ("videoNotFound", "Video not found")):
            body = {"error": {"message": self.key, "errors": [{"reason": reason}]}}
            self.opener_factory.return_value.open.reset_mock()
            self.opener_factory.return_value.open.side_effect = error.HTTPError("https://example.com?key=" + self.key, 403, self.key, {}, io.BytesIO(json.dumps(body).encode()))
            with self.subTest(reason=reason), self.assertRaises(youtube.YouTubeReadError) as caught:
                youtube.fetch_comments(youtube.MOCK_VIDEO_ID, self.key)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn(self.key, str(caught.exception))
            self.opener_factory.return_value.open.assert_called_once()

    def test_timeout_and_connection_errors_hide_details(self):
        for failure in (TimeoutError(self.key), error.URLError(self.key)):
            self.opener_factory.return_value.open.reset_mock()
            self.opener_factory.return_value.open.side_effect = failure
            with self.assertRaises(youtube.YouTubeReadError) as caught:
                youtube.fetch_comments(youtube.MOCK_VIDEO_ID, self.key)
            self.assertNotIn(self.key, str(caught.exception))
            self.opener_factory.return_value.open.assert_called_once()

    def test_empty_comments_success(self):
        self.response({"items": []})
        output = io.StringIO()
        with patch.object(youtube, "load_youtube_key", return_value=self.key), contextlib.redirect_stdout(output):
            self.assertEqual(youtube.main([youtube.MOCK_VIDEO_ID, "--live"]), 0)
        self.assertIn("no public top-level comments", output.getvalue())

    def test_bad_response_and_duplicate_comment_rejected(self):
        bad = copy.deepcopy(self.payload)
        bad["items"].append(copy.deepcopy(bad["items"][0]))
        wrong_video = copy.deepcopy(self.payload)
        wrong_video["items"][0]["snippet"]["videoId"] = "OTHERvideo1"
        for payload in ({}, {"items": [{}]}, bad, wrong_video):
            with self.subTest(payload=payload), self.assertRaises(youtube.YouTubeReadError):
                youtube.normalize_comments(payload, youtube.MOCK_VIDEO_ID)

    def test_invalid_json_and_oversized_response(self):
        for raw in (b"not-json", b"a" * (youtube.MAX_RESPONSE_BYTES + 1)):
            self.opener_factory.return_value.open.return_value.__enter__.return_value = io.BytesIO(raw)
            with self.assertRaises(youtube.YouTubeReadError):
                youtube.fetch_comments(youtube.MOCK_VIDEO_ID, self.key)

    def test_redirect_refused(self):
        with self.assertRaises(youtube.YouTubeReadError):
            youtube.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_terminal_preview_strips_control_characters_and_truncates(self):
        preview = youtube.preview_text("a\x1b\r\n\u202e" + "b" * 300)
        self.assertEqual(len(preview), 240)
        self.assertNotIn("\x1b", preview)
        self.assertNotIn("\u202e", preview)


if __name__ == "__main__":
    unittest.main()
