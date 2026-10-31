"""One entry point for a synthetic report pipeline or explicitly gated live previews."""

import argparse
import contextlib
import csv
import io
import json
import sys
from pathlib import Path
from tempfile import mkdtemp

import classify_reviews
import generate_insights
import generate_report
import qualify_feedback
import youtube_comments
import youtube_search
from validate_reviews import REQUIRED_COLUMNS, load_reviews


AGENT_DIR = Path(__file__).resolve().parent


def read_fixture(name):
    return json.loads((AGENT_DIR / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def run_mock_pipeline(query, *, output_root=None):
    query = youtube_search.validate_query(query)
    videos = youtube_search.normalize_videos(read_fixture("youtube_search_mock.json"), synthetic=True)
    if not videos:
        raise ValueError("Mock discovery returned no videos; no report generated.")
    fixture = read_fixture("pipeline_synthetic.json")
    if fixture.get("is_synthetic") is not True or fixture["video_id"] != videos[0]["video_id"]:
        raise ValueError("Mock pipeline requires an explicitly synthetic fixture matching its selected video.")
    comments = youtube_comments.normalize_comments(fixture["comment_threads"], fixture["video_id"], synthetic=True)
    qualification = qualify_feedback.qualify_batch([
        {"review_id": "youtube:" + comment["comment_id"], "review_text": comment["review_text"], "is_synthetic": True}
        for comment in comments
    ])
    by_id = {result["review_id"]: result for result in qualification["results"]}
    rows = [{
        "review_id": "youtube:" + comment["comment_id"], "review_text": comment["review_text"],
        "source_platform": "synthetic", "source_url": "",
        "brand": by_id["youtube:" + comment["comment_id"]]["brand"],
    } for comment in comments]
    root = Path(output_root) if output_root is not None else AGENT_DIR / "outputs" / "test" / "pipeline"
    root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(mkdtemp(prefix="mock-", dir=root))
    csv_path = run_dir / "synthetic_reviews.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    validation, valid_rows = load_reviews(csv_path)
    selected = [row for row in valid_rows if by_id[row["review_id"]]["eligible_as_usage_review"]]
    groups = {
        "feedback_types": {label: [result["review_id"] for result in qualification["results"] if label in result["feedback_types"]] for label in qualify_feedback.FEEDBACK_TYPES},
        "usage_review_candidates": [row["review_id"] for row in selected],
        "general_product_feedback": [result["review_id"] for result in qualification["results"] if result["eligible_for_product_insights"] and not result["eligible_as_usage_review"]],
        "needs_review": [result["review_id"] for result in qualification["results"] if result["qualification_status"] != "qualified"],
    }
    classify_reviews.save_json(run_dir / "discovery.json", {"mode": "mock", "notice": "SYNTHETIC DATA: fixed examples, not real matches for the keyword.", "query": query, "videos": videos, "selected_video_id": fixture["video_id"]})
    classify_reviews.save_json(run_dir / "qualification.json", qualification)
    classify_reviews.save_json(run_dir / "feedback_groups.json", {"mode": "mock", "is_synthetic": True, **groups})
    with contextlib.redirect_stdout(io.StringIO()):
        classified = classify_reviews.analyze_batch(selected, validation, "mock", "offline-fixtures", run_dir / "classifications.json", fixtures=fixture["classifications"])
    insights = generate_insights.generate_insights(classified)
    classify_reviews.save_json(run_dir / "insights.json", insights)
    quality = qualification["summary"]
    quality_note = "\n".join([
        "### Pipeline Feedback Qualification", "",
        f"输入关键词：{generate_report.markdown(query)}。Mock 使用固定合成样例，不是真实搜索或 AI 分析。",
        f"读取 {len(comments)} 条合成评论；使用体验候选 {len(selected)} 条；最终成功分类 {len(classified['results'])} 条。",
        f"购买咨询 {quality['purchase_inquiries']} 条；视频内容反馈 {quality['content_feedback']} 条；无关/不明确互动 {quality['irrelevant_or_unclear']} 条。",
        f"一般产品反馈另存 {len(groups['general_product_feedback'])} 条，不与使用体验合并；反馈类型可重叠，不可相加作为样本总数。",
        f"品牌 unknown 的评论 {sum(result['brand'] == 'unknown' for result in qualification['results'])} 条；没有明确目标、存在歧义或证据不足的评论不进入本报告的使用体验统计。",
        "品牌样本不足时为 Insufficient Data；自述使用不等于验证购买；不能作真实市场品牌结论。",
        "来源：synthetic_reviews.csv、qualification.json、feedback_groups.json、classifications.json、insights.json。原始模拟视频链接不作为真实证据。", "",
    ])
    if classified["results"]:
        content = generate_report.render_report(insights, classified, valid_rows)
        content = content.replace("## 1. Executive Summary", quality_note + "\n## 1. Executive Summary", 1)
    else:
        content = "# DEMO — SYNTHETIC DATA\n\n" + quality_note + "\nInsufficient Evidence：没有可用的成功使用体验分类，不生成品牌或商业结论。\n"
    report_path = run_dir / "market_research_report.md"
    generate_report.save_report(report_path, content)
    summary = {
        "mode": "mock", "notice": "DEMO — SYNTHETIC DATA; no network calls or real AI inference.",
        "query": query, "discovered_videos": len(videos), "read_comments": len(comments),
        "qualification_summary": quality, "analyzed_usage_reviews": len(classified["results"]),
        "classification_failures": len(classified["failures"]), "feedback_groups": groups,
        "report_path": str(report_path), "run_directory": str(run_dir),
    }
    classify_reviews.save_json(run_dir / "pipeline_summary.json", summary)
    return summary


def discover_live_videos(query, *, live=False):
    if live is not True:
        raise ValueError("Live discovery requires explicit live=True.")
    query = youtube_search.validate_query(query)
    videos = youtube_search.search_videos(query, youtube_comments.load_youtube_key())[:youtube_search.MAX_VIDEOS]
    return {"mode": "live-read-only", "query": query, "videos": videos}


def preview_live_video(discovery, video_id, *, live=False):
    if live is not True or discovery.get("mode") != "live-read-only":
        raise ValueError("Live preview requires explicit permission and a live discovery result.")
    video_id = youtube_comments.parse_video_id(video_id)
    if video_id not in {video["video_id"] for video in discovery["videos"][:youtube_search.MAX_VIDEOS]}:
        raise ValueError("Choose a video from this search result; no comment request was sent.")
    comments = youtube_comments.fetch_comments(video_id, youtube_comments.load_youtube_key())[:youtube_comments.MAX_COMMENTS]
    return {"mode": "live-read-only", "video_id": video_id, "comments": comments}


def display_videos(discovery):
    print("LIVE READ-ONLY — official YouTube search; no qualification or analysis")
    for index, video in enumerate(discovery["videos"][:youtube_search.MAX_VIDEOS], 1):
        print(f"[{index}] {youtube_comments.preview_text(video['title'])}")
        print(f"channel={youtube_comments.preview_text(video['channel_title'])}; published_at={youtube_comments.preview_text(video['published_at'])}")
        print(f"video_id={video['video_id']}  {video['video_url']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?")
    parser.add_argument("--live", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--search-only", action="store_true")
    selection.add_argument("--video-id", help="Explicitly choose an ID that must appear in this search")
    arguments = parser.parse_args(argv)
    if arguments.live and arguments.query is None:
        parser.error("--live requires a product keyword")
    if not arguments.live and (arguments.search_only or arguments.video_id):
        parser.error("--search-only and --video-id are live read-only options")
    try:
        query = youtube_search.validate_query(arguments.query if arguments.query is not None else youtube_search.DEFAULT_QUERY)
        if not arguments.live:
            summary = run_mock_pipeline(query)
            print(summary["notice"])
            print(f"Mock: {summary['discovered_videos']} videos, {summary['read_comments']} comments, {summary['analyzed_usage_reviews']} analyzed usage candidates.")
            print("Consultations, general discussion, content feedback and unclear interactions remain in separate groups. Insufficient Data for market brand conclusions.")
            print(f"Report: {summary['report_path']}")
            return 1 if summary["classification_failures"] else 0
        discovery = discover_live_videos(query, live=True)
        display_videos(discovery)
        if not discovery["videos"]:
            print("No videos returned; no comment request was sent.")
        if arguments.search_only or not discovery["videos"]:
            print("Search-only preview complete. No comments fetched or files saved.")
            return 0
        video_id = arguments.video_id
        if video_id is None:
            choice = input("Choose one video number (1-5), or q to cancel: ").strip()
            if choice.casefold() == "q":
                print("Cancelled; no comment request sent.")
                return 0
            if choice not in {str(index) for index in range(1, len(discovery["videos"]) + 1)}:
                raise ValueError("Invalid selection; no comment request sent.")
            video_id = discovery["videos"][int(choice) - 1]["video_id"]
        preview = preview_live_video(discovery, video_id, live=True)
        print(f"Read {len(preview['comments'])} public top-level comments; showing at most {youtube_comments.MAX_PREVIEW}.")
        for comment in preview["comments"][:youtube_comments.MAX_PREVIEW]:
            print(f"comment_id={youtube_comments.preview_text(comment['comment_id'])}; brand=unknown")
            print(youtube_comments.preview_text(comment["review_text"]))
            print(comment["source_url"])
        print("Live preview only: no files saved, no qualification, no Qwen, no insights or report.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Stopped. No automatic retry; live comments are not persisted.")
        return 130
    except (youtube_comments.YouTubeReadError, classify_reviews.ClassificationError) as failure:
        print(str(failure), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        print("Pipeline input, selection or local file operation failed. No automatic retry or raw error details.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
