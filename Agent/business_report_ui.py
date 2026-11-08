"""Streamlit renderer for BusinessReportView."""

from html import escape

import altair as alt
import streamlit as st


CSS = """
<style>
:root { color-scheme: light; }
.stApp { background: #f2f5f6; color: #102d34; }
.stApp header[data-testid="stHeader"] { background: #f2f5f6; }
.block-container { max-width: 1120px; padding: 2.5rem 2rem 4rem; }
.br-hero { padding: clamp(1.4rem,5vw,3.6rem); border-radius: 1rem; color: #fff;
  background: radial-gradient(ellipse at 96% 0%,#21605a,transparent 58%),#102d34; }
.br-kicker { font: 700 .74rem/1.4 system-ui; letter-spacing: .14em; color: #a4e5cc; }
.br-hero h1 { color: #fff; font: 730 clamp(2.1rem,6vw,4.25rem)/1.05 system-ui;
  margin: .65rem 0; letter-spacing: -.045em; overflow-wrap: anywhere; }
.br-hero p { max-width: 42rem; margin: .65rem 0 0; color: #e0f1ec; }
.br-nav { display: flex; flex-wrap: wrap; gap: .35rem 1.15rem; padding: 1rem .15rem; }
.br-nav a, .br-links a { color: #096257; font-size: .85rem; font-weight: 680; text-decoration: underline;
  text-underline-offset: .21em; }
.br-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,250px),1fr));
  gap: .65rem; margin: .3rem 0 .65rem; align-items: start; }
.br-metric, .br-card { background: #fff; color: #102d34; border: 1px solid #d8e5e3;
  border-radius: .75rem; padding: .9rem 1rem; overflow-wrap: anywhere; }
.br-metric { display: flex; flex-direction: column; gap: .13rem; }
.br-metric strong { font: 730 2rem/1.12 system-ui; font-variant-numeric: tabular-nums; }
.br-metric span { color: #455f63; font-size: .86rem; }
.br-card h3 { color: #102d34; font-size: 1.06rem; line-height: 1.4; margin: .35rem 0; padding: 0; }
.br-card p { color: #3f595c; font-size: .93rem; margin: .25rem 0 .6rem; }
.br-card .br-meaning { border-left: 2px solid #8ac5b4; padding-left: .55rem; }
.br-card .br-meaning strong { color: #155e54; }
.br-badge { color: #166458; background: #e8f5f0; font-size: .73rem; font-weight: 680;
  padding: .18rem .45rem; border-radius: .3rem; }
.br-links { display: flex; flex-wrap: wrap; align-items: baseline; gap: .15rem .65rem;
  color: #455f63; font-size: .8rem; }
.br-purchase { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,300px),1fr));
  gap: .7rem; margin: .35rem 0 .8rem; }
.br-purchase section { padding: .85rem 1.05rem; border-radius: .7rem; background: #e5f3ee;
  color: #102d34; border-top: 3px solid #327d6f; }
.br-purchase section:last-child { background: #faf1e5; border-color: #a16c37; }
.br-purchase h3 { font-size: 1rem; padding: 0; color: #102d34; }
.br-purchase ul { margin-bottom: 0; }
.br-purchase li p { color: #3f595c; font-size: .9rem; margin: .2rem 0 .6rem; }
[data-testid="stText"] { white-space: pre-wrap; overflow-wrap: anywhere; }
@media(max-width: 550px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .br-nav { gap: .4rem .8rem; }
}
</style>
"""

SECTIONS = (
    ("executive-summary", "研究摘要"),
    ("needs", "需求、痛点与偏好"),
    ("purchase", "购买考虑"),
    ("competitors", "竞品讨论"),
    ("opportunities", "商业机会"),
    ("sources", "原文与限制"),
)

STATUS_LABELS = {
    "validated": "已有通过校验的模型分析",
    "unverified": "真实原文 · 历史实验未达到本预览的校验条件",
    "exploratory": "真实原文 · 支持探索性观察，归属或内容仍有局限",
    "raw": "真实原文 · 尚未进入模型分析",
}


