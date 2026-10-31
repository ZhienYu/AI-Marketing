"""Discover up to five YouTube videos; offline Mock unless --live is explicit."""

import argparse
import json
import sys
import unicodedata
from http.client import HTTPException
from pathlib import Path
from urllib import error, parse, request

from youtube_comments import (
    MAX_RESPONSE_BYTES, VIDEO_ID_PATTERN, NoRedirect, YouTubeReadError,
    http_failure_message, load_youtube_key, preview_text,
)


AGENT_DIR = Path(__file__).resolve().parent
SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
MAX_VIDEOS = 5
DEFAULT_QUERY = "Robotic Pool Cleaner"


def validate_query(query):
    if not isinstance(query, str):
        raise YouTubeReadError("Search keyword must be text.")
    query = query.strip()
    if not query or len(query) > 200 or any(unicodedata.category(character).startswith("C") for character in query):
        raise YouTubeReadError("Enter a non-empty keyword of at most 200 characters, without control characters.")
    return query


def normalize_videos(payload, *, synthetic=False):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise YouTubeReadError("YouTube search response has invalid structure. No automatic retry.")
    videos = []
    seen = set()
    try:
        for item in payload["items"][:MAX_VIDEOS]:
            identity = item["id"]
            snippet = item["snippet"]
            video_id = identity["videoId"]
            title = snippet["title"]
            channel_title = snippet["channelTitle"]
            published_at = snippet["publishedAt"]
            if identity["kind"] != "youtube#video" or not isinstance(video_id, str) or not VIDEO_ID_PATTERN.fullmatch(video_id):
                raise ValueError
            if video_id in seen or not all(isinstance(value, str) and value.strip() for value in (title, channel_title, published_at)):
                raise ValueError
            seen.add(video_id)
            videos.append({
                "title": title, "channel_title": channel_title, "published_at": published_at,
                "video_id": video_id,
                "video_url": "https://www.youtube.com/watch?" + parse.urlencode({"v": video_id}),
                "source_platform": "youtube", "is_synthetic": synthetic,
            })
    except (KeyError, TypeError, ValueError):
        raise YouTubeReadError("YouTube returned an incomplete, duplicate or non-video search result. No automatic retry.") from None
    return videos


def search_videos(query, api_key):
    query = validate_query(query)
    parameters = {
        "part": "snippet", "type": "video", "q": query, "order": "relevance",
        "maxResults": MAX_VIDEOS,
        "fields": "items(id(kind,videoId),snippet(title,channelTitle,publishedAt))",
        "key": api_key,
    }
    api_request = request.Request(SEARCH_ENDPOINT + "?" + parse.urlencode(parameters), headers={"Accept": "application/json"}, method="GET")
    try:
        with request.build_opener(NoRedirect()).open(api_request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise YouTubeReadError("Search response exceeded the size limit. No automatic retry.")
        payload = json.loads(raw)
    except error.HTTPError as failure:
        if failure.code == 400:
            failure.close()
            raise YouTubeReadError("Search request rejected (400). Check the keyword, local API key and project configuration.") from None
        raise YouTubeReadError("Search failed: " + http_failure_message(failure)) from None
    except (error.URLError, TimeoutError, OSError, HTTPException):
        raise YouTubeReadError("Search connection failed or timed out. No automatic retry; check access to Google APIs.") from None
    except (ValueError, UnicodeError):
        raise YouTubeReadError("YouTube search returned invalid JSON. No automatic retry.") from None
    return normalize_videos(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="Product keyword, enclosed in quotes")
    parser.add_argument("--live", action="store_true", help="Opt in to one official search request using Agent/.env")
    arguments = parser.parse_args(argv)
    if arguments.live and arguments.query is None:
        parser.error("--live requires your chosen product keyword")
    try:
        query = validate_query(arguments.query if arguments.query is not None else DEFAULT_QUERY)
        if arguments.live:
            videos = search_videos(query, load_youtube_key())
            print("LIVE — official YouTube search response")
        else:
            payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "youtube_search_mock.json").read_text(encoding="utf-8"))
            videos = normalize_videos(payload, synthetic=True)
            print("MOCK — SYNTHETIC DATA; no API request")
            print("Fixed synthetic examples only; these are not actual search results for your keyword.")
        print(f"Keyword: {preview_text(query)}")
        print(f"Returned {len(videos)} video(s), maximum {MAX_VIDEOS}; relevance order preserved. No pagination.")
        for index, video in enumerate(videos, 1):
            print(f"\n[{index}] {preview_text(video['title'])}")
            print(f"channel={preview_text(video['channel_title'])}; published_at={preview_text(video['published_at'])}")
            print(f"video_id={video['video_id']}")
            print(video["video_url"])
        if not videos:
            print("Search succeeded, but no videos were returned. Try a different keyword manually.")
        elif arguments.live:
            print('\nChoose one video manually, then run: python3 -B Agent/youtube_comments.py --live "CHOSEN_VIDEO_ID"')
            print("Replace CHOSEN_VIDEO_ID with an ID above. This is a separate comment request; it is not run automatically.")
        else:
            print("\nFor a safe offline comment preview, run: python3 -B Agent/youtube_comments.py")
            print("Synthetic video IDs are format examples, not real video recommendations.")
        print("No results or comments saved. No comments fetched, no Qwen call, no brand or sentiment inference.")
        return 0
    except YouTubeReadError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print("Could not read the local search fixture. No raw response or credential details are printed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
