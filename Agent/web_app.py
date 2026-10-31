"""Local product discovery interface; real analysis remains unavailable."""

import streamlit as st

import orchestrator
import real_pipeline


RESULT_KEYS = ("live_discovery", "live_preview", "selected_video", "ui_error")


def clear_results():
    for key in RESULT_KEYS:
        st.session_state.pop(key, None)


def clear_preview():
    st.session_state.pop("live_preview", None)
    st.session_state.pop("ui_error", None)


def friendly_error(failure):
    message = str(failure)
    if "commentsDisabled" in message:
        return "这个视频已关闭评论。请选择另一个视频，再点击读取。"
    if any(marker in message for marker in ("quotaExceeded", "dailyLimitExceeded", "http=429")):
        return "YouTube 配额或访问频率已达到限制。请查看 Google Cloud 配额，稍后再试。"
    if any(marker in message for marker in ("keyInvalid", "API_KEY_INVALID", "YOUTUBE_API_KEY", "Cannot read Agent/.env")):
        return "本机 YouTube 凭据未就绪。请自行检查本地配置，不要将密钥粘贴到网页或聊天中。"
    if any(marker in message for marker in ("SERVICE_DISABLED", "accessNotConfigured", "http=403", "API_KEY_SERVICE_BLOCKED")):
        return "YouTube 拒绝了请求。请检查服务是否启用，以及本机凭据的服务权限和应用限制。"
    if "ssl" in message.casefold():
        return "安全连接校验未通过。请检查系统时间、证书及网络设置，不要关闭证书校验。"
    if any(marker in message for marker in ("connection_reset", "timeout", "category=dns", "Connection failed", "Connection was")):
        return "连接 YouTube 时遇到网络波动。本次有限尝试已结束，请稍后手动重试；没有保存真实评论。"
    if "http=404" in message or "videoNotFound" in message:
        return "这个视频已不可用。请重新搜索或选择另一个公开视频。"
    if "non-empty keyword" in message or "keyword must be text" in message:
        return "请输入 1–200 个字符的产品名称或品类，且不要包含控制字符。"
    return "本次操作未完成。请检查输入和本地配置后重试；未显示原始错误详情，以保护敏感信息。"


def render_discovery(query, *, privacy_accepted):
    st.info("LIVE READ-ONLY · 数据来源：YouTube。最多搜索 5 个视频，读取所选视频最多 10 条顶层评论，预览前三条。")
    st.caption("仅点击搜索或读取按钮才调用 API；暂时网络错误最多尝试两次。刷新、选片不会自动请求。")
    if st.button("搜索 YouTube 视频", type="primary", key="search_live", disabled=not privacy_accepted) and privacy_accepted:
        clear_results()
        try:
            query = orchestrator.youtube_search.validate_query(query)
            with st.spinner("正在搜索公开视频…"):
                st.session_state.live_discovery = orchestrator.discover_live_videos(query, live=True)
        except Exception as failure:
            st.session_state.ui_error = friendly_error(failure)
    discovery = st.session_state.get("live_discovery")
    if discovery:
        videos = discovery["videos"][:5]
        st.caption("当前搜索关键词：" + discovery["query"])
        if not videos:
            st.info("没有找到视频。请调整关键词后重新点击搜索。")
        else:
            st.subheader("选择一个视频")
            for index, video in enumerate(videos, 1):
                st.text(f"{index}. {video['title']}")
                st.text(f"频道：{video['channel_title']} · 发布：{video['published_at']}")
                st.link_button("在 YouTube 查看视频 " + str(index), video["video_url"])
            ids = [video["video_id"] for video in videos]
            st.radio("要读取的视频", ids, format_func=lambda video_id: str(ids.index(video_id) + 1) + ". " + video_id, key="selected_video", on_change=clear_preview)
            if st.button("读取所选视频评论", key="read_comments", disabled=not privacy_accepted) and privacy_accepted:
                clear_preview()
                try:
                    with st.spinner("正在读取评论，仅预览前三条…"):
                        preview = orchestrator.preview_live_video(discovery, st.session_state.selected_video, live=True)
                        st.session_state.live_preview = real_pipeline.build_read_only_preview(preview)
                except Exception as failure:
                    st.session_state.ui_error = friendly_error(failure)
    if st.session_state.get("ui_error"):
        st.error(st.session_state.ui_error)
    preview = st.session_state.get("live_preview")
    if preview:
        st.subheader("公开评论预览")
        st.caption(f"读取 {preview['count']} 条，仅展示最多 3 条，每条正文最多 240 字符。品牌保持 unknown。")
        st.caption("本次采集时间（UTC）：" + preview["collected_at"])
        st.caption("证据质量：not_assessed（尚未筛选）；不据此判断是否购买、使用过或表达正负情绪。")
        if not preview["comments"]:
            st.info("请求成功，但该视频没有返回公开顶层评论。")
        for comment in preview["comments"]:
            with st.container(border=True):
                st.text(comment["review_text"])
                st.text("review_id=" + comment["review_id"] + " · 发布：" + comment["published_at"])
                st.link_button("在 YouTube 查看评论来源", comment["source_url"])
        st.caption("短预览仅保留在当前会话内存，不写入文件；修改关键词、切换视频或清除结果后移除。")


def main():
    st.set_page_config(page_title="Product Insight Agent", page_icon="🔎", layout="wide")
    # Discard stale state after upgrading an already-running older Demo UI.
    for key in ("demo_bundle", "mode"):
        st.session_state.pop(key, None)
    with st.sidebar:
        st.title("Product Insight")
        st.caption("LOCAL MVP · YOUTUBE")
        st.write("产品发现 → 评论预览 → 获准后进行分析")
        st.button("清除本次结果", on_click=clear_results, key="clear_session")
        st.caption("反馈筛选、Qwen 分析、竞品比较和报告暂未启用。")
    st.title("发现产品相关的真实消费者讨论")
    st.write("输入产品名称或品类，搜索 YouTube 视频并选择要查看的评论来源。")
    query = st.text_input("产品关键词", value="", key="keyword", on_change=clear_results, placeholder="例如 Robotic Pool Cleaner")
    with st.expander("本地数据使用说明与来源条款"):
        st.write("本应用使用 YouTube API Services。仅在你点击按钮后，将关键词或所选视频 ID 发送给 Google；密钥仅供本机请求使用。")
        st.write("视频结果和最多三条短评论预览保留于当前 Streamlit 会话内存，不写入文件或日志，不发送给阿里云百炼或其他模型。修改关键词、清除结果或停止本地服务可移除结果。")
        st.write("本机浏览器与 Streamlit 建立会话连接；应用不添加广告、外部播放器或额外追踪工具。可通过侧栏清除结果，数据问题请联系本地项目维护者。公开发布前仍需补齐正式隐私政策、联系渠道和审查材料。")
        st.markdown("使用本功能须遵守 [YouTube 服务条款](https://www.youtube.com/t/terms)；另见 [Google 隐私政策](https://policies.google.com/privacy)。阅读本说明不代表取得评论分析许可。")
    accepted = st.checkbox("我已阅读并同意本地数据使用说明", key="privacy_accepted", on_change=clear_results)
    render_discovery(query, privacy_accepted=accepted)
    st.divider()
    st.subheader("下一步：消费者洞察与研究报告")
    st.warning(real_pipeline.analysis_status()["reason"])
    st.button("筛选反馈 → Qwen 分析 → 生成报告（待许可）", disabled=True, key="analyze_real")


if __name__ == "__main__":
    main()
