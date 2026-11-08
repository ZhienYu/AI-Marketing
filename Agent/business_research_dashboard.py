"""Interactive Phase K renderer. All counts and evidence come from the report view."""

from collections import defaultdict
from html import escape
from inspect import signature
from pathlib import Path
import re

import streamlit as st

from business_research_presentation import purchase_groups, topic_family


ASSETS = Path(__file__).with_name("ui")
SECTION = {
    "executive-summary": ("01", "EXECUTIVE OVERVIEW", "研究摘要", "先看本轮证据最清楚的消费者发现。",
                          "M5 5h14v14H5z M8 9h8 M8 13h8 M8 16h5"),
    "consumer-topics": ("02", "CONSUMER TOPICS", "消费者主题", "选择一个主题，查看子主题、相关洞察及原文。",
                        "M4 19h16 M6 15h4 M6 10h9 M6 5h13"),
    "needs": ("03", "NEEDS & PAIN POINTS", "需求、痛点与偏好", "分开呈现使用问题、明确期待与个人偏好。",
              "M12 20 4 12a4 4 0 0 1 8-3 4 4 0 0 1 8 3z"),
    "scenarios": ("04", "USAGE SCENARIOS", "消费者使用场景", "查看原文明确提到的任务、环境和使用条件。",
                  "M12 21s6-6 6-11a6 6 0 1 0-12 0c0 5 6 11 6 11z M12 8v4"),
    "purchase": ("05", "PURCHASE CONSIDERATIONS", "购买决策因素", "区分预算、报价、成交价及其他选购条件。",
                 "M5 9h14l-1 11H6z M9 9V6a3 3 0 0 1 6 0v3"),
    "competitors": ("06", "PRODUCT DISCUSSIONS", "产品与竞品讨论", "查看产品在评论中的角色和有来源的对照。",
                    "M4 6h6v12H4z M14 6h6v12h-6z M10 12h4"),
    "opportunities": ("07", "RESEARCH IMPLICATIONS", "研究启示与商业机会", "从可追溯的反馈出发，了解下一步值得核实什么。",
                      "M9 17h6 M10 20h4 M9 15c0-2-3-3-3-7a6 6 0 0 1 12 0c0 4-3 5-3 7"),
    "sources": ("08", "SOURCES & LIMITATIONS", "来源与限制", "复核完整原文、对应洞察及样本边界。",
                "M7 3h7l4 4v14H7z M14 3v5h4 M10 12h5 M10 16h5"),
}
SOURCE_MODES = {
    "live": ("真实 YouTube 评论 · Qwen 自动分析", "真实 YouTube 评论"),
    "historical": ("历史真实评论 · 模拟分析", "历史真实 YouTube 评论 · 本次分析为模拟"),
    "synthetic": ("全合成评论 · 模拟分析", "全合成评论 · 模拟分析，无真实 YouTube 来源"),
}
SOURCE_STATUS = {
    "validated": "达到正式属性统计条件",
    "exploratory": "探索性证据 · 自述或归属仍有局限",
    "unverified": "历史样本待核验",
    "raw": "仅原文，尚未进入分析",
}
PRODUCT_ROLES = {
    "原文产品提及": "原文中的产品提及", "原文购买自述": "自述已购买",
    "原文使用自述": "自述用过或正在使用", "推荐名单咨询": "推荐名单讨论",
    "原文选购候选": "选购候选", "原文对比": "原文明确比较",
}
REGIONS = {"canada": "加拿大", "malaysia": "马来西亚", "singapore": "新加坡",
           "united states": "美国", "united kingdom": "英国", "australia": "澳大利亚"}
CURRENCY = r"(?:USD|CAD|AUD|GBP|EUR|MYR|SGD|JPY|CNY|HKD|NZD|RM)"
AMOUNT = r"\d+(?:,\d{3})*(?:\.\d+)?"


