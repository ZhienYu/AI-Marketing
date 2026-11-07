"""Keyword-only automatic research UI; permission and payment checks stay server-side."""
import time
import hashlib
import json
import streamlit as st
from analysis_control import KEYWORD_BUDGET_MODE, load_config, analysis_readiness
from automatic_research import start_research, inspect_collection
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
    signature = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    if signature != st.session_state.get("policy_signature"):
        clear_results()
        st.session_state.policy_signature = signature
    gates = analysis_readiness(policy, purpose)
    ready = gates["ready"]
    for name, label in (("youtube", "YouTube 用途授权"), ("provider", "Qwen 第三方处理"), ("technical", "技术与预算")):
        st.caption(label + ("：记录检查通过" if gates[name]["ready"] else "：" + gates[name]["reason"]))
    if not ready:
        st.info("LIVE READ-ONLY：获取、标准 JSON 转换、字段校验及按视频预览可用。只有分析步骤受上方独立条件限制；这些条件不是 YouTube API 的技术限制。")
        if st.session_state.get("research_result", {}).get("mode") == "research":
            clear_results()
    with st.expander("数据使用说明与运行上限"):
        st.write("最多五个视频、每个最多十条顶层评论，不翻页。时间范围筛选视频，不是全部评论历史。真实正文和报告只在本次会话内存展示，不保存文件、不提供下载、不发送给模型以外的分析服务。")
        st.write("没有分析许可时只读取预览。获准后才将必要原文发送至百炼北京地域；不发送密钥、评论者身份或来源链接。预算账本仅保存运行编号、日期和费用预留，不保存评论。")
        st.write("结果在服务器内存最多保留十五分钟，后台定时清除；活动页面每分钟检查到期并移除展示。清除结果或停止本地服务也可移除服务器会话内容。")
        st.markdown("本应用使用 YouTube API Services。使用须遵守 [YouTube 服务条款](https://www.youtube.com/t/terms)，另见 [Google 隐私政策](https://policies.google.com/privacy)。公开发布前仍需完成适用审查和正式隐私政策。")
        st.checkbox("我已阅读并同意数据使用说明", key="privacy_accepted", on_change=clear_results)
    paid = False
    if ready:
        st.caption(f"模型 {policy['model']} · 最多 {policy['max_calls']} 次调用 · 单次运行预留上限 ¥{policy['run_cny_limit']} · UTC 每日累计上限 ¥{policy['daily_cny_limit']}。")
        if policy.get("budget_mode") == KEYWORD_BUDGET_MODE:
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
            st.markdown(result["report"])
            if "estimated_cny" in result:
                usage = result["usage"]
                st.caption(f"本轮 Qwen · 输入 {usage['prompt_tokens']} / 输出 {usage['completion_tokens']} Token · 按配置单价估算 ¥{result['estimated_cny']}。")
            if result.get("status", "completed") != "completed":
                st.warning("分析未完整完成。请查看报告中的来源、失败记录和运行状态。")
        else:
            st.warning(result["reason"])
        batch = result["batch"]
        st.caption(f"本轮获取：{batch['searched_videos']} 个搜索结果，{batch['videos_with_comments']} 个有评论视频，{batch['comment_count']} 条去重评论。")
        audit = result.get("audit") or inspect_collection(batch)["audit"]
        st.caption(f"字段核验：实际 {audit['received_comments']} 条，标准 JSON 有效记录 {audit['valid_records']} 条，异常 {len(audit['issues'])} 项。brand=unknown 表示尚未确认品牌，证据质量尚未评估。")
        st.caption("最近月份仅筛选视频发布时间；评论按最新顺序读取最多十条，不保证覆盖该时间段所有评论。")
        if audit["issues"]:
            st.warning("部分来源字段缺失或不一致；以下仅显示字段诊断，不进行分析。")
            st.dataframe(audit["issues"], hide_index=True)
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
