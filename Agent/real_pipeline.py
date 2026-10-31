"""Read-only evidence envelope and a closed interface for future approved analysis.

No NLP, credential loading, model calls, persistence, or approval switch lives here.
"""

from youtube_comments import preview_text


ANALYSIS_BLOCK_REASON = (
    "真实评论分析尚未启用：未取得覆盖跨视频产品研究、评论 NLP、跨品牌比较及阿里云百炼第三方处理的适用许可。"
    "目前仅可搜索、选片和预览；不运行反馈筛选、Qwen、派生统计或报告。"
)


class AnalysisNotAuthorized(RuntimeError):
    """Raised before accessing input data or invoking any downstream service."""


def analysis_status():
    return {"enabled": False, "code": "youtube_analysis_not_authorized", "reason": ANALYSIS_BLOCK_REASON}


def run_real_analysis(records, *, model="qwen-plus", max_reviews=10):
    """Future coordination interface; deliberately unavailable in this release.

    Even direct calls fail before inspecting records. An API key, browser
    checkbox, environment flag, or an approved-looking input cannot enable it.
    See docs/REAL_DATA_PIPELINE.md for the reviewed implementation plan.
    """
    raise AnalysisNotAuthorized(ANALYSIS_BLOCK_REASON)


def build_read_only_preview(preview):
    """Copy API evidence without interpreting text; retain at most three previews.

    Not-assessed placeholders are not qualification results. This truncated
    display envelope is NOT an input to future AI analysis.
    """
    if preview.get("mode") != "live-read-only" or not preview.get("collected_at"):
        raise ValueError("A timestamped live read-only response is required.")
    comments = []
    for comment in preview["comments"][:3]:
        comments.append({
            "review_id": "youtube:" + comment["comment_id"],
            "comment_id": comment["comment_id"], "video_id": preview["video_id"],
            "review_text": preview_text(comment["review_text"]), "text_is_preview": True,
            "published_at": comment["published_at"], "collected_at": preview["collected_at"],
            "source_platform": "youtube", "source_url": comment["source_url"],
            "is_synthetic": comment.get("is_synthetic", False), "brand": "unknown",
            "brand_attribution": {"status": "unverified", "method": "none", "evidence": []},
            "evidence_quality": {"status": "not_assessed", "usage_evidence": None, "verified_purchase": False},
            "feedback_type": None, "analysis_status": "not_analyzed",
        })
    return {
        "mode": "live-read-only", "video_id": preview["video_id"],
        "collected_at": preview["collected_at"], "count": len(preview["comments"]),
        "comments": comments,
    }
