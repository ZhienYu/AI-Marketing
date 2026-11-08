"""Evidence-linked synthesis for the Phase K report, with no model requests."""

from collections import defaultdict
from dataclasses import replace
import re

from business_report_view import ReportItem, ReportTopic


FAMILIES = {
    "价格与购买成本": ("价格与预算", "明确预算上限", "简单询价", "地区报价", "购买成交价", "价格评价",
                    "当地价格比较", "规格与报价评价", "滤芯获取与费用", "电池老化后的维修与换新"),
    "佩戴与舒适度": ("佩戴与人体工学", "佩戴舒适度", "佩戴贴合感", "密封不合适后退货", "长时间佩戴"),
    "音频与连接": ("声音与通话", "连接与软件体验", "听音乐时断音", "通话质量反馈", "音质与降噪"),
    "续航与电池": ("续航与充电", "电池健康度", "全天续航标准", "希望电池容量更大", "希望充电更快", "希望更大电池和更快充电"),
    "功能与使用条件": ("无需额外 App 的产品偏好", "适用面积", "运行噪声", "选购前想知道哪款更安静", "臭氧释放要求", "预算内除尘",
                    "除尘需求", "清洁效果", "希望找到除尘能力更强的型号", "功能使用条件", "适用性与兼容性"),
    "产品选择与比较": ("型号选择", "型号选择与比较", "型号选择咨询", "个人使用比较", "宣传可信度"),
    "可靠性与维护": ("可靠性与维护", "使用寿命与耐用性", "维修与售后成本"),
}
FAMILY_BY_TOPIC = {topic: family for family, topics in FAMILIES.items() for topic in topics}
COST_COMPARISON = re.compile(r"\b(?:more expensive|less expensive|cheaper|not even close to the cheapest|overpriced)\b|更贵|更便宜", re.I)
LOCAL_MARKET = re.compile(r"\b(?:where i live|in my area|locally|in my country)\b|当地|本地", re.I)


def topic_family(title):
    if title.startswith("使用功能前是否需要"):
        return "功能与使用条件", "订阅与协议疑问"
    return FAMILY_BY_TOPIC.get(title, title), title


def describe_evidence(topic, badge, quote):
    """Translate only explicit signals in the already-cited excerpt."""
    if topic == "价格与预算":
        if badge == "选购咨询" and re.fullmatch(r"\s*(?:price|how much|多少钱|什么价位)[?？!\s]*", quote, re.I):
            return "简单询价", "评论者只询问售价。"
        if badge == "选购评价" and COST_COMPARISON.search(quote) and LOCAL_MARKET.search(quote):
            return "当地价格比较", "评论者比较了当地售价。原文只代表其所在市场的观察。"
        if badge == "选购评价" and re.search(r"\b(?:reasonably priced|good value|worth the price|too expensive|overpriced)\b", quote, re.I):
            return "价格评价", "评论者评价了售价或性价比。"
    if topic == "运行噪声" and badge == "选购咨询" and re.search(r"\b(?:quietest|most quiet|least noisy)\b", quote, re.I):
        return "选购前想知道哪款更安静", "评论者询问哪个型号运行时最安静，未提供实测噪声。"
    if topic == "佩戴与人体工学" and badge.startswith(("使用自述", "使用场景线索")):
        if re.search(r"\b(?:i|we) (?:wear|wore) (?:them|these|the earbuds|my earbuds) (?:all day|for hours)\b", quote, re.I):
            return "长时间佩戴", "评论者自述会全天或连续数小时佩戴。"
    if topic == "续航与充电":
        if badge == "一般偏好" and re.search(r"\b(?:through|lasts?) (?:you )?(?:a |the )?full day\b", quote, re.I):
            return "全天续航标准", "评论者把撑过一整天作为评价电池的标准。"
        if badge == "明确需求":
            if re.search(r"\b(?:larger|bigger) batter(?:y|ies)\b|大容量电池", quote, re.I):
                if re.search(r"\bfaster charging\b|更快充电", quote, re.I):
                    return "希望更大电池和更快充电", "评论者同时提出增加电池容量和加快充电。"
                return "希望电池容量更大", "评论者明确希望增加电池容量。"
            if re.search(r"\bfaster charging\b|更快充电", quote, re.I):
                return "希望充电更快", "评论者明确希望缩短充电时间。"
    return None


def _items_by_source(items):
    return tuple(dict.fromkeys(ref for item in items for ref in item.sources))


