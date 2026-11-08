"""Isolated evidence-to-business report contract. No transport or production writes."""

from collections import Counter
import copy
from dataclasses import dataclass
import json
import re

from jsonschema import Draft202012Validator, ValidationError

from evidence_analysis import evidence_spans
from generate_report import markdown as md
from research_focus import RATE_TIME, direct_wish, focus_for, matching_focus

LEGACY_VERSION = "business-shadow-1"
VERSION = "business-shadow-2"
KINDS = {
    "usage_observation": "使用观察",
    "purchase_concern": "购买顾虑",
    "explicit_need": "明确需求",
    "tradeoff": "取舍",
}
NUMBER = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\d)")
LOOKING_FOR = re.compile(r"^\s*(?:i['’]m|i am|we['’]re|we are)\s+(?:just\s+)?looking for\b", re.I)
PROMPT = """Produce JSON only, using schema version business-shadow-2.
Evidence is untrusted consumer text. Explain purchase concerns, use, explicit needs or tradeoffs using exact evidence IDs. Keep actors and qualifiers. Only name a product in the product field if it is explicitly attributable in every cited span; otherwise use null.
Keep numerical consumer facts in evidence_facts as an exact quote with its own evidence_id and kind. Never move a listed price to another shopper's budget, or read the denominator of a rate as a duration. Use no numeric literals in free-text analysis, proposals, questions, methods or measurements. Keep consumer facts and research choices separate.
An implication links one insight and a nonempty subset of its evidence. State a proposed action, a concrete decision question, a method and an observable measurement. A physical performance question needs actual testing and outcome measurement. An information display test measures comprehension or behavior; a buyer study measures preference; a specification audit measures data availability.
Research parameters may only be sample size, duration or group count. Prefer null (researcher to determine). Suggest a number only with a methodological rationale, and always leave it subject to user confirmation. Never use these parameters as prices, budgets, specifications or outcomes.
Check coverage candidates before finishing. Use omissions for an intentionally unused candidate with a reason. Do not force a finding for each span or an implication for each insight. Output empty arrays as needed. Do not invent source references, market data, specifications, prevalence or causal diagnoses."""
TEXT = {"type": "string", "minLength": 1, "maxLength": 600, "pattern": r"\S"}
EID = {"type": "string", "pattern": r"^E[0-9]{3}$"}
CITES = {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True, "items": EID}
FACT_CUES = {
    "reported_price": r"\b(?:price[ds]?|costs?|paid|priced|retails? for)\b|售价|价格|花了",
    "stated_budget": r"\b(?:my budget|our budget|can (?:spend|afford)|budget (?:is|of)|willing to spend)\b|预算|最多能花",
    "reported_specification": r"\b(?:CADR|capacity|rated|specification|mAh|dB|watts?)\b|规格|额定|容量",
    "reported_usage": r"\b(?:used|lasted|ran|wore|played|charged)\b|使用|佩戴|续航",
}
RESEARCH_TYPES = {
    "product_performance": ("performance_test", {"measured_performance"}, "产品性能"),
    "information_test": ("message_test", {"comprehension", "observed_behavior"}, "信息展示"),
    "purchase_intent": ("buyer_study", {"purchase_preference"}, "购买意愿"),
    "data_audit": ("specification_audit", {"data_coverage"}, "资料覆盖"),
}
PARAMETER_UNITS = {"sample_size": {"participants", "items"}, "duration": {"minutes", "hours", "days"}, "group_count": {"groups"}}


def object_schema(fields):
    return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": fields}


def item_list(item, maximum=8):
    return {"type": "array", "maxItems": maximum, "items": item}


INSIGHT = {"id": {"type": "string", "pattern": r"^I[0-9]{2}$"},
           "kind": {"enum": list(KINDS)}, "summary": TEXT, "product": {"type": ["string", "null"], "minLength": 1},
           "evidence_ids": CITES}
IMPLICATION = {"id": {"type": "string", "pattern": r"^O[0-9]{2}$"},
               "insight_id": {"type": "string", "pattern": r"^I[0-9]{2}$"},
               "proposal": TEXT, "validation": TEXT, "evidence_ids": CITES}
FACT = object_schema({"evidence_id": EID, "kind": {"enum": list(FACT_CUES)}, "quote": TEXT})
PARAMETER = object_schema({"kind": {"enum": list(PARAMETER_UNITS)},
                           "value": {"type": ["integer", "null"], "minimum": 1},
                           "unit": {"enum": sorted(set().union(*PARAMETER_UNITS.values()))},
                           "rationale": {"anyOf": [TEXT, {"type": "null"}]}})
