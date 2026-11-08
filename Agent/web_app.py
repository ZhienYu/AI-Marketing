"""Keyword-only automatic research UI; permission and payment checks stay server-side."""
import time
import hashlib
import json
import streamlit as st
from analysis_control import (
    BATCH_BUDGET_MODE, BATCH_PROFILES, KEYWORD_BUDGET_MODE, ControlError,
    load_config, analysis_readiness, with_batch_profile,
)
from automatic_research import start_research, inspect_collection
from business_report_ui import render_business_report
from consumer_needs import PURPOSES
from session_memory import SessionResult


def clear_results():
    stored = st.session_state.get("research_result")
    if isinstance(stored, SessionResult):
        stored.clear()
    for key in ("research_result", "result_expiry", "paid_confirmed", "ui_error"):
        st.session_state.pop(key, None)


def main():
    st.set_page_config(page_title="Product Insight Agent", page_icon="🔎", layout="wide")
    # Remove legacy preview/demo state when upgrading an existing browser session.
    for key in ("demo_bundle", "mode", "multi_result", "live_preview", "live_discovery", "selected_video"):
        st.session_state.pop(key, None)
    if time.time() >= st.session_state.get("result_expiry", float("inf")):
        clear_results()
    if st.session_state.pop("payment_spent", False):
        st.session_state.pop("paid_confirmed", None)
    st.title("Product Insight Agent")
    @st.fragment(run_every="60s")
    def expiry_watch():
        stored = st.session_state.get("research_result")
        if stored is not None and not stored.snapshot():
            clear_results()
            st.rerun()
    expiry_watch()
    st.write("输入产品关键词，自动发现视频、获取反馈，并在获准后生成有来源证据的研究报告。")
    query = st.text_input("产品关键词", key="keyword", placeholder="例如 Robotic Pool Cleaner", on_change=clear_results)
    purpose = st.selectbox("研究类型", list(PURPOSES), format_func=PURPOSES.get, key="research_purpose", on_change=clear_results)
    months = st.selectbox("视频发布时间范围", [3, 6, 12], index=1, format_func=lambda m: f"最近 {m} 个月", key="video_months", on_change=clear_results)
    policy = load_config()
    if isinstance(policy, dict) and policy.get("budget_mode") == BATCH_BUDGET_MODE:
        mode = st.radio("分析规模", tuple(BATCH_PROFILES),
                        format_func={"standard": "标准 · 10 条", "pilot15": "Phase H 试验 · 15 条"}.get,
                        key="batch_profile", horizontal=True, on_change=clear_results)
        profile = BATCH_PROFILES[mode]
        st.caption(f"目标 {profile.comments} 条 · 最多 {profile.calls} 次 Qwen 请求 · 整轮预留上限 ¥{profile.reservation_cny}。"
                   "采集范围一致，分析须通过用途授权、第三方处理与预算检查，并在本轮确认付费。")
        try:
            policy = with_batch_profile(policy, mode)
        except (ControlError, ValueError, TypeError, KeyError, ArithmeticError):
            policy = None
    signature = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    if signature != st.session_state.get("policy_signature"):
        clear_results()
        st.session_state.policy_signature = signature
    gates = analysis_readiness(policy, purpose)
    ready = gates["ready"]
    for name, label in (("youtube", "YouTube 用途授权"), ("provider", "Qwen 第三方处理"), ("technical", "技术与预算")):
        if not ready:
            st.caption(label + ("：记录检查通过" if gates[name]["ready"] else "：" + gates[name]["reason"]))
    if not ready:
        st.info("LIVE READ-ONLY：获取、标准 JSON 转换、字段校验及按视频预览可用。只有分析步骤受上方独立条件限制；这些条件不是 YouTube API 的技术限制。")
        if st.session_state.get("research_result", {}).get("mode") == "research":
            clear_results()
    with st.expander("数据使用说明与运行上限"):
        st.write("最多五个视频、每个最多十条顶层评论，不翻页。时间范围筛选视频，不是全部评论历史。真实正文和报告只在本次会话内存展示，不保存文件、不提供下载、不发送给模型以外的分析服务。")
        st.write("没有分析许可时只读取预览。获准后才将研究关键词和选样所需的评论原文发送至百炼北京地域；不发送密钥、评论者身份或来源链接。预算账本仅保存运行编号、日期和费用预留，不保存评论。")
        st.write("结果在服务器内存最多保留十五分钟，后台定时清除；活动页面每分钟检查到期并移除展示。清除结果或停止本地服务也可移除服务器会话内容。")
        st.markdown("本应用使用 YouTube API Services。使用须遵守 [YouTube 服务条款](https://www.youtube.com/t/terms)，另见 [Google 隐私政策](https://policies.google.com/privacy)。公开发布前仍需完成适用审查和正式隐私政策。")
        st.checkbox("我已阅读并同意数据使用说明", key="privacy_accepted", on_change=clear_results)
    paid = False
    if ready:
        st.caption(f"模型 {policy['model']} · 最多 {policy['max_calls']} 次调用 · 单次运行预留上限 ¥{policy['run_cny_limit']} · UTC 每日累计上限 ¥{policy['daily_cny_limit']}。")
        if policy.get("budget_mode") == BATCH_BUDGET_MODE:
            st.caption(f"每次输出上限 {policy['max_output_tokens']} Token。"
                       "输入采用保守估算，实际账单以百炼为准。模型不自动重试。")
        elif policy.get("budget_mode") == KEYWORD_BUDGET_MODE:
            st.caption(f"从本轮有效评论中自动选择一条进行分析，输出最多 {policy['max_output_tokens']} Token。输入采用保守估算，账本每次预留 ¥0.0094，实际费用以服务商账单为准。Qwen 不自动重试。")
        elif policy.get("budget_mode") == "single_request_estimate":
            st.warning(f"首次单条实验：输入仅设 {policy['max_input_tokens']} Token 估算阈值，输出最多 {policy['max_output_tokens']} Token；Token 上界未严格验证，¥1 是预算目标而非实际账单硬保证。同一实验最多一次请求，失败或超时也不自动重试。")
        else:
            st.caption(f"每次最多输入 {policy['max_input_tokens']} / 输出 {policy['max_output_tokens']} Tokens；本次 Token 总预留上限 {policy['run_token_limit']}。超时和失败不退款、不自动重试。")
        paid = st.checkbox("我确认本次研究会发起付费 Qwen 请求，并同意上述上限", key="paid_confirmed")
    progress_bar = st.progress(0)
    status = st.empty()
    def progress(stage, completed, total):
        labels = {"collecting": "自动获取视频与评论", "analyzing": "质量筛选与 Qwen 需求分析", "reporting": "生成证据报告"}
        status.write(f"{labels[stage]}：{completed}/{total}")
        base, span = {"collecting": (0, .25), "analyzing": (.25, .65), "reporting": (.9, .09)}[stage]
        progress_bar.progress(min(.99, base + span * completed / max(total, 1)))
    if st.button("开始研究", key="start_research", type="primary", disabled=not st.session_state.get("privacy_accepted")) and st.session_state.get("privacy_accepted"):
        previous = st.session_state.pop("research_result", None)
        if previous is not None:
            previous.clear()
        st.session_state.pop("ui_error", None)
        try:
            result = start_research(query, purpose, months, policy=policy, paid_confirmed=paid, progress=progress)
            st.session_state.research_result = SessionResult(result)
            st.session_state.result_expiry = time.time() + 900
            progress_bar.progress(1.0)
            status.write("本轮已结束。部分失败或预算停止请查看结果状态。")
        except Exception:
            st.session_state.ui_error = "本次研究未完成。请检查网络、API 配置、权限有效期及预算。未显示原始错误以保护密钥；不会自动重试付费模型请求。"
        finally:
            if ready:
                st.session_state.payment_spent = True
    if st.session_state.get("ui_error"):
        st.error(st.session_state.ui_error)
    result = st.session_state.get("research_result")
    result = result.snapshot() if result is not None else None
    if result:
        if result["mode"] == "research":
            view = result.get("business_view")
            status_code = result.get("status", "completed")
            explanations = {
                "partially_completed": "部分批次无法解析，或部分评论条目缺失、未通过校验。",
                "request_failed": "有一批模型请求失败。",
                "permission_or_budget_stopped": "授权或预算检查停止了后续请求。",
                "invalid_provider_response": "模型响应的版本、用量或完整性异常，后续分析已停止。",
                "insufficient_data": "未找到足够的相关评论提交分析。",
            }
            if status_code != "completed":
                coverage = view.coverage if view is not None else None
                scope = f"已提交 {coverage.submitted} 条评论，保留 {coverage.qualitative} 条定性来源。" if coverage else ""
                st.warning(f"{explanations.get(status_code, '分析部分完成。')}{scope}详情可在技术区查看。")
            if view is not None:
                render_business_report(view, months=months, purpose=PURPOSES[purpose])
            else:
                st.markdown(result["report"])
            if "target_comments" in result and result["selected"] < result["target_comments"]:
                st.caption(f"目标 {result['target_comments']} 条，本轮选中 {result['selected']} 条。"
                           "选样筛选与批次限制见技术详情。")
            if "estimated_cny" in result:
                st.caption(f"本轮 Qwen 估算费用 ¥{result['estimated_cny']}。")
            elif result.get("status") == "request_failed" and result.get("api_calls"):
                known = result.get("known_cost_cny")
                label = f"已返回用量的批次估算 ¥{known}。" if known is not None else ""
                st.caption(label + "请求失败批次的费用未知，已保留账本预留。请以百炼账单为准。")
        else:
            st.warning(result["reason"])
        batch = result["batch"]
        st.caption(f"本轮获取：{batch['searched_videos']} 个搜索结果，{batch['videos_with_comments']} 个有评论视频，{batch['comment_count']} 条去重评论。")
        audit = result.get("audit") or inspect_collection(batch)["audit"]
        if audit["issues"]:
            st.warning("部分来源字段缺失或不一致，本轮分析未启动。")
        with st.expander("Advanced Details · 技术详情"):
            st.caption(f"实际 {audit['received_comments']} 条，标准 JSON 有效记录 {audit['valid_records']} 条，异常 {len(audit['issues'])} 项。")
            st.caption("时间筛选针对视频发布时间。每个视频仅获取第一页公开顶层评论。")
            if audit["issues"]:
                st.dataframe(audit["issues"], hide_index=True)
            if "selection" in result:
                st.caption(f"模型 {result['model']} · Schema {result['schema_version']} · Qwen 请求 {result['api_calls']} 次 · 运行状态 {result['status']}")
                st.json(result["usage"])
                outcomes = result.get("outcomes", {})
                report_outcomes = result.get("report_outcomes", {})
                if report_outcomes:
                    stages = ("批次 JSON 解析失败", "批次结构或评论标识异常", "模型返回但未通过校验",
                              "模型返回批次，缺少可用评论条目", "模型归属未通过，保留可核对原文")
                    st.caption(" · ".join(
                        [f"{label} {sum(value == label for value in outcomes.values())} 条" for label in stages]
                        + [f"报告层过滤 {sum(value == '报告层过滤' for value in report_outcomes.values())} 条"]
                    ))
                st.dataframe([{**row, "分析结果": outcomes.get(row["review_id"], ""),
                               "报告结果": report_outcomes.get(row["review_id"], "")}
                              for row in result["selection"]], hide_index=True)
                if result.get("batch_runs"):
                    st.caption(f"预算账本运行编号 {result['run_id']}")
                    st.json(result["batch_runs"])
                st.json([{"review_id": row["review_id"], "status": row["processing"]["status"],
                          "normalizations": row["processing"]["normalizations"],
                          "claims": row["processing"]["claim_quality"], "spans": row["processing"].get("evidence_spans", []),
                          "issues": row["processing"]["issues"]} for row in result["results"]])
                if result.get("business_diagnostics"):
                    st.json(result["business_diagnostics"])
                if result["failures"]:
                    st.json(result["failures"])
                if result["responses"]:
                    st.json(result["responses"])
        with st.expander("查看各视频原始来源和只读评论"):
            for index, row in enumerate(batch["videos"], 1):
                st.subheader(f"{index}. {row['video']['title']}")
                st.caption(f"Video ID: {row['video']['video_id']} · 视频发布：{row['video']['published_at']} · 本视频 {len(row['comments'])} 条评论")
                st.link_button("YouTube 视频", row["video"]["video_url"])
                if row["failure_reason"]:
                    st.warning(row["failure_reason"])
                for number, comment in enumerate(row["comments"], 1):
                    if len(comment["review_text"]) > 240:
                        with st.expander(f"评论 {number} · 展开长评论"):
                            st.text(comment["review_text"])
                    else:
                        st.text(comment["review_text"])
                    st.caption(comment["comment_id"] + " · " + comment["published_at"])
                    st.link_button("YouTube 评论", comment["source_url"])
                if not row["comments"] and not row["failure_reason"]:
                    st.caption("本视频未返回公开顶层评论。")
                st.divider()
        st.button("清除本次结果", key="clear_session", on_click=clear_results)


if __name__ == "__main__":
    main()
