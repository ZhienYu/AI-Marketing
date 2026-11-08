"""In-memory YouTube → validated Qwen evidence → specialist report workflow."""
import copy
import hashlib
import json
from decimal import Decimal
import uuid
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlparse, parse_qs, urlencode

import classify_reviews as classifier
import orchestrator
from analysis_control import BATCH_BUDGET_MODE, ControlError, Execution, KEYWORD_BUDGET_MODE, PHASE_K, PHASE_K_RUN_SECONDS, analysis_readiness, load_policy, message_token_estimate, with_batch_profile
from evidence_analysis import PROMPT as LIVE_PROMPT, VERSION as EVIDENCE_VERSION, evidence_message
from real_analysis_schema import validate as validate_live_output

PROMPT = LIVE_PROMPT
validate_output = validate_live_output


def normalize_batch(batch):
    if batch.get("mode") != "live-read-only":
        raise ValueError("Expected official read-only collection.")
    reviews, seen = [], set()
    for row in batch["videos"][:5]:
        video = row["video"]
        for comment in row["comments"][:10]:
            cid = comment["comment_id"]
            if cid in seen:
                continue
            if comment.get("is_synthetic") is True or comment.get("text_is_preview"):
                raise ValueError("Real analysis rejects synthetic or shortened preview data.")
            url = urlparse(comment["source_url"])
            if url.scheme != "https" or url.hostname != "www.youtube.com" or comment.get("video_id") != video["video_id"]:
                raise ValueError("Inconsistent source metadata.")
            if not isinstance(comment["review_text"], str) or not comment["review_text"].strip():
                continue
            seen.add(cid)
            reviews.append({"review_id": "youtube:" + cid, "comment_id": cid,
                "video_id": video["video_id"], "video_title": video["title"], "video_url": video["video_url"],
                "video_published_at": video["published_at"],
                "review_text": comment["review_text"], "source_url": comment["source_url"], "source_platform": "youtube",
                "published_at": comment["published_at"], "collected_at": comment.get("collected_at") or row.get("collected_at") or batch["collected_at"],
                "brand": "unknown", "evidence_quality": "not_assessed", "is_synthetic": False})
    return reviews