SCHEMA = object_schema({"schema_version": {"const": VERSION},
    "insights": item_list(object_schema({**INSIGHT, "evidence_facts": item_list(FACT)})),
    "implications": item_list(object_schema({**IMPLICATION,
        "decision_question": TEXT, "decision_type": {"enum": list(RESEARCH_TYPES)},
        "method_type": {"enum": [method for method, _, _ in RESEARCH_TYPES.values()]},
        "measurement_type": {"enum": sorted(set().union(*(measures for _, measures, _ in RESEARCH_TYPES.values())))},
        "expected_measurement": TEXT, "research_parameters": item_list(PARAMETER, 3)})),
    "omissions": item_list(object_schema({"evidence_id": EID, "reason": TEXT}), 24)})
LEGACY_SCHEMA = object_schema({"schema_version": {"const": LEGACY_VERSION},
    "insights": item_list(object_schema(INSIGHT)), "implications": item_list(object_schema(IMPLICATION))})
# Validate the envelope first; individual items can fail without losing siblings.
PROXY_METRIC = re.compile(r"\b(?:clicks?|click-through|views?|impressions?|conversion rate|CTR|listings?|claims?|copy|data availability|specification coverage)\b|点击|文案|商品卡|规格覆盖", re.I)
BUYER_MEASURE = re.compile(r"\b(?:choice|choose|preference|intent|willingness)\b|选择|偏好|意愿", re.I)
PARAMETER_AS_FACT = re.compile(
    r"\b(?:set|cap|use|treat)\b.{0,40}\b(?:consumer budget|shopper budget|product price|market share|specification)\b"
    r"|(?:设定|作为|用作).{0,15}(?:消费者预算|商品售价|市场份额|产品规格)", re.I
)
PHYSICAL_METHOD = re.compile(r"\b(?:measure|measurements?|test|observe|record)\b|实测|测量|测试|记录", re.I)
SPELLED_QUANTITY = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million)"
    r"(?:[ -](?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|and))*"
    r"\s+(?:dollars?|euros?|yuan|percent|participants?|groups?|hours?|days?)\b"
    r"|[零一二两三四五六七八九十百千万亿]+\s*(?:元|美元|欧元|人|组|天|小时)|百分之[零一二两三四五六七八九十百]+",
    re.I,
)


@dataclass(frozen=True)
class Evidence:
    id: str
    review_id: str
    source_span_id: str
    source_url: str
    text: str
    products: tuple
    brands: tuple
    need_status: str


@dataclass(frozen=True)
class EvidencePack:
    topic: str
    evidence: tuple


def build_evidence_pack(topic, reviews, *, model_results=None):
    """Use selected real source records and optionally replay raw per-comment outputs."""
    from automatic_research import validate_sources
    from commercial_insights import _mentions
    from multi_comment_research import process_batch_comment

    rows = copy.deepcopy(list(reviews))
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("A business research topic is required.")
    if (len(rows) > 10 or len({row["review_id"] for row in rows}) != len(rows) or
        any(row.get("source_platform") != "youtube" or row.get("is_synthetic") is not False
            or row.get("text_is_preview") for row in rows)):
        raise ValueError("The shadow pack requires up to ten unique full YouTube records.")
    validate_sources(rows)
    evidence = []
    for row in rows:
        spans = evidence_spans(row["review_text"])
        raw = (model_results or {}).get(row["review_id"])
        processed = process_batch_comment(raw, row) if raw is not None else None
        claims = processed["claim_quality"] if processed and processed["status"] in {"Valid", "Partial"} else []
        for span in spans:
            source_id, quote = span["id"], span["text"]
            products = set()
            brands = set()
            explicit = False
            for claim in claims:
                if claim["status"] != "Supported" or source_id not in claim["evidence_ids"]:
                    continue
                path = claim["path"]
                if path == ["product_model"]:
                    name = processed["raw"]["product_model"]["name"]
                    mentions = _mentions(quote, [name])
                    if name.casefold() != "unknown" and len(mentions) == 1 and re.search(
                        r"(?<!\w)" + re.escape(name) + r"(?!\w)", quote, re.I
                    ):
                        products.add(name)
                elif path == ["brand"]:
                    name = processed["raw"]["brand"]["name"]
                    if name.casefold() != "unknown":
                        brands.add(name)
                elif path[0] == "facts" and processed["raw"]["facts"][path[1]]["kind"] == "explicit_need":
                    explicit = True
            need = ("validated_claim" if explicit else "source_cue" if direct_wish(quote) or
                    (LOOKING_FOR.search(quote) and not quote.rstrip().endswith(("?", "？"))) else "unknown")
            if len(evidence) == 999:
                raise ValueError("Too many source spans for the shadow contract.")
            evidence.append(Evidence(f"E{len(evidence)+1:03d}", row["review_id"], source_id, row["source_url"],
                                     quote, tuple(sorted(products)), tuple(sorted(brands)), need))
    return EvidencePack(topic, tuple(evidence))