def _topic_groups(topics):
    by_family = defaultdict(lambda: defaultdict(set))
    for item in topics:
        family, child = topic_family(item.title)
        by_family[family][child].update(item.sources)
    groups = []
    for family, children in by_family.items():
        child_items = tuple(ReportItem(title, "", tuple(sorted(refs))) for title, refs in
                            sorted(children.items(), key=lambda pair: (-len(pair[1]), pair[0])))
        sources = _items_by_source(child_items)
        groups.append(ReportTopic(ReportItem(family, "", sources), child_items))
    return tuple(sorted(groups, key=lambda group: (-len(group.parent.sources), group.parent.title)))


def _consumer_type(item):
    if item.title in {"听音乐时断音", "佩戴贴合感", "密封不合适后退货"} and ("自述" in item.badge):
        return "亲身使用问题"
    if "转述" in item.badge:
        return "第三方转述"
    if "明确" in item.badge and ("需求" in item.badge or "期待" in item.badge):
        return "明确需求"
    if "正面产品偏好" in item.badge:
        return "正面偏好"
    if "选购咨询" in item.badge or item.badge == "原文选购候选":
        return "购买咨询"
    if item.badge.startswith("一般"):
        return "一般观点"
    if "评价" in item.badge and "产品" in item.badge:
        return "产品评价"
    return None


def _scenarios(needs, purchase, competitors):
    # Scenario and issue must come from the same report finding or matched
    # source, never from two unrelated comments in the same broad topic.
    scenarios = []
    tasks = {
        "连接手机听歌": ("连接手机听歌", "用途自述", None),
        "听音乐时断音": ("听音乐", "该场景下的问题", "场景关联的问题是播放中断。"),
        "通话质量反馈": ("通话", "转述的通话反馈", "通话质量由评论者转述，保留为他人反馈。"),
        "适用面积": ("按房间大小选购", "计划使用条件", None),
        "长时间佩戴": ("长时间佩戴", "用途自述", None),
    }
    for item in (*needs, *purchase):
        if item.title in tasks:
            title, badge, detail = tasks[item.title]
            scenarios.append(replace(item, title=title, badge=badge, detail=detail or item.detail, business_meaning=""))
        elif item.title == "预算内除尘" and "桌面" in item.detail:
            scenarios.append(replace(item, title="减少桌面设备积灰", badge="计划使用目的", business_meaning=""))
    for item in competitors:
        if item.badge == "原文购买自述" and (room := re.search(r"只放在(卧室|客厅|办公室)", item.detail)):
            scenarios.append(replace(item, title=room[1], badge="自述使用环境", business_meaning=""))
    return _merge(scenarios)


def _merge(items):
    found = {}
    for item in items:
        key = (item.title, item.detail, item.badge, item.business_meaning)
        prior = found.get(key)
        found[key] = item if prior is None else replace(prior, sources=_items_by_source((prior, item)))
    return tuple(sorted(found.values(), key=lambda item: -len(item.sources)))


RESEARCH = (
    ("核实听音乐时的连接稳定性", ("听音乐时断音",),
     "评论中的断音有明确的听歌场景，可用于界定复现范围。",
     "对照播放设备、连接条件和操作步骤复现。原文无法确认原因或发生率。"),
    ("试戴体验与贴合信息", ("佩戴贴合感", "密封不合适后退货"),
     "这些评论描述了佩戴适配问题，可以用来设计试戴测试。",
     "比较试戴提示和耳塞尺寸选择是否有助于判断适配。当前样本无法估计退货率。"),
    ("说清功能使用条件", ("功能使用条件",),
     "评论者询问使用功能需要满足哪些条件。",
     "先核对原文涉及的订阅或协议，再验证选购页能否解释清楚。咨询本身不能证明需要付费。"),
    ("区分售价与后续使用成本", ("滤芯获取与费用", "电池老化后的维修与换新"),
     "相关评论提到了使用一段时间后仍可能发生的支出。",
     "分别核对整机售价、适用耗材或维修选项，再了解这些信息如何影响选购。实际费用和接受范围仍待核实。"),
)


def _opportunities(findings, existing):
    items, used_titles = [], set()
    equivalent = {"试戴能否提前发现密封问题？", "功能要付费吗？",
                  "买家会怎样权衡换电池和换新？", "在选购页并列整机与替换滤芯费用"}
    for title, signals, meaning, action in RESEARCH:
        sources = _items_by_source(item for item in findings if item.title in signals
                                   or (item.title.startswith("使用功能前是否需要") and "功能使用条件" in signals))
        if sources:
            badge = "多条评论支持 · 待验证" if len(sources) > 1 else "单条来源 · 探索性机会"
            items.append(ReportItem(title, action, sources, badge, meaning))
            used_titles.add(title)
    items.extend(item for item in existing if item.title not in used_titles | equivalent)
    return _merge(items)[:6]


