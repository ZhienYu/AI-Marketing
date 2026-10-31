"""Preview up to ten public YouTube top-level comments; offline Mock by default."""

import argparse
import json
import re
import sys
import unicodedata
from http.client import HTTPException
from pathlib import Path
from urllib import error, parse, request


AGENT_DIR = Path(__file__).resolve().parent
ENDPOINT = "https://www.googleapis.com/youtube/v3/commentThreads"
MAX_COMMENTS = 10
MAX_PREVIEW = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MOCK_VIDEO_ID = "TESTvideo01"
VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")


class YouTubeReadError(Exception):
    pass


def parse_video_id(value):
    value = value.strip()
    if VIDEO_ID_PATTERN.fullmatch(value):
        return value
    if value.startswith(("youtube.com/", "www.youtube.com/", "m.youtube.com/", "youtu.be/")):
        value = "https://" + value
    try:
        url = parse.urlsplit(value)
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port:
            raise ValueError
        if url.hostname == "youtu.be":
            candidate = url.path.strip("/")
        elif url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if url.path.rstrip("/") == "/watch":
                values = parse.parse_qs(url.query).get("v", [])
                if len(values) != 1:
                    raise ValueError
                candidate = values[0]
            else:
                segments = url.path.strip("/").split("/")
                if len(segments) != 2 or segments[0] not in {"shorts", "embed", "live"}:
                    raise ValueError
                candidate = segments[1]
        else:
            raise ValueError
        if not VIDEO_ID_PATTERN.fullmatch(candidate):
            raise ValueError
        return candidate
    except ValueError:
        raise YouTubeReadError("Invalid video: use an 11-character Video ID or a youtube.com/youtu.be video URL.") from None


