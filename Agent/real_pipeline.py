"""Read-only evidence envelope and server-policy-gated real analysis entrypoint."""

from youtube_comments import preview_text


ANALYSIS_BLOCK_REASON = (
    "真实分析需要独立通过用途授权、Qwen 第三方处理、技术/预算和本轮付费确认，不能由输入数据或 API Key 代替。"
    "搜索、标准 JSON 转换、字段校验及原始预览不依赖这些分析条件。"
)


class AnalysisNotAuthorized(RuntimeError):
    """Raised before accessing input data or invoking any downstream service."""


def analysis_status():
    from analysis_control import load_config, analysis_readiness
    controls = analysis_readiness(load_config(), "improvement")
    reasons = [controls[k]["reason"] for k in ("youtube", "provider", "technical") if not controls[k]["ready"]]
    return {"enabled": controls["ready"], "code": "ready" if controls["ready"] else "analysis_not_ready",
            "reason": "仍需本次付费确认。" if controls["ready"] else " ".join(reasons), "controls": controls}


def run_real_analysis(records, *, model="qwen-plus", max_reviews=10, execution=None, progress=None):
    """Reject before reading data unless a server-owned approved execution exists.

    Browser input, a credential or an approved-looking record is not a permit.
    The automatic coordinator supplies the policy/paid-confirmed budget context.
    """
    if execution is None:
        raise AnalysisNotAuthorized(ANALYSIS_BLOCK_REASON)
    from analysis_control import Execution
    if not isinstance(execution, Execution):
        raise AnalysisNotAuthorized(ANALYSIS_BLOCK_REASON)
    limits = execution.check()
    if model != limits["model"] or max_reviews != limits["max_calls"]:
        raise AnalysisNotAuthorized("Execution parameters must match the approved server limits.")
    from automatic_research import analyze_records
    return analyze_records(records, execution, progress=progress)


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