def source_links(report, item):
    links = " ".join(
        f'<a href="#source-{label.lower()}">{escape(label)}</a>'
        for label in dict.fromkeys(item.sources)
    )
    return f'<span class="br-links">{report.mentions(item)} 条评论 {links}</span>'


def cards(report, items):
    html = ['<div class="br-grid">']
    for item in items:
        badge = f'<span class="br-badge">{escape(item.badge)}</span>' if item.badge else ""
        meaning = (
            f'<p class="br-meaning"><strong>对产品或选购的启发</strong> {escape(item.business_meaning)}</p>'
            if item.business_meaning else ""
        )
        # Full evidence remains in the source expander. A second English quote
        # on the card crowds out the finding and makes the source appear twice.
        detail = "" if item.detail.startswith("原文示例 「") else item.detail
        detail_html = f"<p>{escape(detail)}</p>" if detail else ""
        html.append(
            f'<article class="br-card">{badge}<h3>{escape(item.title)}</h3>'
            f'{detail_html}{meaning}{source_links(report, item)}</article>'
        )
    st.html("".join(html) + "</div>")


def topics_chart(report):
    rows = [{"theme": item.title, "count": report.mentions(item)} for item in report.topics]
    maximum = max(row["count"] for row in rows)
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("count:Q", title=None, axis=alt.Axis(tickMinStep=1, gridColor="#e1eae8"),
                scale=alt.Scale(domain=[0, maximum * 1.25])),
        y=alt.Y("theme:N", title=None, sort=[row["theme"] for row in rows],
                axis=alt.Axis(labelFontSize=13, labelLimit=150, ticks=False)),
        tooltip=[alt.Tooltip("theme:N", title="主题"), alt.Tooltip("count:Q", title="评论数")],
    )
    chart = (
        base.mark_bar(color="#187469", cornerRadiusEnd=5, size=23)
        + base.mark_text(align="left", dx=8, color="#102d34", fontSize=14).encode(text="count:Q")
    ).properties(height=max(115, 37 * len(rows))).configure_view(stroke=None)
    st.altair_chart(chart, width="stretch")
    st.caption("按去重评论 ID 计数。同一条评论可涉及多个主题。")


def purchase_breakdown(report):
    if not report.demo:
        cards(report, report.purchase)
        return
    groups = [tuple(item for item in report.purchase if item.badge == label)
              for label in ("购买驱动", "待解决障碍")]
    html = ['<div class="br-purchase">']
    for label, items in zip(("购买驱动", "待解决障碍"), groups):
        count = len({source for item in items for source in item.sources})
        html.append(f"<section><h3>{label} · {count} 条评论</h3>")
        if items:
            html.append("<ul>")
            for item in items:
                html.append(
                    f"<li><strong>{escape(item.title)}</strong> {source_links(report, item)}"
                    f"<p>{escape(item.detail)}</p></li>"
                )
            html.append("</ul>")
        else:
            html.append("<p>本样本没有足够证据。</p>")
        html.append("</section>")
    st.html("".join(html) + "</div>")