def _display_text(text, *, regional=False):
    """Normalize explicit currency codes and known place names for display only."""
    text = re.sub(rf"(?<![\w$€£¥])({AMOUNT})\s*({CURRENCY})\b", r"\2 \1", text, flags=re.I)
    text = re.sub(rf"\b({CURRENCY})\s*({AMOUNT})", lambda m: f"{m[1].upper()} {m[2]}", text, flags=re.I)
    text = re.sub(r"([$€£¥])\s+(?=\d)", r"\1", text)
    text = re.sub(r"(?<=[\u3400-\u9fff]) *[:,;] *", lambda m: {":": "：", ",": "，", ";": "；"}[m[0].strip()], text)
    if regional:
        text = " · ".join(REGIONS.get(part.strip().casefold(), part.strip()) for part in text.split("·"))
    return text


def _refs(labels):
    unique = tuple(dict.fromkeys(labels))
    links = "".join(f'<a class="rd-ref" href="#source-{label.lower()}" data-evidence="{label}" '
                    f'aria-label="查看证据 {label}">{label}</a>' for label in unique)
    if len(unique) > 6:
        links = f'<details class="rd-more"><summary>查看证据编号</summary><div>{links}</div></details>'
    return f'<div class="rd-evidence"><span class="rd-count">{len(unique)} 条评论</span>{links}</div>'


def _cards(items, *, opportunities=False, compact=False):
    if not items:
        return ""
    def card(item):
        detail = _display_text(item.detail, regional=item.title == "地区报价")
        badge = f'<span class="rd-badge">{escape(item.badge)}</span>' if item.badge else ""
        meaning = (f'<p class="rd-kpi"><strong>研究启示</strong> {escape(item.business_meaning)}</p>'
                   if opportunities and item.business_meaning else "")
        if detail.startswith("原文示例"):
            body = "<p>具体描述见关联证据。</p>"
        else:
            prefix = "<strong>建议研究方向</strong> " if opportunities else ""
            body = f"<p>{prefix}{escape(detail)}</p>" if detail else ""
        return f'<article class="rd-card">{badge}<h3>{escape(item.title)}</h3>{meaning}{body}{_refs(item.sources)}</article>'
    limit = 6 if compact else len(items)
    content = '<div class="rd-cards">' + "".join(card(item) for item in items[:limit]) + "</div>"
    if len(items) > limit:
        rest = "".join(card(item) for item in items[limit:])
        content += (f'<details class="rd-more"><summary>其余 {len(items) - limit} 项</summary>'
                    f'<div class="rd-cards">{rest}</div></details>')
    return content