def coverage_candidates(pack):
    """Conservative diagnostics only; candidates do not have to become insights."""
    focus = focus_for(pack.topic)
    words = set(re.findall(r"[^\W_]{3,}", pack.topic.casefold())) - {"the", "and", "for", "review", "best"}
    candidates = {}
    for item in pack.evidence:
        if item.need_status == "validated_claim":
            candidates[item.id] = "已有明确需求证据"
            continue
        relevant = (matching_focus(focus, item.text) if focus else
                    words.intersection(re.findall(r"[^\W_]{3,}", item.text.casefold())))
        if relevant and item.need_status == "source_cue":
            candidates[item.id] = "主题相关的直接需求线索"
        elif relevant and NUMBER.search(item.text) and any(re.search(cue, item.text, re.I) for cue in FACT_CUES.values()):
            candidates[item.id] = "主题相关且包含可核对的量化信息"
    return candidates


def build_shadow_request(pack, policy):
    """Build a single Qwen-compatible request. A future separately authorized runner sends it."""
    from analysis_control import QWEN_MODEL, message_token_estimate

    if policy["model"] != QWEN_MODEL or policy["enable_thinking"] is not False:
        raise ValueError("The shadow request plan uses the pinned non-thinking Qwen model.")
    if not pack.evidence:
        raise ValueError("An empty evidence pack does not need a model request.")
    candidates = coverage_candidates(pack)
    data = {"topic": pack.topic, "schema": SCHEMA, "evidence": [
        {"id": item.id, "text": item.text, "attributed_products": item.products,
         "brand_labels": item.brands, "need_status": item.need_status,
         "coverage_candidate": item.id in candidates}
        for item in pack.evidence]}
    messages = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}]
    output = policy["max_output_tokens"]
    if (type(output) is not int or not 1 <= output <= 3000 or
            message_token_estimate(messages) > min(policy["max_input_tokens"], 11000)):
        raise ValueError("The shadow request exceeds the declared token limits.")
    return {"model": policy["model"], "messages": messages, "max_tokens": output, "temperature": 0,
            "enable_thinking": False, "stream": False, "response_format": {"type": "json_object"}}


def _reject_narrative_quantities(*texts):
    if any(NUMBER.search(text) or SPELLED_QUANTITY.search(text) for text in texts):
        raise ValueError("Narrative contains a quantity; use a verbatim evidence fact or a proposed research parameter.")


def _validate_research_design(opportunity):
    decision = opportunity["decision_type"]
    method, measures, _ = RESEARCH_TYPES[decision]
    if opportunity["method_type"] != method or opportunity["measurement_type"] not in measures:
        raise ValueError("Research method or expected measurement does not match the decision type.")
    if decision == "product_performance" and (
        not PHYSICAL_METHOD.search(opportunity["validation"]) or PROXY_METRIC.search(opportunity["validation"])
        or PROXY_METRIC.search(opportunity["expected_measurement"])
    ):
        raise ValueError("Product performance needs actual testing and outcome measurement, not listing or copy coverage.")
    if decision == "purchase_intent" and not BUYER_MEASURE.search(opportunity["expected_measurement"]):
        raise ValueError("Purchase intent needs an explicit preference or choice measure.")
    kinds = set()
    for param in opportunity["research_parameters"]:
        if param["kind"] in kinds or param["unit"] not in PARAMETER_UNITS[param["kind"]]:
            raise ValueError("Research parameter kind is duplicated or has an incompatible unit.")
        kinds.add(param["kind"])
        if param["value"] is not None and param["rationale"] is None:
            raise ValueError("A concrete research parameter needs a methodological rationale.")
        if param["rationale"] is not None:
            _reject_narrative_quantities(param["rationale"])
            if PARAMETER_AS_FACT.search(param["rationale"]):
                raise ValueError("A research parameter cannot be used as a price, budget or specification.")


