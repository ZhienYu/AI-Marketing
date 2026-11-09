"""Interactive Phase K renderer. All counts and evidence come from the report view."""

from collections import Counter, defaultdict
from html import escape
from inspect import signature
from pathlib import Path
import re
from urllib.parse import quote

import streamlit as st

from business_research_presentation import purchase_groups, topic_family


ASSETS = Path(__file__).with_name("ui")
SECTION = {
    "executive-summary": ("01", "EXECUTIVE OVERVIEW", "研究摘要", "先看本轮证据最清楚的消费者发现。",
                          "M5 5h14v14H5z M8 9h8 M8 13h8 M8 16h5"),
    "consumer-topics": ("02", "CONSUMER TOPICS", "消费者主题", "选择主题，再从子主题跳到具体发现或查看原文。",
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
PRICE_MARK = rf"(?:{CURRENCY}|[€£$¥])"
PRICE_TOKEN = re.compile(rf"(?:{PRICE_MARK}\s*{AMOUNT}|{AMOUNT}\s*{PRICE_MARK}|{AMOUNT})", re.I)


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


def _cards(items, *, targets=None, opportunities=False, compact=False):
    if not items:
        return ""
    def card(item):
        detail = _display_text(item.detail, regional=item.title == "地区报价")
        tone = "neutral"
        if any(word in item.badge for word in ("探索性", "待验证", "转述", "待复核", "未确认")):
            tone = "caution"
        elif any(word in item.badge for word in ("正面", "明确需求", "正式统计")):
            tone = "positive"
        elif any(word in item.badge for word in ("咨询", "候选", "对比")):
            tone = "decision"
        badge = (f'<span class="rd-badge rd-badge-{tone}">{escape(item.badge)}</span>'
                 if item.badge else "")
        if opportunities:
            fields = (("消费者反馈", item.observation), ("商业意义", item.business_meaning),
                      ("建议下一步", detail), ("证据限制", item.evidence_limit or "这是待验证的研究方向。"))
            body = "".join(f'<p class="rd-opportunity-field"><strong>{label}</strong> {escape(value)}</p>'
                           for label, value in fields if value)
        else:
            body = f"<p>{escape(detail)}</p>" if detail else ""
        anchor = f' id="{targets[item]}" tabindex="-1"' if targets and item in targets else ""
        return f'<article class="rd-card"{anchor}>{badge}<h3>{escape(item.title)}</h3>{body}{_refs(item.sources)}</article>'
    items = tuple(dict.fromkeys(items))
    limit = 6 if compact else len(items)
    content = '<div class="rd-cards">' + "".join(card(item) for item in items[:limit]) + "</div>"
    if len(items) > limit:
        rest = "".join(card(item) for item in items[limit:])
        content += (f'<details class="rd-more"><summary>其余 {len(items) - limit} 项</summary>'
                    f'<div class="rd-cards">{rest}</div></details>')
    return content


def _section(anchor, content):
    number, english, title, description, path = SECTION[anchor]
    # The HTML sanitizer strips SVG elements. Use trusted, decorative CSS masks.
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="none" '
           f'stroke="black" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" d="{path}"/></svg>')
    icon = f'<span class="rd-icon" aria-hidden="true" style="--rd-icon:url(data:image/svg+xml,{quote(svg, safe="")})"></span>'
    return (f'<section class="rd-section" id="{anchor}" aria-labelledby="{anchor}-title">'
            f'<header class="rd-heading">{icon}<div>'
            f'<div class="rd-eyebrow">{number} / {english}</div><h2 id="{anchor}-title">{title}</h2>'
            f'<p>{description}</p></div></header>{content}</section>')


def _topics(report, findings):
    if not report.topic_groups:
        return _cards(report.topics)
    maximum = max(len(group.parent.sources) for group in report.topic_groups)
    bars, panels = [], []
    by_title = defaultdict(list)
    for item, target in findings:
        by_title[topic_family(item.title)[1]].append((item, target))
    for index, group in enumerate(report.topic_groups, 1):
        title = group.parent.title
        count = len(group.parent.sources)
        anchor = f"research-topic-{index}"
        bars.append(f'<a class="rd-topic-bar" href="#{anchor}" data-topic="{anchor}" aria-controls="{anchor}">'
                    f'<strong>{escape(title)}</strong><span class="rd-n">{count}</span>'
                    f'<span class="rd-meter" aria-hidden="true"><span style="width:{100 * count / maximum:.2f}%"></span></span></a>')
        children = []
        for child in group.children:
            refs = set(child.sources)
            matches = [(len(refs.intersection(item.sources)), target)
                       for item, target in by_title[child.title]]
            overlap, target = max(matches, key=lambda match: match[0], default=(0, ""))
            label = escape(child.title)
            title_link = (f'<a class="rd-finding-link" href="#{target}" data-finding>{label} <span aria-hidden="true">↗</span></a>'
                          if overlap else f'<strong>{label}</strong>')
            children.append(f'<li>{title_link}{_refs(child.sources)}</li>')
        panels.append(f'<div class="rd-topic-panel" id="{anchor}" data-topic-panel>'
                      f'<h3>{escape(title)} · 子主题</h3><ul>{"".join(children)}</ul></div>')
    types = ""
    if len(report.information_types) > 1 and len({s for i in report.information_types for s in i.sources}) >= 4:
        rows = "".join(f'<li>{escape(item.title)}{_refs(item.sources)}</li>' for item in report.information_types)
        types = f'<details class="rd-more"><summary>消费者反馈类型分布</summary><ul>{rows}</ul></details>'
    return ('<div class="rd-topic-layout"><div class="rd-topic-list" aria-label="上层主题分布">'
            + "".join(bars) + '</div><div aria-live="polite">' + "".join(panels) + "</div></div>"
            '<p class="rd-note">按独立评论 ID 计数。上层主题取子主题来源的并集，各组数量不可相加。</p>' + types)


def _sources(report, mode, links_enabled, headings, targets):
    related = defaultdict(dict)
    for anchor, items in sorted(headings, key=lambda section: section[0] == "executive-summary"):
        for item in items:
            for ref in item.sources:
                key = (item.title, item.badge or SECTION[anchor][2])
                related[ref].setdefault(key, targets.get(anchor, {}).get(item))
    limitations = report.limitations
    if mode != "live":
        scope = ("此页全部为合成评论及模拟分析，无真实消费者、采集视频或 YouTube 来源。"
                 if mode == "synthetic" else "此页回放既有历史原文，分析结果为模拟，仅用于验证报告界面。")
        limitations = (scope, "预览的数量和发现均不代表市场趋势。")
    labels = (
        ("单条来源", "一条去重评论支持。"),
        ("多条评论支持", "多条去重评论支持，仍需验证，不能据此判断市场普遍性。"),
        ("探索性", "可用于提出研究问题，适用范围仍待核实。"),
        ("选购咨询", "原文提出问题，未据此确认购买或使用。"),
        ("使用自述", "评论者描述自己的使用体验，尚未独立核实。"),
    )
    definitions = "".join(f"<li><strong>{label}</strong>　{detail}</li>" for label, detail in labels)
    result = [f"<ul>{''.join(f'<li>{escape(text)}</li>' for text in limitations)}</ul>",
              f'<details class="rd-more"><summary>证据标签说明</summary><ul>{definitions}</ul></details>']
    for source in report.sources:
        kind = SOURCE_MODES[mode][1]
        status = SOURCE_STATUS[source.analysis_status] if mode == "live" else "仅用于离线预览"
        date = f" · {escape(source.published_at)}" if mode != "synthetic" and source.published_at else ""
        analyses = []
        for (title, label), target in related[source.label].items():
            title = escape(title)
            if target:
                title = f'<a href="#{target}" data-finding>{title}</a>'
            analyses.append(f"<li>{title} · {escape(label)}</li>")
        analyses = "".join(analyses)
        analyses = f'<ul class="rd-related">{analyses}</ul>' if analyses else "<p>本来源无单独展示的分析卡片。</p>"
        url = (f'<a href="{escape(source.url)}" target="_blank" rel="noopener noreferrer">在 YouTube 查看原文 ↗</a>'
               if links_enabled and mode != "synthetic" else "")
        result.append(f'<details class="rd-source" id="source-{source.label.lower()}"><summary>{source.label} · 完整原文</summary>'
                      f'<div class="rd-source-body"><p class="rd-source-meta">{kind} · {status}{date}</p>'
                      f'<blockquote class="rd-source-text" lang="und">{escape(source.text)}</blockquote>{url}'
                      f'<h3>对应分析</h3>{analyses}</div></details>')
    return "".join(result)



def _executive(report, mode, targets):
    findings = report.summary
    references = Counter(ref for item in findings for ref in dict.fromkeys(item.sources))
    singles = sum(len(set(item.sources)) == 1 for item in findings)
    shared = [f"{ref} 支持 {count} 条观察，按一条评论计。"
              for ref, count in references.items() if count > 1]
    comment_label = {"live": "引用的去重评论", "historical": "引用的历史评论",
                     "synthetic": "引用的合成评论"}[mode]
    counts = [(comment_label, len(references)), ("观察数", len(findings))]
    if mode != "synthetic":
        videos = {source.video_id for source in report.sources if source.label in references}
        counts.append(("引用评论来自的视频", len(videos)))
    counts.append(("获多条评论支持的观察", len(findings) - singles))
    metrics = ('<div class="rd-metrics" aria-label="观察证据覆盖">'
               + "".join(f'<span>{label} <strong>{count}</strong></span>' for label, count in counts) + '</div>')
    limits = {
        "live": "公开评论样本不能代表市场整体，自述未经独立核实。",
        "historical": "历史原文配模拟分析，仅供演示。",
        "synthetic": "评论与分析均为合成示例。",
    }
    notes = shared
    if singles * 2 > len(findings):
        notes.append("多数观察只有一条评论支持。")
    if mode != "synthetic" and len(videos) < len(references):
        notes.append("同一视频中的评论共享讨论背景。")
    notes.append(limits[mode])
    evidence = f'<p class="rd-overview-note"><strong>证据说明</strong> {escape("".join(notes))}</p>'
    rows = []
    for item in findings:
        anchor = targets["executive-summary"][item]
        meaning = (f'<p class="rd-summary-meaning"><strong>对企业的启示</strong> {escape(item.business_meaning)}</p>'
                   if item.business_meaning else "")
        rows.append(f'<li id="{anchor}" tabindex="-1"><h3>{escape(item.title)}</h3>'
                    f'<p>{escape(item.detail)}</p>{meaning}{_refs(item.sources)}</li>')
    conclusions = ('<h3 class="rd-overview-label">本轮观察</h3><ol class="rd-conclusions">'
                   + "".join(rows) + "</ol>" if rows else '<p class="rd-note">现有证据不足以提炼观察。</p>')
    questions = []
    for item in report.opportunities[:3]:
        title = "买家能否在下单前看清功能使用条件？" if item.title == "说清功能使用条件" else item.title
        questions.append(f'<li><a href="#{targets["opportunities"][item]}" data-finding>{escape(title)}</a></li>')
    follow_up = ('<h3 class="rd-overview-label">值得进一步关注</h3><ul class="rd-questions">'
                 + "".join(questions) + "</ul>" if questions else "")
    return metrics + evidence + conclusions + follow_up


def _price_rows(items, sources):
    """Project only explicit amounts from already supported purchase items."""
    source_text = {source.label: " ".join(source.text.casefold().split()) for source in sources}
    records, covered = defaultdict(dict), set()
    for item in items:
        detail = item.detail
        region = ""
        if item.title == "明确预算上限":
            amount = detail.removeprefix("评论者明确表示最多支出 ").removesuffix("（原文金额）。")
            amounts = [("个人选购", amount)]
            kind = "个人预算"
        elif item.title in {"地区报价", "购买成交价"}:
            parts = detail.split("。金额来自评论", 1)[0].split(" · ")
            if len(parts) != (3 if item.title == "地区报价" else 2):
                continue
            name, *place, amount = parts
            region = place[0] if place else ""
            amounts = [(name, amount)]
            kind = "地区报价" if place else "实际成交价（自述）"
        elif item.title.endswith(" · 候选对照"):
            names = item.title.removesuffix(" · 候选对照").split(" / ")
            values = detail.removeprefix("评论者列出的候选报价分别为 ").split("。", 1)[0].split(" / ")
            if len(names) != 2 or len(values) != 2:
                continue
            amounts = list(zip(names, values))
            kind = "候选报价"
        else:
            continue
        rows = []
        for name, amount in amounts:
            amount = amount.removesuffix(".")
            if not PRICE_TOKEN.fullmatch(amount):
                continue
            literal = " ".join(amount.casefold().split())
            marker = re.search(PRICE_MARK, amount, re.I)
            code = marker[0].upper() if marker else ""
            currency = {"€": "EUR", "£": "GBP", "RM": "MYR", "$": "未注明（$）", "¥": "未注明（¥）"}.get(
                code, code or "未注明")
            # A numeric substring inside another amount is not a matching quote.
            pattern = re.compile(rf"(?<![\w\d.,]){re.escape(literal)}(?!\w|[.,]\d)")
            refs = tuple(ref for ref in item.sources if pattern.search(source_text[ref]))
            if refs:
                rows.append(((name, amount, currency, kind, region or "未注明"), refs))
        for key, refs in rows:
            records[key].update(dict.fromkeys(refs))
        if len(rows) == len(amounts) and all(set(refs) == set(item.sources) for _, refs in rows):
            covered.add(item)
    return tuple((*key, tuple(refs)) for key, refs in records.items()), covered


def _price_table(rows):
    header = ("产品或对象", "原文金额", "币种", "价格类型", "地区", "证据")
    columns = "".join(f'<th scope="col">{label}</th>' for label in header)
    body = []
    for *cells, refs in rows:
        values = "".join(f"<td>{escape(value)}</td>" for value in cells)
        body.append(f"<tr>{values}<td>{_refs(refs)}</td></tr>")
    return ('<h3 class="rd-group-title">评论中的价格对照</h3>'
            '<p class="rd-note">并列展示原文金额。不同地区、时间及交易条件可能不可比。</p>'
            '<div class="rd-price-wrap" tabindex="0" role="region" aria-label="价格对照，可横向滚动">'
            f'<table class="rd-prices"><thead><tr>{columns}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def dashboard_markup(report, *, mode="live", compact=True, source_links_enabled=True, months=None, purpose=None):
    """Render trusted structure with escaped source and model text."""
    title = SOURCE_MODES[mode][0]
    coverage = report.coverage
    banner_note = {"live": "公开评论样本，供定性研究参考", "historical": "历史原文样本 · 模拟分析",
                   "synthetic": "合成示例 · 模拟分析"}[mode]
    if coverage and mode == "live":
        banner_note += f" · 采集 {coverage.collected} 条 / {coverage.collected_videos} 个视频"
        banner_note += f" · 提交分析 {coverage.submitted} 条 · 正式属性统计 {coverage.formal} 条"
    elif coverage:
        banner_note += f" · 预览输入 {coverage.collected} 条"
    if mode == "live" and months is not None:
        banner_note += f" · {purpose or '研究范围'} · 最近 {months} 个月发布的视频"
    headings = (
        ("executive-summary", report.summary), ("needs", report.needs), ("scenarios", report.scenarios),
        ("purchase", report.purchase), ("competitors", report.competitors), ("opportunities", report.opportunities),
    )
    specific = tuple(item for item in report.needs if item.detail and item.title != "未进一步分类"
                     and not item.detail.startswith(("原文示例", "展开来源", "具体描述见")))
    clues = tuple(item for item in report.needs if item not in specific)
    targets = {anchor: {item: f"finding-{anchor}-{i}" for i, item in enumerate(dict.fromkeys(items), 1)}
               for anchor, items in headings if anchor != "needs"}
    targets["needs"] = {item: f"finding-needs-{i}" for i, item in enumerate(dict.fromkeys(specific), 1)}
    findings = tuple(pair for anchor in ("needs", "purchase", "competitors", "scenarios")
                     for pair in targets[anchor].items())
    sections = {}
    sections["executive-summary"] = _executive(report, mode, targets)
    if report.topic_groups or report.topics:
        sections["consumer-topics"] = _topics(report, findings)
    if report.needs:
        rows = []
        for item in clues:
            excerpt = (item.detail.removeprefix("原文示例").strip()
                       if item.detail.startswith("原文示例") else "")
            quote_text = f'<p lang="und">{escape(excerpt)}</p>' if excerpt else ""
            rows.append(f'<li><strong>{escape(item.title)}</strong>{quote_text}{_refs(item.sources)}</li>')
        extra = (f'<details class="rd-more"><summary>原文线索 · {len(rows)} 项</summary>'
                 f'<ul class="rd-clues">{"".join(rows)}</ul></details>' if rows else "")
        sections["needs"] = _cards(specific, targets=targets["needs"], compact=compact) + extra
    if report.scenarios:
        sections["scenarios"] = _cards(report.scenarios, targets=targets["scenarios"], compact=compact)
    if report.purchase:
        rows, covered = _price_rows(report.purchase, report.sources)
        if len(rows) < 3:
            covered = set()
        visible = tuple(item for item in report.purchase if item not in covered)
        prices = _price_table(rows) if len(rows) >= 3 else ""
        if covered:
            details = tuple(item for item in report.purchase if item in covered)
            prices += ('<details class="rd-more"><summary>展开价格条目说明</summary>'
                      + _cards(details, targets=targets["purchase"], compact=compact) + "</details>")
        sections["purchase"] = prices + "".join(
            f'<h3 class="rd-group-title">{title}</h3>' + _cards(group, targets=targets["purchase"], compact=compact)
            for title, group in purchase_groups(visible)
        )
    if report.competitors:
        products = ""
        for role, label in PRODUCT_ROLES.items():
            group = tuple(item for item in report.competitors if item.badge == role)
            if group:
                products += f'<h3 class="rd-group-title">{label}</h3>' + _cards(group, targets=targets["competitors"], compact=compact)
        other = tuple(item for item in report.competitors if item.badge not in PRODUCT_ROLES)
        products += _cards(other, targets=targets["competitors"], compact=compact)
        if not any(item.badge == "原文对比" for item in report.competitors):
            products += '<p class="rd-note">本轮证据不足以判断产品之间的性能优劣。</p>'
        sections["competitors"] = products
    if report.opportunities:
        legend = ('<p class="rd-note rd-opportunity-legend">单条来源是探索性线索。多条评论支持表示样本中有重复反馈，'
                  '仍需验证，且不代表市场普遍性。</p>')
        sections["opportunities"] = legend + _cards(report.opportunities, targets=targets["opportunities"],
                                                     opportunities=True, compact=compact)
    sections["sources"] = _sources(report, mode, source_links_enabled, headings, targets)
    nav = "".join(f'<a href="#{anchor}" data-section>{SECTION[anchor][2]}</a>' for anchor in sections)
    return (
        '<div class="rd-report"><section class="rd-hero" id="report-top">'
        f'<small>PRODUCT INSIGHT AGENT · {title}</small><h1>{escape(report.topic)}</h1><p>消费者商业研究报告</p><div class="rd-hero-scope">{escape(banner_note)}</div></section>'
        f'<nav class="rd-nav" aria-label="报告章节"><span class="rd-nav-hint">左右滑动查看章节 ↔</span><div class="rd-nav-links">{nav}</div>'
        '<a class="rd-top" href="#report-top" aria-label="返回顶部">↑ <span>返回顶部</span></a></nav>'
        + "".join(_section(anchor, body) for anchor, body in sections.items())
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