def _section(anchor, content):
    number, english, title, description, path = SECTION[anchor]
    icon = (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>')
    return (f'<section class="rd-section" id="{anchor}" aria-labelledby="{anchor}-title">'
            f'<header class="rd-heading"><span class="rd-icon">{icon}</span><div>'
            f'<div class="rd-eyebrow">{number} / {english}</div><h2 id="{anchor}-title">{title}</h2>'
            f'<p>{description}</p></div></header>{content}</section>')


def _finding_family(item):
    if item.badge in {"原文选购候选", "推荐名单咨询", "原文对比"}:
        return "产品选择与比较"
    return topic_family(item.title)[0]


def _topics(report, findings):
    if not report.topic_groups:
        return _cards(report.topics)
    maximum = max(len(group.parent.sources) for group in report.topic_groups)
    bars, panels = [], []
    for index, group in enumerate(report.topic_groups, 1):
        title = group.parent.title
        count = len(group.parent.sources)
        anchor = f"research-topic-{index}"
        bars.append(f'<a class="rd-topic-bar" href="#{anchor}" data-topic="{anchor}" aria-controls="{anchor}">'
                    f'<strong>{escape(title)}</strong><span class="rd-n">{count}</span>'
                    f'<span class="rd-meter" aria-hidden="true"><span style="width:{100 * count / maximum:.2f}%"></span></span></a>')
        children = "".join(f'<li><strong>{escape(item.title)}</strong>{_refs(item.sources)}</li>' for item in group.children)
        matches = {}
        child_titles = {child.title for child in group.children}
        for item in findings:
            scoped = tuple(ref for ref in item.sources if ref in group.parent.sources)
            if scoped and (_finding_family(item) == title or item.title in child_titles):
                matches[item.title] = tuple(dict.fromkeys(matches.get(item.title, ()) + scoped))
        related = "".join(f'<li>{escape(name)}{_refs(refs)}</li>' for name, refs in matches.items())
        related = f'<details class="rd-more"><summary>对应洞察</summary><ul>{related}</ul></details>' if related else ""
        panels.append(f'<div class="rd-topic-panel" id="{anchor}" data-topic-panel>'
                      f'<h3>{escape(title)} · 子主题</h3><ul>{children}</ul>{related}</div>')
    types = ""
    if len(report.information_types) > 1 and len({s for i in report.information_types for s in i.sources}) >= 4:
        rows = "".join(f'<li>{escape(item.title)}{_refs(item.sources)}</li>' for item in report.information_types)
        types = f'<details class="rd-more"><summary>消费者反馈类型分布</summary><ul>{rows}</ul></details>'
    return ('<div class="rd-topic-layout"><div class="rd-topic-list" aria-label="上层主题分布">'
            + "".join(bars) + '</div><div aria-live="polite">' + "".join(panels) + "</div></div>"
            '<p class="rd-note">按独立评论 ID 计数。上层主题取子主题来源的并集，各组数量不可相加。</p>' + types)


def _sources(report, mode, links_enabled, findings):
    related = defaultdict(dict)
    for anchor, items in findings:
        for item in items:
            for ref in item.sources:
                related[ref].setdefault(item.title, item.badge or SECTION[anchor][2])
    limitations = report.limitations
    if mode != "live":
        scope = ("此页全部为合成评论及模拟分析，无真实消费者、采集视频或 YouTube 来源。"
                 if mode == "synthetic" else "此页回放既有历史原文，分析结果为模拟，仅用于验证报告界面。")
        limitations = (scope, "预览的数量和发现均不代表市场趋势。")
    result = [f"<ul>{''.join(f'<li>{escape(text)}</li>' for text in limitations)}</ul>"]
    for source in report.sources:
        kind = SOURCE_MODES[mode][1]
        status = SOURCE_STATUS[source.analysis_status] if mode == "live" else "仅用于离线预览"
        date = f" · {escape(source.published_at)}" if mode != "synthetic" and source.published_at else ""
        analyses = "".join(f"<li>{escape(title)} · {escape(label)}</li>" for title, label in related[source.label].items())
        analyses = f'<ul class="rd-related">{analyses}</ul>' if analyses else "<p>本来源无单独展示的分析卡片。</p>"
        url = (f'<a href="{escape(source.url)}" target="_blank" rel="noopener noreferrer">在 YouTube 查看原文 ↗</a>'
               if links_enabled and mode != "synthetic" else "")
        result.append(f'<details class="rd-source" id="source-{source.label.lower()}"><summary>{source.label} · 完整原文</summary>'
                      f'<div class="rd-source-body"><p class="rd-source-meta">{kind} · {status}{date}</p>'
                      f'<blockquote class="rd-source-text" lang="und">{escape(source.text)}</blockquote>{url}'
                      f'<h3>对应分析</h3>{analyses}</div></details>')
    return "".join(result)


def dashboard_markup(report, *, mode="live", compact=True, source_links_enabled=True, months=None, purpose=None):
    """Render trusted structure with escaped source and model text."""
    title = SOURCE_MODES[mode][0]
    coverage = report.coverage
    scope = []
    if coverage:
        if mode == "live":
            scope = [(f"采集评论 · {coverage.collected_videos} 个视频", coverage.collected),
                     ("提交分析", coverage.submitted), ("进入定性报告", coverage.qualitative),
                     ("正式属性统计", coverage.formal)]
        else:
            scope = [("合成示例评论" if mode == "synthetic" else "历史原文样本", coverage.collected),
                     ("模拟分析", coverage.submitted), ("展示证据", coverage.qualitative)]
    scope_html = "".join(f'<span>{label} <strong>{count}</strong></span>' for label, count in scope)
    if mode == "live" and months is not None:
        scope_html += f"<span>{escape(purpose or '研究范围')} · 最近 {months} 个月发布的视频</span>"
    headings = (
        ("executive-summary", report.summary), ("needs", report.needs), ("scenarios", report.scenarios),
        ("purchase", report.purchase), ("competitors", report.competitors), ("opportunities", report.opportunities),
    )
    findings = tuple(item for anchor, items in headings if anchor not in {"executive-summary", "opportunities"} for item in items)
    sections = {}
    if report.summary:
        sections["executive-summary"] = _cards(report.summary)
    if report.topic_groups or report.topics:
        sections["consumer-topics"] = _topics(report, findings)
    if report.needs:
        specific = tuple(item for item in report.needs if item.title != "未进一步分类" and not item.detail.startswith("原文示例"))
        other = tuple(item for item in report.needs if item not in specific)
        extra = (f'<details class="rd-more"><summary>其他评论线索</summary>{_cards(other, compact=compact)}</details>'
                 if other else "")
        sections["needs"] = _cards(specific, compact=compact) + extra
    if report.scenarios:
        sections["scenarios"] = _cards(report.scenarios, compact=compact)
    if report.purchase:
        sections["purchase"] = "".join(f'<h3 class="rd-group-title">{title}</h3>{_cards(group, compact=compact)}'
                                       for title, group in purchase_groups(report.purchase))
    if findings or report.competitors:
        products = ""
        for role, label in PRODUCT_ROLES.items():
            group = tuple(item for item in report.competitors if item.badge == role)
            if group:
                products += f'<h3 class="rd-group-title">{label}</h3>' + _cards(group, compact=compact)
        other = tuple(item for item in report.competitors if item.badge not in PRODUCT_ROLES)
        products += _cards(other, compact=compact)
        if not any(item.badge == "原文对比" for item in report.competitors):
            products += '<p class="rd-note">本轮证据不足以判断产品之间的性能优劣。</p>'
        sections["competitors"] = products
    if findings or report.opportunities:
        sections["opportunities"] = (_cards(report.opportunities, opportunities=True, compact=compact)
                                    or '<p class="rd-note">本轮暂无足够证据支持具体商业机会。</p>')
    sections["sources"] = _sources(report, mode, source_links_enabled, headings)
    empty_note = '<p class="rd-note">本轮没有可展示的研究洞察。可在技术详情核对原因。</p>' if len(sections) == 1 else ""
    nav = "".join(f'<a href="#{anchor}" data-section>{SECTION[anchor][2]}</a>' for anchor in sections)
    return (
        '<div class="rd-report"><section class="rd-hero" id="report-top">'
        f'<small>PRODUCT INSIGHT AGENT · {title}</small><h1>{escape(report.topic)}</h1><p>消费者商业研究报告</p></section>'
        f'<div class="rd-scope">{scope_html}</div><nav class="rd-nav" aria-label="报告章节"><div class="rd-nav-links">{nav}</div>'
        '<a class="rd-top" href="#report-top" aria-label="返回顶部">↑ <span>返回顶部</span></a></nav>'
        + empty_note + "".join(_section(anchor, body) for anchor, body in sections.items())
        + '<dialog class="rd-dialog" aria-labelledby="research-evidence-title"><div class="rd-dialog-top">'
          '<h2 id="research-evidence-title">证据详情</h2><button type="button" autofocus>关闭</button></div>'
          '<div data-dialog-content></div></dialog></div>'
    )


def render_dashboard(report, **options):
    markup = (ASSETS / "research_dashboard.css").read_text(encoding="utf-8") + dashboard_markup(report, **options)
    if "unsafe_allow_javascript" in signature(st.html).parameters:
        # Only the checked-in static script executes. Source and model text are escaped.
        script = (ASSETS / "research_dashboard.js").read_text(encoding="utf-8")
        st.html(markup + f"<script>{script}</script>", unsafe_allow_javascript=True)
    else:
        st.html(markup)
