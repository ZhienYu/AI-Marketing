"""Map checked batch results to the visual report without further model calls."""

from collections import Counter, defaultdict
from dataclasses import replace
import re

from business_purchase_signals import CONSUMABLE_COST, purchase_choice, purchase_constraints
from business_evidence_cards import REPLACES, RESEARCH, observation_card
from business_research_presentation import describe_evidence, upgrade_phase_k
from business_report_view import BusinessReportView, CommentSource, ReportCoverage, ReportItem
from commercial_insights import competitor_evidence
from multi_comment_research import (
    CONTENT_OR_IMAGINED, GENERAL_TOPICS, LINK, MEDIA_ONLY, PROMOTION, TOPICS, VIDEO_LINK,
    evidence_spans, group_themes, supports_purchase_inquiry,
)
from report_evidence import GENERAL_COMPLAINT, MONEY, independent_claims, literal_claims
from research_focus import FACETS, focus_for, matching_focus, research_axes


SECTIONS = {"needs": "明确需求", "experience": "产品反馈", "preferences": "一般偏好"}
UNCATEGORIZED = GENERAL_TOPICS | {"产品评价与观察", "未进一步分类"}
MARKETING_TRUST = re.compile(
    r"\b(?:marketing|advertis\w*|hype|influencers?|promotional claims?)\b"
    r"(?=.{0,120}\b(?:mislead\w*|exaggerat\w*|overpriced|sound (?:good|great|better)|instead of|rather than)\b)"
    r"|(?:营销|宣传).{0,24}(?:夸大|误导|不可信|噱头)", re.I | re.S,
)
ROOM_SIZE = re.compile(r"\b(?:sq\.?\s*ft|square (?:feet|foot|meters?|metres?)|room size)\b|房间面积", re.I)
ACCESSORY_COST = re.compile(r"\b(?:costs?|costing|price[ds]?|priced|paid)\b|价格|费用", re.I)
CHOICE_REQUEST = re.compile(r"\b(?:can|could) you (?:please )?(?:suggest|recommend)\b", re.I)
CONTEXT_OBJECT = re.compile(r"\b(?:near|beside|next to|plugged into|attached to|on top of) (?:my |the |an? )?$", re.I)


def _category_pattern(query, focus):
    category = query
    for facet in focus:
        category = re.sub(FACETS[facet][0], " ", category, flags=re.I)
    words = re.findall(r"[^\W_]+", category.casefold())
    if not words:
        return None
    head = words[-1]
    if head in {"phone", "smartphone"}:
        return re.compile(r"\b(?:smart)?phones?\b", re.I)
    modifier = r"(?:" + re.escape(words[-2]) + r"\s+)?" if len(words) > 1 else ""
    return re.compile(r"(?<!\w)" + modifier + re.escape(head.rstrip("s")) + r"s?(?!\w)", re.I)


def _meaning(topic):
    # Present evidence-bound decision lenses. Unknown topics may have no safe
    # commercial interpretation, so they keep only the source observation.
    return {
        "运行噪声": "把噪声列为选购比较维度，提供相同档位和条件下的数据。",
        "明确预算上限": "在推荐前保留预算门槛，并核对当地报价。单条预算无法作为市场价格目标。",
        "臭氧释放要求": "把该限制作为选购筛选条件。产品宣称和实际排放仍需分别核实。",
        "适用面积": "把适用面积列为推荐条件，先确认用户的房间大小，再比较候选产品。",
        "预算内除尘": "入门款定位可以围绕除尘目标验证。先确认用户希望少做哪些清洁，再验证产品能否达到该目标。",
        "规格与报价评价": "这条评价把规格和价格放在一起，可用于研究用户怎样判断性价比。",
        "续航与充电": "在原文所述的使用或充电场景下评估续航，避免用额定容量代替实际体验。",
        "可靠性与维护": "记录原文所述的故障条件与维护动作，帮助决定应先复现哪类问题。",
        "连接与软件体验": "把具体软件行为或修复期望作为研究输入，分别核查现有体验与用户希望改变的行为。",
        "宣传可信度": "比较实测证据和宣传描述能否帮助用户判断产品表现。这条观点未提供故障证据。",
        "滤芯获取与费用": "购买总成本可纳入耗材比较。应核对当地滤芯报价和供应渠道。",
    }.get(topic, "")


COMPARISON = re.compile(r"\b(?:compar\w*|versus|vs\.?|which (?:one|model)|alternatives?)\b|对比|比較", re.I)
NOISE = re.compile(r"\b(?:quiet(?:er|est)?|loud(?:er|est)?|nois(?:e|y|ier|iest))\b|噪声|噪音", re.I)
DRIVER = re.compile(r"\b(?:bought|chose|picked|switched)\b.{0,55}\b(?:because|due to)\b|因为.{1,30}(?:购买|选择)", re.I)
BARRIER = re.compile(r"\b(?:can't afford|cannot afford|too expensive for me|deal[- ]breaker|"
                     r"won't buy (?:it )?(?:unless|because)|put me off)\b|买不起|超出.{0,8}预算", re.I)