def render_business_report(report, *, months=None, purpose=None, original_collection=None):
    """The optional (comments, videos) pair labels a frozen historical run."""
    st.html(CSS)
    status = "DEMO · 真实评论 / 人工演示洞察" if report.demo else "BUSINESS RESEARCH · 真实 YouTube 样本"
    if original_collection is not None:
        status = "历史离线回放 · 真实评论与历史模型响应"
    st.html(
        f'<section class="br-hero"><div class="br-kicker">PRODUCT INSIGHT AGENT · {status}</div>'
        f'<h1>{escape(report.topic)}</h1><p>消费者商业洞察报告</p></section>'
    )
    has_insights = bool(report.summary or report.needs or report.purchase or report.competitors)
    visible = [
        bool(report.summary or report.topics), bool(report.needs), bool(report.purchase),
        bool(report.competitors), bool(report.opportunities) or (has_insights and not report.demo), True,
    ]
    nav = "".join(
        f'<a href="#{anchor}">{title}</a>'
        for (anchor, title), show in zip(SECTIONS, visible) if show and (
            anchor != "executive-summary" or report.summary
        )
    )
    if report.topics:
        topics_link = '<a href="#consumer-topics">消费者主题</a>'
        if report.summary:
            summary_end = nav.index("</a>") + len("</a>")
            nav = nav[:summary_end] + topics_link + nav[summary_end:]
        else:
            nav = topics_link + nav
    st.html(f'<nav class="br-nav" aria-label="报告章节">{nav}</nav>')
    metrics = [
        (len(report.sources), "本页原始评论"), (report.video_count, "来源视频"),
        (report.validated_count, "本页已导入的已校验分析"),
    ]
    if report.coverage:
        coverage = report.coverage
        metrics = [(coverage.collected, f"采集评论 · {coverage.collected_videos} 个视频"),
                   (coverage.submitted, "提交分析"), (coverage.qualitative, "进入定性报告"),
                   (coverage.formal, "通过正式属性统计的评论")]
        if original_collection is not None:
            original_comments, original_videos = original_collection
            metrics[:2] = [(original_comments, f"原轮采集 · {original_videos} 个视频"),
                           (coverage.submitted, f"本次回放 · {coverage.collected_videos} 个视频")]
            st.caption(f"回放范围为原轮提交分析的 {coverage.submitted} 条评论。")
        if months is not None:
            st.caption(f"{purpose or '研究范围'} · 最近 {months} 个月发布的视频")
    st.html('<div class="br-grid">' + "".join(
        f'<div class="br-metric"><strong>{value}</strong><span>{label}</span></div>'
        for value, label in metrics
    ) + "</div>")
    if not report.demo and not any(visible[:-1]):
        st.info("当前没有通过基本证据检查的洞察。可在技术详情和采集预览查看原因及已获取的评论。")
    if visible[0]:
        if report.summary:
            st.header("研究摘要", anchor="executive-summary")
            cards(report, report.summary)
        if report.topics:
            st.header("消费者主题", anchor="consumer-topics")
            if len(report.topics) > 1 and (report.demo or any(report.mentions(item) > 1 for item in report.topics)):
                topics_chart(report)
            elif report.demo or len(report.topics) > 1:
                cards(report, report.topics)
            else:
                st.caption(f"{report.topics[0].title} · {report.mentions(report.topics[0])} 条评论")
    for (anchor, title), items in zip(
        SECTIONS[1:5], (report.needs, report.purchase, report.competitors, report.opportunities)
    ):
        if items:
            st.header(title, anchor=anchor)
            if anchor == "competitors" and not report.demo:
                for label in ("原文产品提及", "原文购买自述", "推荐名单咨询", "原文选购候选", "原文对比"):
                    group = tuple(item for item in items if item.badge == label)
                    if group:
                        st.subheader({
                            "原文产品提及": "有品类证据的产品提及",
                            "原文购买自述": "评论者自述已购买",
                            "推荐名单咨询": "原文推荐名单讨论",
                            "原文选购候选": "评论者正在比较的选购候选",
                            "原文对比": "原文明确比较",
                        }[label])
                        cards(report, group)
                if not any(item.badge == "原文对比" for item in items):
                    st.caption("本轮没有足够证据判断候选型号的性能优劣。")
            else:
                specific = tuple(item for item in items if item.title != "未进一步分类")
                uncategorized = tuple(item for item in items if item.title == "未进一步分类")
                if anchor == "purchase" and report.demo:
                    purchase_breakdown(report)
                elif specific:
                    cards(report, specific)
                if uncategorized:
                    with st.expander("其他评论线索"):
                        cards(report, uncategorized)
    if visible[4] and not report.opportunities:
        st.header("商业机会", anchor="opportunities")
        st.caption("本轮暂无足够证据支持具体商业机会。")
    st.header("原文与限制", anchor="sources")
    for limitation in report.limitations:
        st.markdown(f"- {limitation}")
    for source in report.sources:
        st.html(f'<div id="source-{source.label.lower()}"></div>')
        with st.expander(f"{source.label} · 查看 YouTube 原文"):
            st.caption(f"{STATUS_LABELS[source.analysis_status]} · {source.published_at}")
            st.text(source.text)
            st.link_button("查看 YouTube 来源", source.url)