def _summary(findings, sources):
    validated = {source.label for source in sources if source.analysis_status == "validated"}
    eligible = [item for item in findings if item.detail and not item.detail.startswith(
        ("原文示例", "展开来源", "请查看来源")) and "未进一步分类" not in item.title
        and "提及，角色未确认" not in item.detail]
    def score(item):
        quality = 2 if set(item.sources) & validated else 0
        decision = 3 if _consumer_type(item) in {"亲身使用问题", "明确需求", "购买咨询", "正面偏好"} else 0
        specificity = 2 if item.title not in FAMILY_BY_TOPIC or item.title.startswith("使用功能前") else 0
        return quality + decision + specificity + min(len(item.sources), 3)
    ranked = sorted(eligible, key=score, reverse=True)
    selected, families = [], set()
    # Reserve one place for a supported recurring finding when available, then
    # retain concrete one-off findings without repeating a topic or a source.
    first = next((item for item in ranked if len(item.sources) > 1), None)
    ordered = [first] + ranked if first else ranked
    for item in ordered:
        family, _ = topic_family(item.title)
        if (family in families or item in selected
                or any(set(item.sources) == set(other.sources) for other in selected)):
            continue
        families.add(family)
        selected.append(item)
        if len(selected) == 4:
            break
    summary = []
    for item in selected:
        detail = item.detail
        if item.title == "听音乐时断音":
            detail = ("多条评论自述在听音乐时遇到声音中断。" if len(item.sources) > 1
                      else "有评论者自述在听音乐时遇到声音中断。")
        elif item.title.startswith("使用功能前是否需要"):
            detail = "原文提出的是功能使用条件的疑问，尚无法确认实际要求。"
        summary.append(replace(item, detail=detail, business_meaning=""))
    return tuple(summary)


def upgrade_phase_k(report, topics):
    roles = {"当前使用": ("原文使用自述", "评论者明确说正在使用该产品。"),
             "本人使用过": ("原文使用自述", "评论者明确说用过该产品。"),
             "已购买": ("原文购买自述", "评论者自述已购买该产品。")}
    competitors = []
    for item in report.competitors:
        if item.badge == "原文产品提及" and item.detail in roles:
            badge, detail = roles[item.detail]
            item = replace(item, detail=detail, badge=badge)
        competitors.append(item)
    competitors = tuple(competitors)
    findings = (*report.needs, *report.purchase, *competitors)
    explicit_relations = tuple(
        replace(item, title=f"{item.title} · 候选对照", badge="选购咨询")
        for item in competitors if item.badge == "原文选购候选" and "候选报价分别为" in item.detail
    )
    types = defaultdict(set)
    for item in findings:
        if label := _consumer_type(item):
            types[label].update(item.sources)
    scenarios = _scenarios(report.needs, report.purchase, competitors)
    purchase = tuple(item for item in report.purchase if item.title != "连接手机听歌")
    opportunities = _opportunities(findings, report.opportunities)
    # Preserve coverage and sources. Some source links used by the legacy
    # opportunities can also be reached from the evidence section directly.
    return replace(report, research_layout=True, summary=_summary(findings, report.sources),
                   purchase=purchase + explicit_relations, competitors=competitors, opportunities=opportunities, scenarios=scenarios,
                   topic_groups=_topic_groups(topics), information_types=tuple(
                       ReportItem(label, "", tuple(sorted(refs))) for label, refs in
                       sorted(types.items(), key=lambda pair: (-len(pair[1]), pair[0]))))


def purchase_groups(items):
    groups = defaultdict(list)
    categories = ("预算与询价", "报价、成交价与价值判断", "使用条件与后续费用", "候选与其他选购因素")
    for item in items:
        if item.title in {"明确预算上限", "简单询价"}:
            index = 0
        elif item.title in {"地区报价", "购买成交价", "当地价格比较", "价格评价", "规格与报价评价"}:
            index = 1
        elif item.title.startswith("使用功能前是否需要") or item.title in {"滤芯获取与费用", "适用面积", "臭氧释放要求"}:
            index = 2
        else:
            index = 3
        groups[categories[index]].append(item)
    return tuple((title, groups[title]) for title in categories if groups[title])