def audit_shadow_response(pack, response):
    """Return an accepted view and per-item diagnostics without editing the raw response."""
    value = json.loads(response) if isinstance(response, str) else copy.deepcopy(response)
    version = value.get("schema_version") if isinstance(value, dict) else None
    contract = {VERSION: SCHEMA, LEGACY_VERSION: LEGACY_SCHEMA}.get(version) if isinstance(version, str) else None
    if contract is None:
        raise ValueError("Unsupported shadow response version.")
    envelope = copy.deepcopy(contract)
    for prop in envelope["properties"].values():
        if prop.get("type") == "array":
            del prop["items"]
    Draft202012Validator(envelope).validate(value)
    index = {item.id: item for item in pack.evidence}
    insights = {}
    implications = []
    notes = {}
    rejected = []

    def resolve(ids, *legacy_assertions):
        if any(ident not in index for ident in ids):
            raise ValueError("Unknown shadow evidence ID.")
        items = [index[ident] for ident in ids]
        if legacy_assertions:
            numbers = {number for item in items for number in NUMBER.findall(item.text)}
            unknown = set().union(*(set(NUMBER.findall(text)) for text in legacy_assertions)) - numbers
            if unknown:
                raise ValueError("Shadow text contains a number absent from its evidence: " + ", ".join(sorted(unknown)))
        return items

    def validate_fact(fact, ids):
        ident, quote, kind = fact["evidence_id"], fact["quote"], fact["kind"]
        if ident not in ids or quote not in index[ident].text or not NUMBER.search(quote):
            raise ValueError("An evidence fact must quote the number verbatim from one cited span.")
        if not re.search(FACT_CUES[kind], quote, re.I):
            raise ValueError("Evidence fact quote does not establish the declared kind.")
        if kind == "stated_budget" and re.search(FACT_CUES["reported_price"], quote, re.I):
            raise ValueError("A reported price cannot establish a shopper budget.")
        if kind == "reported_usage" and RATE_TIME.search(quote):
            raise ValueError("A rate denominator cannot establish usage duration.")

    def audit_section(section, identity):
        items = value[section]
        counts = Counter(item[identity] for item in items if isinstance(item, dict) and isinstance(item.get(identity), str))
        validator = Draft202012Validator(contract["properties"][section]["items"])
        for position, item in enumerate(items):
            ident = item.get(identity) if isinstance(item, dict) else None
            try:
                validator.validate(item)
                if counts[ident] != 1:
                    raise ValueError("Duplicate item ID.")
                ids = item.get("evidence_ids", [])
                if section == "insights":
                    evidence = resolve(ids, item["summary"]) if version == LEGACY_VERSION else resolve(ids)
                    if item["product"] is not None and any(
                        item["product"].casefold() not in {product.casefold() for product in e.products} for e in evidence
                    ):
                        raise ValueError("A shadow insight names a product without matching attribution in every cited span.")
                    if item["kind"] == "explicit_need" and all(e.need_status == "unknown" for e in evidence):
                        raise ValueError("An explicit need requires a direct source cue or validated need.")
                    if version == VERSION:
                        _reject_narrative_quantities(item["summary"])
                        for fact in item["evidence_facts"]:
                            validate_fact(fact, ids)
                    insights[ident] = item
                elif section == "implications":
                    parent = insights.get(item["insight_id"])
                    if parent is None or not set(ids) <= set(parent["evidence_ids"]):
                        raise ValueError("An implication must cite evidence from its accepted parent insight.")
                    if version == LEGACY_VERSION:
                        resolve(ids, item["proposal"], item["validation"])
                    else:
                        resolve(ids)
                        _reject_narrative_quantities(*(item[key] for key in
                            ("proposal", "decision_question", "validation", "expected_measurement")))
                        _validate_research_design(item)
                    implications.append(item)
                else:
                    resolve([ident])
                    notes[ident] = item["reason"]
            except (ValueError, ValidationError) as exc:
                # Keep raw items in the audit, and render only the reason publicly.
                reason = ("Item does not match the shadow schema." if isinstance(exc, ValidationError) else str(exc))
                rejected.append({"section": section, "id": ident if isinstance(ident, str) else None,
                                 "position": position, "reason": reason})

    audit_section("insights", "id")
    audit_section("implications", "id")
    if version == VERSION:
        audit_section("omissions", "evidence_id")
    cited = {ident for insight in insights.values() for ident in insight["evidence_ids"]}
    missed = [{"evidence_id": ident, "signal": signal,
               "reason": notes.get(ident, "未被任何通过校验的洞察引用，模型未说明原因"),
               "model_reason": ident in notes}
              for ident, signal in coverage_candidates(pack).items() if ident not in cited]
    return {"raw": value, "insights": list(insights.values()), "implications": implications,
            "rejected": rejected, "missed_coverage": missed}