# Summary answers a decision question. Topic cards below carry the counts.
SUMMARY_FINDINGS = {
    "预算内除尘": ("入门款定位有一个可验证的除尘目标", "评论里有人明确把价格和除尘放在一起考虑。这提供了一个可以验证的基础款使用目标。"),
    "运行噪声": ("买家希望在选购前知道哪款更安静", "这是比较条件。原文没有提供各机型的实测噪声或噪声门槛。"),
    "明确预算上限": ("至少一位买家给出了明确的支出上限", "可以用这个条件筛选候选型号。它只代表原评论中的个人约束。"),
    "臭氧释放要求": ("部分选购问题涉及功能之外的使用限制", "原文明确提出不希望释放臭氧。报告无法据此确认任何型号的排放表现。"),
    "适用面积": ("推荐型号需要先匹配实际房间", "原文给出了房间面积。它约束候选范围，但没有证明任何型号能覆盖该面积。"),
    "滤芯获取与费用": ("耗材可能改变买家对总成本的判断", "原文讨论了滤芯费用或供应，适合和整机价格分开呈现。样本没有提供普遍可接受的费用。"),
    "续航与充电": ("续航研究应从具体使用场景出发", "评论提到充电或续航情境。后续比较可统一使用条件，避免把不同场景的表现直接并列。"),
    "可靠性与维护": ("应区分故障现象与发生条件", "原文的故障或维护线索能帮助安排复现。当前证据无法估计故障率。"),
    "连接与软件体验": ("把当前软件体验和期望修复项分开验证", "评论可提供具体行为线索。上线优先级仍需核对影响范围和复现条件。"),
}


def _skip_source(source):
    return bool(MEDIA_ONLY.fullmatch(source) or CONTENT_OR_IMAGINED.search(source)
                or VIDEO_LINK.search(source) or (LINK.search(source) and PROMOTION.search(source)))


def _purchase_kind(label, quote):
    if DRIVER.search(quote):
        return "购买驱动"
    if BARRIER.search(quote):
        return "待解决障碍"
    if "咨询" in label or supports_purchase_inquiry(quote):
        return "选购咨询"
    return "选购评价"


def _literal_card(claim, ref):
    """Render the original relationship and its decision implication."""
    names = " / ".join(claim.names)
    source = (ref,)
    if claim.kind == "recommendation":
        return "competitors", ReportItem(
            names, f"评论者想知道为何推荐名单没有列出 {claim.names[0]}。没有提供性能比较。",
            source, "推荐名单咨询", "推荐页可以解释哪些型号被纳入，以及筛选依据是什么。",
        )
    if claim.kind == "choice":
        note = f"原文还提到「{claim.value}」，滤芯描述尚未核实。" if claim.value else ""
        return "competitors", ReportItem(
            names, "评论者在这些选项之间犹豫。原文没有确认它们是否属于同一品类。" + note,
            source, "原文选购候选",
        )
    if claim.kind == "inquiry":
        return "purchase", ReportItem(
            f"{names} · 选购咨询", "评论者想知道这款值不值得买。原文未确认它的品类，也没有交代是否购买。",
            source, "型号选购咨询", "选购资料可说明适合谁，以及需要权衡什么。",
        )
    if claim.kind == "purchase":
        location = {"bedroom": "卧室", "living room": "客厅", "office": "办公室"}.get(claim.value.lower(), "")
        detail = f"评论者说已购买，只放在{location}。" if location else "评论者说已购买。"
        return "competitors", ReportItem(
            names, detail + "没有评价使用效果。", source, "原文购买自述",
        )
    if claim.kind == "filter_cost":
        amount = re.search(r"\bcosts?\s+([£€$¥]?\s*\d[\d,.]*(?:\s?[kK]\b)?)", claim.quote, re.I)
        detail = f"评论者自述替换滤芯费用为 {amount[1]}。" if amount else "评论者提到了替换滤芯的费用。"
        return "purchase", ReportItem(
            "滤芯获取与费用", detail + "币种和更换周期尚未核实。",
            source, "长期拥有成本",
        )
    if claim.kind == "room":
        return "purchase", ReportItem(
            "适用面积", f"评论者把 {claim.value} 作为选购条件。原文没有验证任何型号能覆盖该面积。",
            source, "房间条件",
        )
    if claim.kind == "preference":
        app = bool(re.search(r"\bapps?\b", claim.value, re.I))
        title = "无需额外 App 的产品偏好" if app else "偏好省去额外要求"
        detail = "评论者觉得不用另外装 App 是个卖点。" if app else "评论者把省去一项要求视为优点，具体见原文。"
        return "preferences", ReportItem(title, detail, source, "正面产品偏好")
    if claim.kind == "dust_budget":
        detail = "评论者希望在预算内买到能除尘的产品"
        detail += "，少花时间清洁桌面设备。" if claim.value else "。"
        return "needs", ReportItem("预算内除尘", detail + "没有给出具体预算。", source, "明确选购需求")
    return "needs", ReportItem(
        "希望找到除尘能力更强的型号", "评论者在粉尘场景下寻找更合适的型号。原文未验证已购型号的除尘表现或医疗效果。",
        source, "明确选购需求",
    )


