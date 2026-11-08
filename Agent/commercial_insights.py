"""Evidence-only commercial presentation for the existing multi-comment report."""

from collections import defaultdict
import re

from generate_report import markdown as md
from research_focus import BARE_COMPARISON, matching_focus

# Lexical model candidates supplement the validated model output. The candidate
# is the name as written, with no manufacturer inferred from a model prefix.
MODEL_NAME = re.compile(
    r"(?<!\w)(?!(?:The|My|Our|This|That|With|And|For|But|Between|Compare)\b)"
    r"(?:[A-Z][\w-]+|[a-z]+[A-Z][\w-]+)"
    r"(?:(?: [A-Z][\w-]+){0,2} (?=\w*\d)(?=\w*[A-Za-z])(?!\d+(?i:mAh|W|Hz|GB|TB)\b)[A-Za-z0-9-]+"
    r"|(?: [A-Z][\w-]+){1,2} \d+(?![\w%]|\s+(?i:mAh|W|Hz|GB|TB|hours?|minutes?)\b))"
    r"(?: (?:Pro|Max|Plus|Ultra|Mini|Lite|SE)){0,2}\b"
)
PAIR_CUE = re.compile(
    r"\b(?:vs\.?|versus|compared (?:with|to)|rather than|(?:more|less|better|worse|longer|shorter|cheaper|faster|slower) than|"
    r"outperform\w*|beats?)(?: the| my| our| this| an?)?\s+$", re.I
)
CHOICE_CUE = re.compile(r"\b(?:choosing|deciding|torn|hesitat\w*) (?:between|whether)\b", re.I)
PREFERENCE_CUE = re.compile(r"\b(?:prefer|compare|compared)\b", re.I)
ROLE_CUES = (
    ("已购买", re.compile(r"(?:^\s*|\b(?:I|we) )(?:bought|purchased|ordered) (?:an? |the |my |our )?$", re.I)),
    ("拟购买或考虑", re.compile(r"\b(?:considering|thinking (?:of|about) buying|looking (?:at|to buy)|switch(?:ing)? to|replace (?:it|mine) with|buy(?:ing)?|purchase) (?:an? |the )?$", re.I)),
    ("当前使用", re.compile(r"\b(?:I|we) (?:(?:currently )?use|(?:am|are) (?:currently )?using) (?:my |our |an? |the )?$", re.I)),
    ("本人使用过", re.compile(r"\b(?:I|we) (?:used|tested|tried|wore) (?:my |our |an? |the )?$", re.I)),
    ("视频中介绍", re.compile(r"\b(?:the video (?:shows|reviews)|(?:shown|reviewed|featured) in the video:?|in the video:?)(?: an?| the)? $", re.I)),
)
VIDEO_AFTER = re.compile(r"^\s*(?:(?:as|was|is) )?(?:shown|reviewed|featured) in (?:the |this )?video\b", re.I)
BUY_AFTER = re.compile(r"^\s+as (?:an?|the) (?:\w+ )?option\b", re.I)
ATTRIBUTED = re.compile(r"\b(?:said|says|heard|told|my friend|according to)\b|[“”\"]", re.I)
HYPOTHETICAL = re.compile(r"^\s*(?:if\b|(?:(?:just|now) )?imagine\b)", re.I)


def source_links(entries):
    links = {row["review_id"]: row["source_url"] for row, *_ in entries}
    return len(links), "、".join(f"[来源 {index}]({url})" for index, url in enumerate(links.values(), 1))


def _entity_names(processed):
    raw = processed["raw"]
    spans = {span["id"]: span["text"] for span in processed["evidence_spans"]}
    names = defaultdict(list)
    for claim in processed["claim_quality"]:
        if claim["status"] != "Supported" or claim["path"] not in (["brand"], ["product_model"]):
            continue
        name = raw[claim["path"][0]]["name"]
        if name.casefold() == "unknown":
            continue
        for ident in claim["evidence_ids"]:
            if ident in spans:
                names[ident].append(name)
    return names


def _mentions(text, named):
    # Prefer the longest source-matched name when a brand, model substring and
    # full model overlap. Preserve capitalization and source positions.
    candidates = [(m.start(), m.end(), m.group()) for m in MODEL_NAME.finditer(text)]
    labels = list(named)
    if len(labels) == 2:
        labels.extend((f"{named[0]} {named[1]}", f"{named[1]} {named[0]}"))
    for name in labels:
        candidates.extend((m.start(), m.end(), m.group()) for m in
                          re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I))
    kept = []
    for start, end, name in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
        if not any(start < b and a < end for a, b, _ in kept):
            kept.append((start, end, name))
    return sorted(kept)