def validate_shadow_response(pack, response):
    """Strict compatibility interface; use audit_shadow_response for partial rendering."""
    audit = audit_shadow_response(pack, response)
    if audit["rejected"]:
        raise ValueError(audit["rejected"][0]["reason"])
    return audit["raw"]


def render_shadow_report(pack, response=None, *, offline=True):
    """Render source-backed observations independently of the production report."""
    value = (audit_shadow_response(pack, response) if response is not None else
             {"insights": [], "implications": [], "rejected": [], "missed_coverage": []})
    index = {item.id: item for item in pack.evidence}
    lines = [f"# Shadow Report · {md(pack.topic)}", "",
             "> 离线构造输出 · 无真实模型调用" if offline else "> 独立旁路报告 · 商业解释与建议待复核",
             "", f"本包包含 {len({item.review_id for item in pack.evidence})} 条独立评论。"
                 " 洞察与建议不计入正式属性统计。", ""]

    def cite(ids):
        count = len({index[ident].review_id for ident in ids})
        refs = "、".join(f"[{ident}]({index[ident].source_url})" for ident in ids)
        return f"{count} 条独立评论（{refs}）"

    lines += ["## Insight · 消费者关注点", ""]
    if not value["insights"]:
        lines += ["当前只有证据，暂无通过校验的洞察。", ""]
    for item in value["insights"]:
        product = f" · {md(item['product'])}" if item["product"] is not None else ""
        lines += [f"- **{item['id']} · {KINDS[item['kind']]}{product}** {md(item['summary'])}。依据 {cite(item['evidence_ids'])}。"]
        for fact in item.get("evidence_facts", []):
            lines += [f"  - **评论原文事实 · {md(fact['kind'])}** 「{md(fact['quote'])}」 {cite([fact['evidence_id']])}。"]
    lines += ["", "## Implication · 待验证商业建议", ""]
    if not value["implications"]:
        lines += ["暂无足够证据提出建议。"]
    for item in value["implications"]:
        lines += [f"- **{item['id']} · 关联 {item['insight_id']}** {md(item['proposal'])}。依据 {cite(item['evidence_ids'])}。",
                  f"  - **验证方法** {md(item['validation'])}。"]
        if "decision_question" in item:
            lines += [f"  - **决策问题 · {RESEARCH_TYPES[item['decision_type']][2]}** {md(item['decision_question'])}",
                      f"  - **预期测量** {md(item['expected_measurement'])}。"]
            for param in item["research_parameters"]:
                value_text = str(param["value"]) + " " + param["unit"] if param["value"] is not None else "由研究人员确定"
                rationale = f"。依据：{md(param['rationale'])}" if param["rationale"] else ""
                lines += [f"  - **拟定研究参数 · 待用户确认** {md(param['kind'])}：{md(value_text)}{rationale}。"]
    if value["rejected"] or value["missed_coverage"]:
        lines += ["", "## Shadow Diagnostics · 证据覆盖与拒绝", ""]
    for item in value["rejected"]:
        lines += [f"- **{md(item['id'] or item['section'])} 未采用** {md(item['reason'])}"]
    for item in value["missed_coverage"]:
        ident = item["evidence_id"]
        reason = "模型给出的原因，待复核：" if item["model_reason"] else ""
        lines += [f"- **遗漏候选** {cite([ident])} · {item['signal']}。{reason}{md(item['reason'])}。"]
    lines += ["", "## Evidence · 原始证据", ""]
    for item in pack.evidence:
        product = "、".join(md(name) for name in item.products) or "未确认"
        lines += [f"- **{item.id} / {item.source_span_id}** [原始评论]({item.source_url}) 「{md(item.text.strip())}」"
                  f" · 产品归属：{product}"]
    return "\n".join(lines) + "\n"
