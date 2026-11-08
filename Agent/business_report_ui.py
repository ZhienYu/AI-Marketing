"""Streamlit renderer for BusinessReportView."""

from html import escape

from business_research_presentation import purchase_groups

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
.br-card p { color: #3f595c; font-size: .94rem; line-height: 1.58; margin: .3rem 0 .65rem; }
.br-dense { columns: 2; column-gap: .75rem; margin: .35rem 0 .65rem; }
.br-dense .br-card { break-inside: avoid; margin: 0 0 .65rem; }
.br-card details { display: inline-block; color: #155e54; }
.br-card details summary { cursor: pointer; }
.br-scope { color: #455f63; font-size: .86rem; line-height: 1.6; padding: .55rem .15rem; }
.br-row { display: flex; flex-wrap: wrap; gap: .35rem .7rem; align-items: baseline; padding: .35rem 0;
  border-bottom: 1px solid #e1eae8; }

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
  .br-dense { columns: 1; }
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
    count = f"{report.mentions(item)} 条评论"
    if report.research_layout and report.mentions(item) > 6:
        return f'<div class="br-links">{count}<details><summary>查看证据编号</summary>{links}</details></div>'
    return f'<span class="br-links">{count} {links}</span>'


def cards(report, items, *, mode="detail"):
    layout = "br-dense" if report.research_layout and mode != "summary" else "br-grid"
    html = [f'<div class="{layout}">']
    for item in items:
        badge = f'<span class="br-badge">{escape(item.badge)}</span>' if item.badge else ""
        meaning = ""
        if item.business_meaning and (not report.research_layout or mode == "research"):
            label = "研究启示" if report.research_layout else "对产品或选购的启发"
            meaning = f'<p class="br-meaning"><strong>{label}</strong> {escape(item.business_meaning)}</p>'
        # Full evidence remains in the source expander. A second English quote
        # on the card crowds out the finding and makes the source appear twice.
        detail = "" if item.detail.startswith("原文示例 「") else item.detail
        prefix = "<strong>建议研究方向</strong> " if report.research_layout and mode == "research" else ""
        detail_html = f"<p>{prefix}{escape(detail)}</p>" if detail else ""
        html.append(
            f'<article class="br-card">{badge}<h3>{escape(item.title)}</h3>'
            f'{meaning}{detail_html}{source_links(report, item)}</article>'
        )
    st.html("".join(html) + "</div>")


def topics_chart(report, items=None):
    rows = [{"theme": item.title, "count": report.mentions(item)} for item in
            (report.topics if items is None else items)]
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


def _section_cards(report, items, compact, *, mode="detail"):
    if not compact or len(items) <= 6:
        cards(report, items, mode=mode)
        return
    cards(report, items[:6], mode=mode)
    with st.expander(f"查看本组其余 {len(items) - 6} 项"):
        cards(report, items[6:], mode=mode)


def _topic_details(report):
    parents = tuple(group.parent for group in report.topic_groups)
    if len(parents) > 1 and any(report.mentions(item) > 1 for item in parents):
        topics_chart(report, parents[:8])
    for group in report.topic_groups:
        with st.expander(f"{group.parent.title} · {report.mentions(group.parent)} 条评论"):
            rows = "".join(f'<div class="br-row"><strong>{escape(child.title)}</strong>{source_links(report, child)}</div>'
                           for child in group.children)
            st.html(rows)


def render_business_report(report, *, months=None, purpose=None, original_collection=None, compact=False,
                           preview_notice=None, source_links_enabled=True, data_mode="live"):
    """The optional (comments, videos) pair labels a frozen historical run."""
    if report.research_layout:
        from business_research_dashboard import render_dashboard
        render_dashboard(report, mode=data_mode, compact=compact, source_links_enabled=source_links_enabled,
                         months=months, purpose=purpose)
        return
    st.html(CSS)
    status = "DEMO · 真实评论 / 人工演示洞察" if report.demo else "BUSINESS RESEARCH · 真实 YouTube 样本"
    if original_collection is not None:
        status = "历史离线回放 · 真实评论与历史模型响应"
    status = preview_notice or status
    st.html(
        f'<section class="br-hero"><div class="br-kicker">PRODUCT INSIGHT AGENT · {escape(status)}</div>'
        f'<h1>{escape(report.topic)}</h1><p>消费者商业洞察报告</p></section>'
    )
    has_insights = bool(report.summary or report.needs or report.purchase or report.competitors)
    visible = [
        bool(report.summary or report.topics), bool(report.needs), bool(report.purchase),
        bool(report.competitors) or (report.research_layout and has_insights),
        bool(report.opportunities) or (has_insights and not report.demo), True,
    ]
    sections = SECTIONS
    if report.research_layout:
        names = {"purchase": "购买决策因素", "competitors": "产品与竞品讨论",
                 "opportunities": "研究启示与商业机会", "sources": "来源与限制"}
        sections = tuple((anchor, names.get(anchor, title)) for anchor, title in SECTIONS)
    nav = "".join(
        f'<a href="#{anchor}">{title}</a>'
        for (anchor, title), show in zip(sections, visible) if show and (
            anchor != "executive-summary" or report.summary
        )
    )
    if report.topics or report.topic_groups:
        topics_link = '<a href="#consumer-topics">消费者主题</a>'
        if report.summary:
            summary_end = nav.index("</a>") + len("</a>")
            nav = nav[:summary_end] + topics_link + nav[summary_end:]
        else:
            nav = topics_link + nav
    if report.scenarios:
        nav = nav.replace('<a href="#purchase">', '<a href="#scenarios">消费者使用场景</a><a href="#purchase">', 1) if visible[2] else (
            nav.replace('<a href="#sources">', '<a href="#scenarios">消费者使用场景</a><a href="#sources">', 1))
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
    if report.research_layout:
        scope = " · ".join(f"{label} {value}" for value, label in metrics)
        st.html(f'<div class="br-scope">{escape(scope)}</div>')
    else:
        st.html('<div class="br-grid">' + "".join(
            f'<div class="br-metric"><strong>{value}</strong><span>{label}</span></div>'
            for value, label in metrics
        ) + "</div>")
    if not report.demo and not any(visible[:-1]):
        st.info("当前没有通过基本证据检查的洞察。可在技术详情和采集预览查看原因及已获取的评论。")
    if visible[0]:
        if report.summary:
            st.header("研究摘要", anchor="executive-summary")
            cards(report, report.summary, mode="summary")
        if report.topic_groups:
            st.header("消费者主题", anchor="consumer-topics")
            _topic_details(report)
            if len(report.information_types) > 1 and len({s for i in report.information_types for s in i.sources}) >= 4:
                with st.expander("消费者反馈类型分布"):
                    topics_chart(report, report.information_types)
        elif report.topics:
            st.header("消费者主题", anchor="consumer-topics")
            if len(report.topics) > 1 and (report.demo or any(report.mentions(item) > 1 for item in report.topics)):
                topics_chart(report)
            elif report.demo or len(report.topics) > 1:
                cards(report, report.topics)
            else:
                st.caption(f"{report.topics[0].title} · {report.mentions(report.topics[0])} 条评论")
    for (anchor, title), items in zip(
        sections[1:5], (report.needs, report.purchase, report.competitors, report.opportunities)
    ):
        if anchor == "purchase" and report.scenarios:
            st.header("消费者使用场景", anchor="scenarios")
            _section_cards(report, report.scenarios, compact)
        if anchor == "competitors" and report.research_layout and has_insights and not items:
            st.header(title, anchor=anchor)
            st.caption("本轮证据不足以确认具名产品之间的比较。")
        if items:
            st.header(title, anchor=anchor)
            if anchor == "competitors" and not report.demo:
                for label in ("原文产品提及", "原文购买自述", "原文使用自述", "推荐名单咨询", "原文选购候选", "原文对比"):
                    group = tuple(item for item in items if item.badge == label)
                    if group:
                        st.subheader({
                            "原文产品提及": "有品类证据的产品提及",
                            "原文购买自述": "评论者自述已购买",
                            "原文使用自述": "评论者自述用过或正在使用",
                            "推荐名单咨询": "原文推荐名单讨论",
                            "原文选购候选": "评论者正在比较的选购候选",
                            "原文对比": "原文明确比较",
                        }[label])
                        _section_cards(report, group, compact)
                if not any(item.badge == "原文对比" for item in items):
                    st.caption("本轮没有足够证据判断候选型号的性能优劣。")
            else:
                uncategorized = tuple(item for item in items if item.title == "未进一步分类" or
                                      (report.research_layout and item.detail.startswith("原文示例")))
                specific = tuple(item for item in items if item not in uncategorized)
                if anchor == "purchase" and report.demo:
                    purchase_breakdown(report)
                elif specific:
                    if report.research_layout and anchor == "purchase":
                        for title, group in purchase_groups(specific):
                            st.subheader(title)
                            _section_cards(report, group, compact)
                    else:
                        _section_cards(report, specific, compact, mode="research" if anchor == "opportunities" else "detail")
                if uncategorized:
                    with st.expander("其他评论线索"):
                        cards(report, uncategorized)
    if visible[4] and not report.opportunities:
        st.header(sections[4][1], anchor="opportunities")
        st.caption("本轮暂无足够证据支持具体商业机会。")
    st.header(sections[5][1], anchor="sources")
    for limitation in report.limitations:
        st.markdown(f"- {limitation}")
    for source in report.sources:
        st.html(f'<div id="source-{source.label.lower()}"></div>')
        label = "查看 YouTube 原文" if source_links_enabled else "查看合成示例原文"
        with st.expander(f"{source.label} · {label}"):
            if source_links_enabled:
                st.caption(f"{STATUS_LABELS[source.analysis_status]} · {source.published_at}")
            st.text(source.text)
            if source_links_enabled:
                st.link_button("查看 YouTube 来源", source.url)