def _role(before, after, context):
    if VIDEO_AFTER.match(after):
        return "视频中介绍"
    if BUY_AFTER.match(after):
        return "拟购买或考虑"
    for label, cue in ROLE_CUES:
        if cue.search(before) and (label not in {"当前使用", "本人使用过", "已购买"} or not ATTRIBUTED.search(context)):
            return label
    if re.search(r"\b(?:what about|how about|thoughts on)\s+(?:the )?$", before, re.I) and after.lstrip().startswith("?"):
        return "产品咨询"
    return "提及，角色未确认"


def competitor_evidence(state, focus, skip_source, *, product_scope=None):
    """Pair only explicit comparisons in one original span. Never assign a fault."""
    mentions, pairs = defaultdict(dict), defaultdict(dict)
    for row in state["results"]:
        processed = row["processing"]
        if processed["status"] not in {"Valid", "Partial"} or not processed.get("evidence_spans"):
            continue
        validated_names = _entity_names(processed)
        for span in processed["evidence_spans"]:
            source = span["text"]
            if skip_source(source) or BARE_COMPARISON.fullmatch(source) or HYPOTHETICAL.match(source):
                continue
            if focus and not matching_focus(focus, source):
                continue
            found = _mentions(source, validated_names[span["id"]])
            scoped = []
            for i, (start, end, name) in enumerate(found):
                before = source[found[i-1][1] if i else 0:start]
                after = source[end:found[i+1][0] if i + 1 < len(found) else len(source)]
                role = _role(before, after, source)
                if product_scope is not None and not product_scope(row, source, name, role, before, after):
                    continue
                scoped.append((start, end, name))
                key = name.casefold()
                # One comment can mention a product in more than one role.
                mentions[key].setdefault((row["review_id"], role), (name, row["source_url"], source))
            if len(found) != 2 or len(scoped) != 2:
                continue
            left, right = found
            between, lead = source[left[1]:right[0]], source[:left[0]]
            if PAIR_CUE.search(between) or (PREFERENCE_CUE.search(lead) and
                    re.fullmatch(r"\s*(?:over|to|with)(?: the| my)?\s+", between, re.I)):
                label = "评论中的比较"
            elif CHOICE_CUE.search(lead) and re.search(r"\b(?:and|or)\b", between, re.I):
                label = "选购备选比较"
            else:
                continue
            key = tuple(sorted((left[2].casefold(), right[2].casefold())))
            if key[0] != key[1]:
                pairs[key].setdefault(row["review_id"], (left[2], right[2], label, row["source_url"], source))
    return mentions, pairs


def render_competitors(state, focus, skip_source):
    mentions, pairs = competitor_evidence(state, focus, skip_source)
    if not mentions:
        return ["当前缺少可归属的产品提及或比较。"]
    lines = []
    for comments in pairs.values():
        left, right, *_ = next(iter(comments.values()))
        lines.extend([f"### {md(left)} / {md(right)} · {len(comments)} 条独立评论", ""])
        lines.extend(f"- **{label}** [原文]({url}) 「{md(source.strip())}」"
                     for _, _, label, url, source in comments.values())
    if not pairs:
        lines.append("已发现产品提及；原文中可确认的双对象比较证据不足。")
    lines.extend(["", "### 产品提及与角色", ""])
    for entries in mentions.values():
        name = next(iter(entries.values()))[0]
        lines.append(f"- **{md(name)}** · {len({review for review, _ in entries})} 条独立评论。")
        for (_, role), (_, url, source) in entries.items():
            lines.append(f"  - {role} [原文]({url}) 「{md(source.strip())}」")
    lines.extend(["", "比较为评论者的描述或选购考虑；角色未确认时不做故障归因。小样本不支持产品排名。"])
    return lines


# Product-agnostic validation patterns, selected by cited measures or existing
# topics. They propose work to test, never infer a business outcome.
VALIDATION = {
    "电池容量": ("比较不同容量的设计方案", "统一使用负载与起止电量，记录持续时间"),
    "充电速度": ("试验充电速度目标", "固定温度和充电设备，测量相同电量区间的耗时"),
    "机身厚度或重量": ("比较容量与便携性的设计组合", "记录原型尺寸与重量，并用同一场景做盲测"),
    "指定使用场景下的持续时间": ("设定目标使用时长", "用一致的负载和起止条件复测"),
    "连续使用后的舒适度与贴合度": ("测试不同尺寸或佩戴方案", "按佩戴时长收集压迫感、贴合度和退出原因"),
    "取消或续订的步骤与实际扣费": ("测试更清晰的取消或续订入口", "让用户独立完成任务，记录完成率、步骤和账单结果"),
    "不同污物条件下的清洁效果": ("比较清洁或过滤方案", "固定污物类型与用量，记录残留量和维护时间"),
    "使用寿命与耐用性": ("复核高频使用下的耐用性及维修选项", "按型号记录使用周期和故障条件，并核对保修与维修报价"),
    "价格与预算": ("试验更清晰的价格与功能对照", "向用户展示同条件选项，记录决策理由和可接受的价格范围"),
    "维修与售后成本": ("评估可更换部件及透明报价", "按同一故障比较维修与整机更换报价"),
}