def validate_sources(reviews):
    for row in reviews:
        cid, vid = row["comment_id"], row["video_id"]
        parsed = urlparse(row["source_url"])
        params = parse_qs(parsed.query)
        if (row["review_id"] != "youtube:" + cid or not orchestrator.youtube_comments.VIDEO_ID_PATTERN.fullmatch(vid)
            or parsed.scheme != "https" or parsed.netloc != "www.youtube.com" or parsed.path != "/watch"
            or params != {"v": [vid], "lc": [cid]}):
            raise ValueError("Review identity and original source link disagree.")
        for field in ("published_at", "collected_at"):
            if datetime.fromisoformat(row[field].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("Source timestamps require timezone information.")
        if not isinstance(row["review_text"], str) or not row["review_text"].strip():
            raise ValueError("Empty source text.")
        # Canonical links only; arbitrary imported query parameters cannot appear in reports.
        row["source_url"] = "https://www.youtube.com/watch?" + urlencode({"v": vid, "lc": cid})
        row["video_url"] = "https://www.youtube.com/watch?" + urlencode({"v": vid})


def inspect_collection(batch):
    """Metadata validation only: no NLP, model, key access or persistence."""
    records, issues, seen_comments, seen_videos = [], [], set(), set()
    received = 0
    for row in batch.get("videos", []):
        video = row.get("video", {})
        vid = video.get("video_id", "")
        if vid in seen_videos:
            issues.append({"video_id": vid, "field": "video_id", "reason": "duplicate_video"})
        seen_videos.add(vid)
        for comment in row.get("comments", []):
            received += 1
            cid = comment.get("comment_id", "")
            errors = []
            if not cid or cid in seen_comments:
                errors.append(("comment_id", "missing_or_duplicate"))
            seen_comments.add(cid)
            for field in ("review_text", "video_id", "published_at", "source_url", "source_platform"):
                if not isinstance(comment.get(field), str) or not comment[field].strip():
                    errors.append((field, "missing"))
            if comment.get("video_id") != vid:
                errors.append(("video_id", "parent_mismatch"))
            if comment.get("source_platform") != "youtube":
                errors.append(("source_platform", "unexpected"))
            for field in ("title", "video_url", "published_at"):
                if not video.get(field):
                    errors.append(("video." + field, "missing"))
            for field, value in (
                ("published_at", comment.get("published_at")),
                ("collected_at", comment.get("collected_at") or row.get("collected_at") or batch.get("collected_at")),
                ("video.published_at", video.get("published_at")),
            ):
                try:
                    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                        raise ValueError()
                except (AttributeError, TypeError, ValueError):
                    errors.append((field, "invalid_timestamp"))
            if not errors:
                try:
                    normalized = normalize_batch({**batch, "videos": [{**row, "comments": [comment]}]})
                    validate_sources(normalized)
                    expected_video_url = "https://www.youtube.com/watch?" + urlencode({"v": vid})
                    if video["video_url"] != expected_video_url:
                        raise ValueError()
                    records.extend(normalized)
                except (KeyError, ValueError, TypeError):
                    errors.append(("source_metadata", "inconsistent"))
            issues.extend({"video_id": vid, "comment_id": cid, "field": field, "reason": reason}
                          for field, reason in errors)
    if batch.get("comment_count") != received:
        issues.append({"field": "comment_count", "reason": "count_mismatch"})
    return {"records": records, "audit": {"received_comments": received,
        "valid_records": len(records), "issues": issues,
        "unknown_brand_count": len(records), "evidence_quality": "not_assessed"}}


def analyze_records(records, execution, *, progress=None):
    if not isinstance(execution, Execution):
        raise ControlError("A server-owned execution is required.")
    execution.check()  # before inspecting records or loading a key
    reviews = copy.deepcopy(records)
    if any(r.get("source_platform") != "youtube" or r.get("is_synthetic") is not False or r.get("text_is_preview") for r in reviews):
        raise ControlError("Only full provenance-preserving YouTube records are accepted.")
    if len(reviews) > 50 or len({r["review_id"] for r in reviews}) != len(reviews):
        raise ValueError("Invalid record count or duplicate identity.")
    validate_sources(reviews)
    state = {"run_id": execution.run_id, "purpose": execution.purpose, "model": execution.check()["model"],
             "schema_version": EVIDENCE_VERSION, "collected": len(reviews), "results": [], "failures": [], "unprocessed": len(reviews),
             "usage": {}, "status": "completed", "collected_at": datetime.now(timezone.utc).isoformat()}
    settings = None

    def record_usage(usage):
        for key, count in usage.items():
            state["usage"][key] = state["usage"].get(key, 0) + count

    for index, review in enumerate(reviews):
        if index >= execution.check()["max_calls"]:
            state["status"] = "budget_stopped"
            break
        if progress:
            progress("analyzing", index, len(reviews))
        try:
            execution.check()
            if settings is None:
                settings = classifier.load_local_settings()
            output, usage = classifier.classify_qwen(review, settings, state["model"], automatic=execution)
            normalized = output["normalized"]
            state["results"].append({**review, "brand": normalized["brand"]["name"], "analysis": normalized,
                                     "processing": output, "usage": usage})
            record_usage(usage)
            if not all(key in usage for key in classifier.TOKEN_FIELDS):
                state["status"] = "usage_unknown_stopped"
                state["unprocessed"] = len(reviews) - index - 1
                break
        except ControlError:
            state["status"] = "permission_or_budget_stopped"
            break
        except classifier.ClassificationError as failure:
            record_usage(failure.usage)
            entry = {"review_id": review["review_id"], "reason": str(failure)}
            if getattr(failure, "raw_model_text", None) is not None:
                # Keep a source-only fallback for a rejected model output. It never enters statistics.
                entry["source"] = review
            if hasattr(failure, "processing"):
                entry["processing"] = failure.processing
            if getattr(failure, "raw_model_text", None) is not None:
                entry["raw_model_text"] = failure.raw_model_text
            state["failures"].append(entry)
            state["status"] = "failed_stopped"
            state["unprocessed"] = len(reviews) - index - 1
            break
        state["unprocessed"] = len(reviews) - index - 1
    if all(key in state["usage"] for key in classifier.TOKEN_FIELDS):
        usage = state["usage"]
        p = execution.check()
        cost = (usage["prompt_tokens"] * Decimal(str(p["input_cny_per_million"]))
                + usage["completion_tokens"] * Decimal(str(p["output_cny_per_million"]))) / 1_000_000
        state["estimated_cny"] = format(cost, "f")
    if progress:
        progress("reporting", len(state["results"]), len(reviews))
    from research_quality import render_live_specialist
    execution.check()
    state["report"] = render_live_specialist(state, execution=execution)
    return state


def start_research(query, purpose, months, *, policy=None, paid_confirmed=False, progress=None, ledger_path=None):
    if purpose not in {"improvement", "competitor"}:
        raise ValueError("Invalid research purpose.")
    query = orchestrator.youtube_search.validate_query(query)
    orchestrator.video_cutoff(months)
    phase_k = isinstance(policy, dict) and policy.get("batch_profile") == PHASE_K
    gates = analysis_readiness(policy, purpose)
    deadline = None
    options = {}
    if phase_k:
        active = load_policy()
        if not gates["ready"] or active is None or with_batch_profile(active, PHASE_K) != policy:
            return {"mode": "blocked", "reason": "Phase K 扩容授权或本机配置尚未通过，未启动采集。"}
        deadline = monotonic() + PHASE_K_RUN_SECONDS
        options = {"phase_k": True, "deadline": deadline}
    if progress:
        progress("collecting", 0, 20 if phase_k else 5)
    batch = orchestrator.multi_video_research(query, months=months, live=True, progress=progress, **options)
    collection = inspect_collection(batch)
    gates["paid_confirmed"] = paid_confirmed is True
    if not gates["ready"] or not gates["paid_confirmed"]:
        reasons = [gates[k]["reason"] for k in ("youtube", "provider", "technical") if not gates[k]["ready"]]
        if not gates["paid_confirmed"]:
            reasons.append("本次付费请求尚未确认（与平台授权分开）。")
        return {"mode": "live-read-only", "batch": batch, **collection, "controls": gates,
                "report": None, "reason": "获取、转换、校验已完成；分析未执行：" + " ".join(reasons)}
    if collection["audit"]["issues"]:
        return {"mode": "live-read-only", "batch": batch, **collection, "controls": {**gates, "ready": False},
                "report": None, "reason": "来源字段校验有异常，未启动分析；原始预览与异常字段仍可查看。"}
    reviews = collection["records"]
    if policy.get("budget_mode") == BATCH_BUDGET_MODE:
        from multi_comment_research import run_batch_research
        try:
            result = run_batch_research(query, reviews, policy, purpose, paid_confirmed=paid_confirmed,
                                        progress=progress, ledger_path=ledger_path, deadline=deadline)
        except ControlError:
            return {"mode": "live-read-only", "batch": batch, **collection, "controls": gates,
                    "report": None, "reason": "分析授权、配置或预算校验未通过。本轮已停止。"}
        return {"mode": "research", "batch": batch, **collection, "controls": gates, **result}
    if policy.get("budget_mode") == KEYWORD_BUDGET_MODE:
        # Prefer a substantive comment near 350 characters. This is an explicit
        # convenience sample, independent of the analysis result.
        for row in sorted(reviews, key=lambda row: abs(len(row["review_text"]) - 350)):
            original = row["review_text"]
            messages = [{"role": "system", "content": PROMPT},
                        {"role": "user", "content": json.dumps(evidence_message(original), ensure_ascii=False)}]
            if message_token_estimate(messages) <= policy["max_input_tokens"]:
                policy = {**policy, "budget_mode": "single_request_estimate", "single_request_id": uuid.uuid4().hex,
                          "selected_review_id": row["review_id"], "selected_text_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest()}
                break
        else:
            return {"mode": "live-read-only", "batch": batch, **collection, "controls": gates, "report": None,
                    "reason": "本轮没有符合输入上限的有效评论，未调用 Qwen。可调整关键词或视频时间范围。"}
    if policy.get("budget_mode") == "single_request_estimate":
        reviews = [row for row in reviews if row["review_id"] == policy["selected_review_id"]]
        if len(reviews) != 1:
            return {"mode": "live-read-only", "batch": batch, **collection, "controls": {**gates, "ready": False},
                    "report": None, "reason": "本次采集中未找到已确认的首次候选评论，未发送 Qwen；不会自动替换候选。"}
    kwargs = {} if ledger_path is None else {"ledger_path": ledger_path}
    import real_pipeline
    try:
        execution = Execution(policy, purpose, paid_confirmed=paid_confirmed, run_id=str(uuid.uuid4()), **kwargs)
        result = real_pipeline.run_real_analysis(reviews, model=policy["model"], max_reviews=policy["max_calls"], execution=execution, progress=progress)
    except ControlError:
        return {"mode": "live-read-only", "batch": batch, **collection, "controls": {**gates, "ready": False},
                "report": None, "reason": "分析执行条件已变化或校验未通过，已停止分析；已获取的来源与字段核验仍可查看。"}
    return {"mode": "research", "batch": batch, **collection, "controls": gates, **result}