def load_youtube_key():
    value = None
    try:
        with (AGENT_DIR / ".env").open(encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                name, separator, candidate = line.partition("=")
                if not separator or name.strip() != "YOUTUBE_API_KEY":
                    continue
                if value is not None:
                    raise YouTubeReadError("Duplicate YOUTUBE_API_KEY settings; keep one definition in Agent/.env.")
                candidate = candidate.strip()
                if candidate.startswith(("\"", "'")):
                    if len(candidate) < 2 or candidate[-1] != candidate[0]:
                        raise YouTubeReadError("Invalid quoted YOUTUBE_API_KEY setting in Agent/.env.")
                    candidate = candidate[1:-1]
                else:
                    candidate = candidate.split(" #", 1)[0].strip()
                value = candidate
    except (OSError, UnicodeError):
        raise YouTubeReadError("Cannot read Agent/.env; check that it exists and is UTF-8 encoded.") from None
    if not value or not value.isascii() or any(character.isspace() or ord(character) < 32 for character in value):
        raise YouTubeReadError("Set a non-empty YOUTUBE_API_KEY in Agent/.env. Do not paste it into the terminal or chat.")
    return value


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise YouTubeReadError("Unexpected redirect refused. No retry; the API key was not forwarded.")


def normalize_comments(payload, video_id, *, synthetic=False):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise YouTubeReadError("YouTube response has invalid structure; no results were saved.")
    comments = []
    seen = set()
    try:
        for item in payload["items"][:MAX_COMMENTS]:
            thread = item["snippet"]
            top_level = thread["topLevelComment"]
            snippet = top_level["snippet"]
            comment_id = top_level["id"]
            text = snippet["textDisplay"]
            published_at = snippet["publishedAt"]
            if thread["videoId"] != video_id or not all(
                isinstance(value, str) and value.strip() for value in (comment_id, text, published_at)
            ) or comment_id in seen:
                raise ValueError
            seen.add(comment_id)
            comments.append({
                "comment_id": comment_id,
                "review_text": text,
                "published_at": published_at,
                "video_id": video_id,
                "source_url": "https://www.youtube.com/watch?" + parse.urlencode({"v": video_id, "lc": comment_id}),
                "source_platform": "youtube",
                "brand": "unknown",
                "is_synthetic": synthetic,
            })
    except (KeyError, TypeError, ValueError):
        raise YouTubeReadError("YouTube returned an incomplete or inconsistent top-level comment. No retry.") from None
    return comments


def http_failure_message(failure):
    reason = None
    try:
        payload = json.loads(failure.read(65536))
        reason = payload["error"]["errors"][0]["reason"]
    except (OSError, ValueError, KeyError, IndexError, TypeError, HTTPException):
        pass
    finally:
        failure.close()
    if not isinstance(reason, str):
        reason = None
    messages = {
        "commentsDisabled": "Comments are disabled for this video. Choose another public video.",
        "quotaExceeded": "YouTube daily quota exceeded. Check Google Cloud Quotas and retry after reset.",
        "dailyLimitExceeded": "YouTube daily quota exceeded. Check Google Cloud Quotas and retry after reset.",
        "accessNotConfigured": "Enable YouTube Data API v3 in the project that owns this API key.",
        "ipRefererBlocked": "API key application restrictions rejected this terminal request. Check permitted IPs/application settings.",
        "keyInvalid": "API key rejected. Check YOUTUBE_API_KEY locally and its project restrictions.",
        "videoNotFound": "Video not found or unavailable to this request. Check the URL and visibility.",
    }
    return messages.get(reason, {
        400: "Request rejected. Check the video ID, local API key and API configuration.",
        403: "Access denied. Check API enablement, key restrictions, permissions and quota.",
        404: "Video not found or unavailable. Check the URL and visibility.",
        429: "YouTube rate limit reached. Wait before manually retrying.",
    }.get(failure.code, "YouTube service request failed. Check service availability before manually retrying."))


def fetch_comments(video_id, api_key):
    if not VIDEO_ID_PATTERN.fullmatch(video_id):
        raise YouTubeReadError("Invalid video ID; no request was sent.")
    parameters = {
        "part": "snippet", "videoId": video_id, "maxResults": MAX_COMMENTS,
        "textFormat": "plainText", "order": "time",
        "fields": "items(snippet(videoId,topLevelComment(id,snippet(textDisplay,publishedAt))))",
        "key": api_key,
    }
    api_request = request.Request(ENDPOINT + "?" + parse.urlencode(parameters), headers={"Accept": "application/json"}, method="GET")
    try:
        with request.build_opener(NoRedirect()).open(api_request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise YouTubeReadError("Response exceeded the preview size limit. No retry.")
        payload = json.loads(raw)
    except error.HTTPError as failure:
        raise YouTubeReadError(http_failure_message(failure)) from None
    except (error.URLError, TimeoutError, OSError, HTTPException):
        raise YouTubeReadError("Connection failed or timed out. No automatic retry; check network access to Google APIs.") from None
    except (ValueError, UnicodeError):
        raise YouTubeReadError("YouTube returned invalid JSON. No automatic retry.") from None
    return normalize_comments(payload, video_id)


def preview_text(value):
    return "".join(" " if unicodedata.category(character).startswith("C") else character for character in value)[:240]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", help="YouTube video URL or Video ID")
    parser.add_argument("--live", action="store_true", help="Opt in to one real API request using Agent/.env")
    arguments = parser.parse_args(argv)
    if arguments.live and not arguments.video:
        parser.error("--live requires your chosen video URL or Video ID")
    try:
        video_id = parse_video_id(arguments.video or MOCK_VIDEO_ID)
        if arguments.live:
            comments = fetch_comments(video_id, load_youtube_key())
        else:
            payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_comments_mock.json").read_text(encoding="utf-8"))
            comments = normalize_comments(payload, MOCK_VIDEO_ID, synthetic=True)
        mode = "LIVE — official API response" if arguments.live else "MOCK — SYNTHETIC DATA; no API request"
        print(mode)
        if arguments.video and not arguments.live:
            print("Mock uses the synthetic sample video. Add --live to request your chosen video.")
        print(f"Retrieved {len(comments)} public top-level comment(s); previewing at most {MAX_PREVIEW}. No pagination.")
        for index, comment in enumerate(comments[:MAX_PREVIEW], 1):
            print(f"\n[{index}] comment_id={preview_text(comment['comment_id'])}; brand=unknown")
            print(f"published_at={preview_text(comment['published_at'])}; video_id={comment['video_id']}; source_platform=youtube")
            print(preview_text(comment["review_text"]))
            print(comment["source_url"])
        if not comments:
            print("Request succeeded, but no public top-level comments were returned.")
        print("\nRead-only preview complete. No comments saved, no Qwen call, no brand or sentiment inference.")
        print("Comment links are constructed from returned IDs; deleted/hidden comments may not remain accessible.")
        return 0
    except YouTubeReadError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print("Could not read the local Mock fixture. No raw response or credential details are printed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