def _phase_k_groups(items, *, by_topic=False):
    groups = {}
    for item in items:
        # Keep prices, named entities, roles and actions separate. Broad themes
        # can share a card, with one example and every supporting source.
        detail = "" if by_topic and item.detail.startswith("原文示例") else item.detail
        key = (item.title, item.badge, item.business_meaning, detail)
        prior = groups.get(key)
        groups[key] = item if prior is None else replace(
            prior, sources=tuple(dict.fromkeys(prior.sources + item.sources)))
    return sorted(groups.values(), key=lambda item: -len(item.sources))


def build_business_view(query, state, formal, collected, *, diagnostics=None):
    # Only returned and usable items can contribute. A budget stop or missing
    # result never converts a selected raw comment into an analysis finding.
    returned = [r for r in state["results"] if r["processing"]["status"] in {"Valid", "Partial"}]
    checked = [r for r in returned if not any(
        label["type"] in {"Irrelevant", "Unclear"}
        for label in r["processing"]["raw"].get("feedback_types", [])
    )]
    rechecked = state.get("source_observations", [])
    focus = focus_for(query)
    # Source-only extraction requires a returned analysis with cited evidence,
    # and never projects model claims from an invalid record.
    purchase_sources = list(checked)
    for failure in state.get("failures", []):
        processed = failure.get("processing", {})
        raw = processed.get("raw")
        if not isinstance(raw, dict) or not any(
            c.get("path") == ["feedback_types", i] and c.get("evidence_ids")
            for i, label in enumerate(raw.get("feedback_types", []))
            if isinstance(label, dict) and label.get("type") == "Purchase Inquiry"
            for c in processed.get("claim_quality", [])
        ):
            continue
        row = next((row for row in collected if row["review_id"] == failure.get("review_id")), None)
        if row:
            purchase_sources.append(row)
    choices = {}
    for row in purchase_sources:
        text = row["review_text"]
        if not _skip_source(text) and (not focus or matching_focus(focus, text)):
            if choice := purchase_choice(text):
                choices[row["review_id"]] = row, choice
    literal = {}
    for row in purchase_sources:
        text = row["review_text"]
        if _skip_source(text) or (focus and not matching_focus(focus, text)):
            continue
        if claims := literal_claims(query, evidence_spans(text)):
            literal[row["review_id"]] = (row, claims)
    rows = {r["review_id"]: r for r in checked + rechecked}
    for key, (row, _) in literal.items():
        rows.setdefault(key, row)
    category = _category_pattern(query, focus)

    def generic_product(name):
        return (name.casefold() in {"unknown", "model", "device", "product", "this one"}
                or bool(category and category.fullmatch(name))
                or bool(re.fullmatch(MONEY + r"\s+\w+", name, re.I)))

    original_rows = {row["review_id"]: row for row in collected}
    independently_checked = [(row, row["processing"]) for row in checked]
    for failure in state.get("failures", []):
        processed = failure.get("processing", {})
        raw = processed.get("raw")
        row = original_rows.get(failure.get("review_id"))
        if (row and isinstance(raw, dict) and processed.get("evidence_spans")
                and not any(label.get("type") in {"Irrelevant", "Unclear"} for label in raw.get("feedback_types", []))
                and any(issue.get("reason") in {"Entity lacks original attribution evidence.",
                                               "No supported feedback category remains."}
                        for issue in processed.get("issues", []))):
            independently_checked.append((row, processed))
    independent = {}
    for row, processed in independently_checked:
        text = row["review_text"]
        if (MEDIA_ONLY.fullmatch(text) or VIDEO_LINK.search(text)
                or (LINK.search(text) and PROMOTION.search(text))
                or (focus and not matching_focus(focus, text))):
            continue
        spans = processed["evidence_spans"]
        if not all(text[span["start"]:span["end"]] == span["text"] for span in spans):
            continue
        spans = [span for span in spans if not _skip_source(span["text"])]
        raw = processed["raw"]
        entity = raw.get("product_model", {})
        brand = raw.get("brand", {}).get("name", "unknown")
        cited = " ".join(span["text"] for span in spans if span["id"] in entity.get("evidence_ids", []))
        name = entity.get("name", "unknown")
        combined_name = f"{brand} {name}"
        if combined_name.casefold() in cited.casefold():
            name = combined_name
        if generic_product(name) or not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", cited, re.I):
            name = ""
        if claims := independent_claims(spans, name):
            key = row["review_id"]
            independent[key] = tuple(claim for claim in claims if not any(generic_product(n) for n in claim.names))
            if independent[key]:
                rows.setdefault(key, row)
    refs = {review_id: f"S{index:02d}" for index, review_id in enumerate(rows, 1)}
    product_audit = []
    opportunity_audit = Counter()
    supported_opportunities = set()
    for row in returned:
        model_needs = row["processing"]["raw"].get("potential_needs", [])
        opportunity_audit["模型提出"] += len(model_needs)
        supported = [model_needs[c["path"][1]] for c in row["processing"]["claim_quality"]
                     if c["path"][0] == "potential_needs" and c["status"] == "Supported"]
        supported_opportunities.update(id(item) for item in supported)
        opportunity_audit["证据校验未通过"] += len(model_needs) - len(supported)
    for failure in state.get("failures", []):
        raw = failure.get("processing", {}).get("raw")
        if isinstance(raw, dict) and isinstance(raw.get("potential_needs"), list):
            opportunity_audit["模型提出"] += len(raw["potential_needs"])
            opportunity_audit["评论级分析未通过"] += len(raw["potential_needs"])
    groups = group_themes({**state, "results": checked, "selected_sources": checked}, formal, focus=focus, include_context=True)
    themes = defaultdict(set)
    topic_evidence = defaultdict(set)
    buckets = defaultdict(list)
    for section in (*SECTIONS, "purchase"):
        for candidate_topic, entries in groups.get(section, {}).items():
            for row, label, evidence_ids, quotes, _ in entries:
                topic = candidate_topic
                local_claims = literal.get(row["review_id"], (None, ()))[1]
                claim_kinds = {claim.kind for claim in local_claims}
                parts = {q.strip() for q in quotes}
                if section == "experience" and "preference" in claim_kinds and all(
                    any(claim.kind == "preference" and claim.quote == part for claim in local_claims)
                    or GENERAL_COMPLAINT.search(part) for part in parts
                ):
                    continue
                if section == "purchase" and (
                    any(claim.quote in parts and claim.kind in {"recommendation", "choice", "inquiry", "room", "dust_budget", "dust_request"}
                        for claim in local_claims)
                ):
                    continue
                quote = " ".join(q.strip() for q in quotes)
                if section == "purchase" and row["review_id"] in choices:
                    unrelated_price = (candidate_topic == "价格与预算"
                                       and re.search(TOPICS["价格与预算"], CONSUMABLE_COST.sub("", quote), re.I))
                    if not unrelated_price:
                        continue
                if topic == "型号选择与比较" and not COMPARISON.search(quote):
                    continue
                if section == "purchase" and ROOM_SIZE.search(quote):
                    topic = "适用面积"
                elif section == "purchase" and NOISE.search(quote):
                    topic = "运行噪声"
                elif section == "purchase" and topic == "价格与预算" and re.search(r"\b(?:cadr|rated|specification)\b", quote, re.I):
                    topic = "规格与报价评价"
                elif section == "needs" and topic in {"价格与预算", "清洁效果"} and (
                    re.search(TOPICS["价格与预算"], quote, re.I) and re.search(r"\bdust\b|除尘", quote, re.I)
                ):
                    topic = "预算内除尘"
                if section == "experience" and (MARKETING_TRUST.search(quote) or
                    MARKETING_TRUST.search(row["review_text"]) and not any(
                        c["path"][0] == "feedback_types" and c["status"] == "Supported"
                        and row["processing"]["raw"]["feedback_types"][c["path"][1]]["type"] == "Actual Usage Experience"
                        for c in row["processing"]["claim_quality"]
                    )):
                    continue
                if focus and not matching_focus(focus, quote):
                    continue
                if section == "experience" and (supports_purchase_inquiry(quote) or quote.rstrip().endswith(("?", "？"))):
                    continue
                destination = "purchase" if section == "experience" and (
                    DRIVER.search(quote) or BARRIER.search(quote)
                ) else section
                kind = _purchase_kind(label, quote) if destination == "purchase" else SECTIONS[section]
                if destination == "experience":
                    if "严格统计" in label:
                        kind = "正式统计支持的反馈"
                    elif "使用原文线索" in label:
                        kind = "使用场景线索 · 探索性"
                    elif "本人使用自述" in label:
                        kind = "使用自述 · 探索性"
                    else:
                        kind = ("产品问题线索" if label.startswith("问题反馈") else "产品评价或观察") + " · 探索性"
                if topic not in UNCATEGORIZED and topic not in FACETS and topic not in TOPICS and not _meaning(topic):
                    if topic.casefold() not in quote.casefold():
                        topic = "产品评价与观察"
                ref = refs[row["review_id"]]
                if destination == "purchase" and kind == "选购咨询" and topic in UNCATEGORIZED:
                    raw = row["processing"]["raw"]
                    entity = raw.get("product_model", {}).get("name", "unknown")
                    brand = raw.get("brand", {}).get("name", "unknown")
                    claims = row["processing"]["claim_quality"]
                    supported_entity = any(c["path"] == ["product_model"] and c["status"] == "Supported"
                                           and set(c["evidence_ids"]) & set(evidence_ids) for c in claims)
                    if supported_entity and not generic_product(entity) and entity.casefold() in quote.casefold():
                        name = f"{brand} {entity}" if brand.casefold() != "unknown" else entity
                        if name.casefold() not in quote.casefold():
                            name = entity
                        buckets["purchase", f"{name} · 选购咨询", "型号咨询 · 品类待确认"].append(
                            (ref, tuple(q.strip() for q in quotes)))
                        continue
                if topic not in UNCATEGORIZED:
                    themes[topic].add(ref)
                    topic_evidence[topic, ref].update(evidence_ids)
                if topic in UNCATEGORIZED:
                    topic = "未进一步分类"
                buckets[destination, topic, kind].append((ref, tuple(q.strip() for q in quotes)))

    literal_constraints = []
    for row in checked:
        ref = refs[row["review_id"]]
        processed = row["processing"]
        supported_ids = {ident for claim in processed["claim_quality"] if claim["status"] == "Supported"
                         for ident in claim["evidence_ids"]}
        inquiry_ids = {ident for claim in processed["claim_quality"]
                       if claim["path"][0] == "feedback_types" and claim["status"] == "Supported"
                       and processed["raw"]["feedback_types"][claim["path"][1]]["type"] == "Purchase Inquiry"
                       for ident in claim["evidence_ids"]}
        for span in processed["evidence_spans"]:
            if span["id"] not in supported_ids or _skip_source(span["text"]):
                continue
            quote = span["text"].strip()
            if span["id"] in inquiry_ids and (not focus or matching_focus(focus, quote)):
                limit, ozone = purchase_constraints(quote)
                if limit:
                    literal_constraints.append(ReportItem(
                        "明确预算上限", f"评论者明确表示最多支出 {limit}（原文金额）。",
                        (ref,), "个人选购限制", _meaning("明确预算上限"),
                    ))
                    themes["明确预算上限"].add(ref)
                if ozone:
                    literal_constraints.append(ReportItem(
                        "臭氧释放要求", "评论者明确表示不希望产品释放臭氧。",
                        (ref,), "个人选购限制", _meaning("臭氧释放要求"),
                    ))
                    themes["臭氧释放要求"].add(ref)
                if limit or ozone:
                    for key, entries in buckets.items():
                        if key[1] in UNCATEGORIZED:
                            entries[:] = [(source, quotes) for source, quotes in entries
                                          if not (source == ref and quote in quotes)]
            if not focus and MARKETING_TRUST.search(quote):
                buckets["preferences", "宣传可信度", "宣传可信度顾虑 · 一般观点"].append((ref, (quote,)))
                themes["宣传可信度"].add(ref)
            if not any(claim.kind == "filter_cost" and claim.quote == quote for claim in literal.get(row["review_id"], (None, ()))[1]) and not focus and re.search(r"\b(?:filters?|refills?|consumables?)\b", quote, re.I) and (
                ACCESSORY_COST.search(quote) and re.search(r"\b(?:bought|purchased|ordered)\b", row["review_text"], re.I)
            ):
                buckets["purchase", "滤芯获取与费用", "耗材费用自述"].append((ref, (quote,)))
                themes["滤芯获取与费用"].add(ref)

    # Recover the literal choice question for presentation only. Preserve the
    # rejected model result and leave category, entities and statistics alone.
    for failure in state.get("failures", []):
        processed = failure.get("processing", {})
        raw = processed.get("raw")
        if not isinstance(raw, dict) or not any(
            issue.get("reason") == "No supported feedback category remains." for issue in processed.get("issues", [])
        ):
            continue
        row = next((row for row in collected if row["review_id"] == failure.get("review_id")), None)
        if row is None or any(c.kind == "choice" for c in literal.get(row["review_id"], (None, ()))[1]):
            continue
        ids = {ident for claim in raw.get("feedback_types", []) if claim["type"] == "Purchase Inquiry"
               for ident in claim["evidence_ids"]}
        for span in processed.get("evidence_spans", []):
            quote = span["text"].strip()
            if (span["id"] not in ids or _skip_source(quote)
                or not CHOICE_REQUEST.search(quote) or not COMPARISON.search(quote)
                or (focus and not matching_focus(focus, quote))):
                continue
            key = row["review_id"]
            if key not in refs:
                refs[key] = f"S{len(refs) + 1:02d}"
                rows[key] = row
            buckets["purchase", "型号选择咨询", "原文选购咨询 · 品类待确认"].append((refs[key], (quote,)))
            break
    observation_cards = []
    for key, claims in independent.items():
        ref = refs.get(key)
        if not ref:
            continue
        for claim in claims:
            observation_cards.append((claim.kind, *observation_card(claim, ref)))
            for topic in REPLACES.get(claim.kind, ()):
                themes[topic].discard(ref)
                for (_, bucket_topic, badge), entries in buckets.items():
                    if bucket_topic == topic and badge != "正式统计支持的反馈":
                        entries[:] = [(source, quotes) for source, quotes in entries if source != ref]

    cards = defaultdict(list)
    for (section, topic, kind), entries in buckets.items():
        if not entries:
            continue
        if state.get("phase_k"):
            descriptions = defaultdict(list)
            unresolved = []
            for ref, quotes in entries:
                specific = describe_evidence(topic, kind, " ".join(quotes))
                if specific is None:
                    unresolved.append((ref, quotes))
                else:
                    descriptions[specific].append(ref)
                    themes[specific[0]].add(ref)
                    if specific[0] != topic:
                        themes[topic].discard(ref)
            cards[section].extend(ReportItem(title, detail, tuple(dict.fromkeys(source_refs)), kind)
                                  for (title, detail), source_refs in descriptions.items())
            entries = unresolved
            if not entries:
                continue
        source_refs = tuple(dict.fromkeys(ref for ref, _ in entries))
        # A single representative excerpt provides specificity. Full quotes,
        # other perspectives and video links remain under evidence navigation.
        excerpts = [quote for _, quotes in entries for quote in quotes if 0 < len(quote) <= 260]
        excerpt = next((quote for quote in excerpts if topic == "适用面积" and ROOM_SIZE.search(quote)),
                       excerpts[0] if excerpts else "")
        detail = f"原文示例 「{excerpt}」" if excerpt else "展开来源查看消费者描述。"
        cards[section].append(ReportItem(topic, detail, source_refs, kind, _meaning(topic)))
    cards["purchase"].extend(dict.fromkeys(literal_constraints))
    need_keys = {(item.title, item.sources, item.detail) for item in cards["needs"]}
    cards["purchase"] = [item for item in cards["purchase"] if (item.title, item.sources, item.detail) not in need_keys]
    for items in cards.values():
        combined = {}
        for item in items:
            key = item.sources, item.badge, item.detail
            if not item.detail.startswith("原文示例"):
                key += (item.title,)
            previous = combined.get(key)
            if previous:
                item = ReportItem(f"{previous.title} · {item.title}", item.detail, item.sources,
                                  item.badge, item.business_meaning)
            combined[key] = item
        items[:] = combined.values()
        items.sort(key=lambda item: (-len(item.sources), item.title, item.badge))

    literal_products = []
    for key, (_, claims) in literal.items():
        ref = refs[key]
        for claim in claims:
            section, item = _literal_card(claim, ref)
            if claim.kind in {"recommendation", "choice", "inquiry"}:
                themes["型号选择"].add(ref)
            if section == "competitors":
                literal_products.append(item)
            elif not any(old.title == item.title and ref in old.sources for old in cards[section]):
                cards[section].append(item)
                if claim.kind != "inquiry":
                    theme = "除尘需求" if claim.kind in {"dust_budget", "dust_request"} else item.title
                    themes[theme].add(ref)

    for kind, section, item in observation_cards:
        if section == "competitors":
            literal_products.append(item)
        else:
            cards[section].append(item)
        if kind != "listening_context":
            theme = {"priced_choice": "型号选择", "subjective_comparison": "个人使用比较"}.get(kind, item.title)
            themes[theme].update(item.sources)

    def product_scope(row, source, name, role, before, after):
        if generic_product(name):
            return False
        # A nearby category noun must describe the named product itself.
        # Video titles and model name recognition cannot establish category.
        category_before = re.search(r"[^\W_]+\s*[,(:]?\s*$", before)
        adjacent = category and (
            (category_before and category.fullmatch(category_before.group().strip(" ,(:")))
            or category.match(after.lstrip(" ,("))
        )
        linked = category and (category.search(name) or (adjacent and not CONTEXT_OBJECT.search(before)))
        if not linked:
            product_audit.append({"review_id": row["review_id"], "product": name, "role": role,
                                  "reason": "原文未证实型号属于研究品类"})
        return bool(linked)

    mentions, pairs = competitor_evidence({"results": checked}, focus, _skip_source, product_scope=product_scope)
    choice_cards = []
    paired_refs = []
    for key, (row, choice) in choices.items():
        if key not in refs:
            refs[key] = f"S{len(refs) + 1:02d}"
            rows[key] = row
        ref = refs[key]
        title = " / ".join(choice.options)
        choice_cards.append(ReportItem(title, "评论者询问该选哪款。型号按原文列出，品类归属待确认。",
                                       (ref,), "原文选购候选"))
        themes["型号选择"].add(ref)
        if choice.area:
            themes["适用面积"].add(ref)
            cards["purchase"].append(ReportItem(
                "适用面积", f"选购条件中的房间面积为 {choice.area}（原文）。", (ref,),
                "使用场景条件", _meaning("适用面积"),
            ))
        if choice.consumable_cost:
            themes["滤芯获取与费用"].add(ref)
            cards["purchase"].append(ReportItem(
                "滤芯获取与费用", "评论者要求选购时考虑耗材费用。原文未给出价格或预算。",
                (ref,), "选购成本因素", _meaning("滤芯获取与费用"),
            ))
        if choice.area and choice.consumable_cost:
            paired_refs.append(ref)
    competitors = list(literal_products)
    for entries in mentions.values():
        name = next(iter(entries.values()))[0]
        by_role = defaultdict(list)
        for review_id, role in entries:
            by_role[role].append(refs[review_id])
        for role, sources in by_role.items():
            unique = tuple(dict.fromkeys(sources))
            if any(item.title.casefold() == name.casefold() and item.sources == unique for item in literal_products):
                continue
            competitors.append(ReportItem(name, role, unique, "原文产品提及"))
    for comments in pairs.values():
        left, right, _, _, _ = next(iter(comments.values()))
        competitors.append(ReportItem(
            f"{left} / {right}", "原文同时讨论两个对象。可在来源核对比较维度或选购背景。",
            tuple(refs[key] for key in comments), "原文对比",
        ))

    # Group literal pairs by unordered exact option names. Do not combine
    # brand aliases or claim either model performs better.
    by_pair = {}
    for item in choice_cards:
        key = tuple(sorted(name.casefold() for name in item.title.split(" / ")))
        previous = by_pair.get(key)
        if previous:
            item = ReportItem(previous.title, item.detail,
                              tuple(dict.fromkeys(previous.sources + item.sources)), item.badge)
        by_pair[key] = item
    competitors.extend(by_pair.values())

    opportunities = []
    # Treat model suggestions as hypotheses. Only carry through suggestions
    # already supported by the claim validator and backed by a displayed topic.
    grouped_opportunities = set()
    for topic, entries in groups.get("opportunities", {}).items():
        for row, _, evidence_ids, quotes, item in entries:
            ref = refs[row["review_id"]]
            grouped_opportunities.add(id(item))
            suggestion = item["summary"]
            if not set(evidence_ids) <= topic_evidence[topic, ref] or re.search(r"\d|https?://|%|百分之|市场份额", suggestion):
                opportunity_audit["展示证据不匹配或含未核实指标"] += 1
                continue
            if set(research_axes(suggestion)) - set(research_axes(" ".join(quotes))):
                opportunity_audit["建议涉及原文未提及的属性"] += 1
                continue
            opportunities.append(ReportItem(topic, suggestion, (ref,), "AI 假设 · 待验证",
                                            "用于决定是否值得继续调查，当前样本无法验证预期效果。"))
    for need in cards["needs"]:
        if not opportunities and need.title == "预算内除尘":
            opportunities.append(ReportItem(
                "入门款能否让用户少清理桌面？", "在实际使用场景中测试除尘效果，再判断这是否值得作为入门款卖点。",
                need.sources, "单条来源 · 探索性机会" if len(need.sources) == 1 else "原文研究方向 · 待验证",
            ))
            break
    preference = next((item for item in cards["preferences"] if item.badge == "正面产品偏好"), None)
    if preference:
        app = preference.title == "无需额外 App 的产品偏好"
        opportunities.append(ReportItem(
            "不用另装 App 会影响选购吗？" if app else "买家是否在意这项额外要求？",
            "比较需要与不需要 App 的方案，看看买家会不会因此改变选择。" if app else
            "比较有无这项要求的方案，看看买家会不会因此改变选择。",
            preference.sources, "单条来源 · 探索性机会",
        ))
    by_suggestion = {}
    for item in opportunities:
        key = item.detail.casefold().strip(" .。")
        previous = by_suggestion.get(key)
        if previous:
            item = ReportItem(previous.title, previous.detail, tuple(dict.fromkeys(previous.sources + item.sources)),
                              previous.badge, previous.business_meaning)
        by_suggestion[key] = item
    opportunities = [
        ReportItem(item.title, item.detail, item.sources,
                   ("AI 假设 · 多条来源" if len(item.sources) > 1 else "AI 假设 · 单条来源"),
                   item.business_meaning)
        if item.badge == "AI 假设 · 待验证" else item
        for item in list(by_suggestion.values())[:2]
    ]
    filter_cost = next((item for item in cards["purchase"] if item.badge == "长期拥有成本"), None)
    if filter_cost and len(opportunities) < 3:
        opportunities.append(ReportItem(
            "在选购页并列整机与替换滤芯费用", "先核对滤芯的售价、币种和供应渠道，再验证并列展示是否有助于选购。",
            filter_cost.sources, "单条来源 · 探索性机会",
        ))
    if paired_refs:
        evidence = tuple(dict.fromkeys(paired_refs))
        opportunities.insert(0, ReportItem(
            "把适用面积与耗材成本放进选购比较",
            "在同一选购页面并列展示各型号适用面积和可核对的滤芯更换费用。"
            "先核实各型号的面积口径、当地滤芯价格与更换周期。",
            evidence, "多条评论支持 · 小样本" if len(evidence) > 1 else "单条来源 · 探索性机会",
            "现有证据说明这些条件被一起考虑。消费者是否因此改变选择仍待验证。",
        ))
    if diagnostics is not None:
        opportunity_audit["主题或内容筛选未保留"] = len(supported_opportunities - grouped_opportunities)
        diagnostics.update(product_scope_exclusions=product_audit,
                           opportunities=dict(opportunity_audit), model_opportunities_displayed=sum(
                               item.badge.startswith("AI 假设") for item in opportunities),
                           literal_choice_comments=len(choices),
                           model_scope_exclusions=len(returned) - len(checked))
    if state.get("phase_k"):
        research_sources = defaultdict(list)
        for kind, _, item in observation_cards:
            if kind in RESEARCH:
                research_sources[kind].extend(item.sources)
        research = sorted(research_sources.items(), key=lambda pair: -len(set(pair[1])))
        for kind, references in research:
            title, detail = RESEARCH[kind]
            sources = tuple(dict.fromkeys(references))
            badge = "多条评论支持 · 待验证" if len(sources) > 1 else "单条来源 · 探索性机会"
            opportunities.append(ReportItem(title, detail, sources, badge))
        opportunities = _phase_k_groups(opportunities)[:6]
        for section in ("needs", "experience", "purchase", "preferences"):
            cards[section] = _phase_k_groups(cards[section], by_topic=section != "purchase")
        competitors = _phase_k_groups(competitors)
    existing_directions = {item.title for item in opportunities}
    for kind, _, item in observation_cards:
        if state.get("phase_k") or kind not in RESEARCH or len(opportunities) >= 3:
            continue
        title, detail = RESEARCH[kind]
        if title not in existing_directions:
            opportunities.append(ReportItem(title, detail, item.sources, "单条来源 · 探索性机会"))
            existing_directions.add(title)
    if diagnostics is not None:
        diagnostics["source_research_direction"] = any(not item.badge.startswith("AI 假设") for item in opportunities)
    primary = cards["needs"] + cards["experience"] + cards["purchase"] + cards["preferences"]
    displayed = {ref for item in primary + competitors + opportunities for ref in item.sources}
    all_topics = tuple(ReportItem(topic, "", tuple(sorted(sources))) for topic, sources in
                       sorted(((key, refs & displayed) for key, refs in themes.items() if refs & displayed),
                              key=lambda pair: (-len(pair[1]), pair[0])))
    topic_items = all_topics[:8]
    formal_ids = {r["review_id"] for r in formal if r["product_aspects"]}
    source_items = tuple(CommentSource(
        refs[key], row["video_id"], row["comment_id"], row["review_text"], row["published_at"],
        "validated" if key in formal_ids else "exploratory",
    ) for key, row in rows.items() if refs[key] in displayed)
    summary = []
    if paired_refs:
        evidence = tuple(dict.fromkeys(paired_refs))
        count_phrase = "有多条评论" if len(evidence) > 1 else "有一条评论"
        summary.append(ReportItem(
            "选购时，房间适配和后续花费可以是同一个问题",
            f"{count_phrase}在比较候选型号时，同时提出房间面积和滤芯成本。"
            "原文未提供实际购买决定，也无法估计这种需求有多普遍。",
            evidence, "样本观察",
            "品牌可先验证，是否应该把适用面积与后续耗材费用放在同一选购比较页。",
        ))
    for item in cards["needs"] + cards["preferences"] + cards["purchase"]:
        synthesis = {
            "预算内除尘": ("预算有限，也希望净化器能减少日常清洁负担",
                       "一位评论者想在预算内减少桌面清洁。对入门款来说，这提供了一个具体的使用任务。"),
            "无需额外 App 的产品偏好": ("不用另外装 App，也可能是卖点",
                                   "一位评论者把这一点当成优点。它为产品定位提供了线索，值得验证买家是否在意。"),
            "滤芯获取与费用": ("整机售价之外，还有后续换滤芯的花费",
                          "一位已购买的评论者主动提到滤芯费用。比较产品价格时，可以把耗材一起列出。"),
        }.get(item.title)
        if item.title == "滤芯获取与费用" and item.badge != "长期拥有成本":
            synthesis = None
        if item.title == "预算内除尘" and "桌面" not in item.detail:
            synthesis = None
        if synthesis and not any(set(item.sources) & set(previous.sources) for previous in summary):
            summary.append(ReportItem(*synthesis, item.sources, "样本观察"))
            if len(summary) == 4:
                break
    for kind, _, item in sorted(observation_cards, key=lambda entry: entry[0] not in RESEARCH):
        if len(summary) >= 4:
            break
        if not item.business_meaning or any(set(item.sources) & set(prior.sources) for prior in summary):
            continue
        if kind == "priced_choice":
            context = next((other.detail for tag, _, other in observation_cards
                            if tag == "listening_context" and other.sources == item.sources), "")
            if context:
                summary.append(ReportItem(
                    "两款耳机报价不同，买家描述了自己的听歌场景",
                    item.detail + context + "选购比较可以围绕这类日常听歌场景展开。",
                    item.sources, "样本观察",
                ))
                continue
        summary.append(ReportItem(item.title, item.detail + item.business_meaning, item.sources, "样本观察"))
    summary_sources = {ref for item in summary for ref in item.sources}
    for item in sorted(primary, key=lambda item: -len(item.sources)):
        if len(summary) >= 4 or item.title not in SUMMARY_FINDINGS or not set(item.sources) - summary_sources:
            continue
        title, detail = SUMMARY_FINDINGS[item.title]
        summary.append(ReportItem(title, detail, item.sources, "样本观察"))
        summary_sources.update(item.sources)
        if len(summary) == 4:
            break
    view = BusinessReportView(
        query, False, source_items, summary=tuple(summary), topics=topic_items,
        needs=tuple(cards["needs"] + cards["experience"] + cards["preferences"]),
        purchase=tuple(cards["purchase"]), competitors=tuple(competitors), opportunities=tuple(opportunities),
        coverage=ReportCoverage(len(collected), state["submitted"], len(displayed), len(formal_ids),
                                len({r["video_id"] for r in collected})),
        limitations=(
            "本轮来自近期发布视频的第一页公开顶层评论。时间范围筛选视频发布时间。",
            "探索性洞察和待验证方向单列。用户自述、产品参数与价格未经独立核实。",
            "每项按去重评论 ID 计数。同一条评论可支持多个主题，本次样本不代表市场趋势。",
        ),
    )
    return upgrade_phase_k(view, all_topics) if state.get("phase_k") else view
