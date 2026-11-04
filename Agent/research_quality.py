"""Human-authored synthetic research corpus and evidence-led specialist reports.

Refined attributes are a research sidecar; legacy API/checkpoint schemas stay intact.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import mkdtemp

from classify_reviews import CLASSIFICATION_FIELDS, ClassificationError, analyze_batch, save_json
from generate_report import markdown as md, save_report
from qualify_feedback import qualify_batch
from validate_reviews import REQUIRED_COLUMNS, load_reviews

NAV = "Navigation & Obstacle Handling"
ATTRIBUTES = (NAV, "Reliability", "Battery Life", "Cleaning Performance", "Maintenance", "Price", "Customer Support", "Ease of Use", "Other")
# Editorial hypotheses and experiments, never assertions of observed demand.
EDITORIAL = {
    NAV: ("导航与避障", "障碍区卡住或需要人工救援", "减少障碍区的人工干预可能有价值", "先验证台阶识别与脱困，再决定是否调整导航", "按台阶尺寸、缆线布局分组，记录脱困成功率和人工救援次数"),
    "Reliability": ("可靠性", "运行期间发生硬件或持续性故障", "持续运行与维修可预期性可能影响体验", "先排查故障模式，不将导航卡住混作硬件失效", "复现故障、记录运行时长与维修原因"),
    "Battery Life": ("续航", "部分使用场景下续航不足", "清洁任务完整完成可能比标称续航更重要", "比较不同面积与清洁周期下的续航需求", "固定面积、模式和电池状态，观察一次任务完成率"),
    "Cleaning Performance": ("清洁效果", "清洁表现出现正反反馈", "不同污物条件下的稳定效果可能值得验证", "按污物类型分层验证，避免笼统性能承诺", "在相同落叶/碎屑条件下对照测试残留量"),
    "Maintenance": ("维护", "滤网拆装体验不同", "降低清理维护负担可能有价值", "测试滤网取出与清洗流程", "观察拆装用时、出错点和用户操作负担"),
    "Price": ("价格与持有成本", "耗材成本被提及", "全生命周期成本透明度可能值得探索", "先核对耗材成本和用户敏感度", "访谈耗材使用频率并测试成本说明是否帮助理解"),
    "Customer Support": ("售后支持", "售后进度信息不足", "维修状态可见性可能值得探索", "测试进度通知方案", "访谈维修用户，观察信息需求和通知理解度"),
    "Ease of Use": ("易用性", "设置和操作体验", "简化首次设置可能有帮助", "先观察真实设置流程", "记录任务用时和求助点"),
    "Other": ("其他", "具体反馈待进一步归类", "证据不足", "进一步访谈", "核对反馈目标及场景"),
}


def validate_annotations(annotations, originals, results, qualified):
    if not isinstance(annotations, dict) or set(annotations) - set(results):
        raise ClassificationError("Invalid research annotation IDs.")
    for rid, value in annotations.items():
        if not isinstance(value, dict) or set(value) != {"attribute", "scenario_quote", "explicit_need_quote", "origin"}:
            raise ClassificationError("Invalid research annotation schema.")
        if value["attribute"] not in ATTRIBUTES or value["origin"] != "human_mock":
            raise ClassificationError("Unsupported attribute or annotation origin.")
        if not qualified.get(rid, {}).get("eligible_as_usage_review"):
            raise ClassificationError("Unqualified annotation evidence.")
        for key in ("scenario_quote", "explicit_need_quote"):
            quote = value[key]
            if quote is not None and (not isinstance(quote, str) or not quote.strip() or quote not in originals[rid]["review_text"]):
                raise ClassificationError("Unverified scenario or explicit need quote.")
        if value["explicit_need_quote"] and not re.search(r"\bI (?:need|want|wish|require)\b", value["explicit_need_quote"], re.IGNORECASE):
            raise ClassificationError("Explicit needs require a direct need expression, not inferred dissatisfaction.")
        legacy = "Reliability" if value["attribute"] == NAV else value["attribute"]
        if {legacy} != {item["aspect"] for item in results[rid]["product_aspects"]}:
            raise ClassificationError("Refined attribute contradicts legacy classification.")
        if value["attribute"] == NAV and not any(word in originals[rid]["review_text"].casefold() for word in ("step", "ladder", "cable", "obstacle", "navigation", "stuck", "tangled")):
            raise ClassificationError("Navigation refinement has no supporting text.")


def evidence_groups(research, classified):
    groups = defaultdict(lambda: {"Positive": set(), "Negative": set(), "Neutral": set(), "scenarios": defaultdict(set), "explicit": set(), "brands": defaultdict(lambda: defaultdict(set))})
    for row in classified["results"]:
        rid = row["review_id"]
        ann = research.get("annotations", {}).get(rid)
        for aspect in row["product_aspects"]:
            attribute = ann["attribute"] if ann else aspect["aspect"]
            if not ann and attribute == "Reliability" and any(word in aspect["feedback"].casefold() for word in ("stuck", "obstacle", "navigation", "tangled")):
                attribute = NAV
            group = groups[attribute]
            group[aspect["sentiment"]].add(rid)
            group["brands"][row["brand"]][aspect["sentiment"]].add(rid)
            if ann and ann["scenario_quote"]:
                group["scenarios"][ann["scenario_quote"]].add(rid)
            if ann and ann["explicit_need_quote"]:
                group["explicit"].add(rid)
    return groups


def render_specialist(purpose, research, classified, reviews):
    from consumer_needs import PURPOSES
    if purpose not in PURPOSES or classified.get("mode") != "mock" or any(r.get("source_platform") != "synthetic" for r in reviews):
        raise ClassificationError("Specialist reports accept synthetic Mock inputs only.")
    originals = {r["review_id"]: r for r in reviews}
    rows = classified["results"]
    refs = {r["review_id"]: f"E{index:02d}" for index, r in enumerate(rows, 1)}
    def cite(ids):
        return ", ".join(f"[{refs[rid]}](#{refs[rid].lower()})" for rid in sorted(ids)) or "—"
    groups = evidence_groups(research, classified)
    ordered = sorted(groups, key=lambda a: (-len(groups[a]["Negative"]), a))
    lines = ["# " + PURPOSES[purpose], "", "> **DEMO — SYNTHETIC DATA** · 全部为虚构评论、人工分类与人工 Mock 推断；本次没有 AI 推理或真实消费者研究。", "",
             "## Executive Summary", "",
             f"本次成功分类 {len(rows)} 条自述使用反馈；需求标注覆盖 {research['coverage']['needs_reviewed']} 条。购买咨询、视频反馈和歧义不进入产品好坏统计。",
             "Insufficient Data：所有结论仅用于验证报告方法；样本少且非随机，不能推出需求规模、市场排名、销量或 ROI。", ""]
    if purpose == "improvement":
        for attribute in [a for a in ordered if groups[a]["Negative"]][:3]:
            group = groups[attribute]
            title, pain, need, direction, experiment = EDITORIAL[attribute]
            contexts = "; ".join(scene for scene, ids in group["scenarios"].items() if ids & group["Negative"]) or "场景尚未明确"
            lines.append(f"- **{title}的研究线索**：负面反馈涉及 {md(contexts)}；{len(group['Negative'])} 条负面、{len(group['Positive'])} 条正面，明确需求自述 {len(group['explicit'])} 条。**待验证价值：** {need}；先用场景复现区分产品问题与使用条件。{cite(group['Negative'] | group['Positive'])}")
        lines += ["", "## 研究建议", "", "先复现反复出现的问题，再访谈需求的重要性与现有替代方案；用小规模原型测试决定是否继续投入。排序仅按当前样本问题提及数，未估计严重度、成本或市场机会大小。", "", "## 从使用场景到验证：需求分析链", ""]
        for attribute in ordered:
            group = groups[attribute]
            if not group["Negative"]:
                continue
            title, pain, need, direction, experiment = EDITORIAL[attribute]
            support = group["Negative"]
            scenarios = "; ".join(f"{key}（{len(ids & support)} 条）" for key, ids in group["scenarios"].items() if ids & support) or "原文未明确，不能补写使用场景"
            explicit = [originals[rid]["review_text"] for rid in sorted(group["explicit"] & support)]
            label = "单条反馈支持的探索性假设，证据不足" if len(support) == 1 else "多条样本线索，仍不是可靠商业机会"
            lines += [f"### {title}：{label}", "",
                      f"**使用场景 → 具体痛点：** {md(scenarios)} → {pain}。当前 {len(support)} 条负面提及；不是已核实的发生率。{cite(support)}",
                      f"**需求：** 明确表达需求的记录 {len(group['explicit'] & support)} 条；逐字需求见附录。其余潜在需求为**人工 Mock 推断**：{need}。不能把全部痛点人数算成明确需求人数。",
                      f"**潜在改进方向 → 验证：** {direction} → {experiment}。",
                      f"**反证与不确定性：** 同属性正面反馈 {len(group['Positive'])} 条 {cite(group['Positive'])}；场景/操作差异和反馈真实性未验证，不确定能否复现或改善购买决策。", ""]
        if not any(g["Negative"] for g in groups.values()):
            lines.append("Insufficient Evidence：没有有依据的痛点，不生成改进机会。")
    else:
        brands = Counter(row["brand"] for row in rows if row["brand"].strip().casefold() != "unknown")
        comparisons = []
        for attribute in ordered:
            group = groups[attribute]
            shared = [(scene, {rid for rid in ids if originals[rid]["brand"] in brands}) for scene, ids in group["scenarios"].items() if len({originals[rid]["brand"] for rid in ids if originals[rid]["brand"] in brands}) >= 2]
            if shared:
                comparisons.append((attribute, shared))
        for attribute, shared in comparisons[:3]:
            scene, ids = shared[0]
            descriptions = []
            directions = set()
            for brand in sorted(brands):
                selected = {rid for rid in ids if originals[rid]["brand"] == brand}
                if selected:
                    pos, neg = len(selected & groups[attribute]["Positive"]), len(selected & groups[attribute]["Negative"])
                    descriptions.append(f"{brand} 正{pos}/负{neg}")
                    directions.add((bool(pos), bool(neg)))
            interpretation = "认知方向存在不同，可作为对照验证线索，不能作为品牌优势主张" if len(directions) > 1 else "方向一致，未形成品牌差异证据；应先研究共同场景需求"
            lines.append(f"- **{EDITORIAL[attribute][0]} · {md(scene)}**：{'；'.join(descriptions)}。{interpretation}。{cite(ids)}")
        if not comparisons:
            lines.append("- 无共同场景的可比较证据，无法进行可靠竞品比较。")
        lines += ["", "## 研究建议", "", "围绕共同场景设计同条件对照试验，再判断潜在差异是否可重复；未观察到某品牌的问题不代表该品牌没有问题。", "", "## 品牌覆盖", "", "| 有样本品牌 | 自述使用样本 | 比较限制 |", "|---|---:|---|"]
        for brand, count in sorted(brands.items()):
            lines.append(f"| {md(brand)} | {count} | Insufficient Data |")
        lines += [f"未知品牌记录 {sum(r['brand'].casefold() == 'unknown' for r in rows)} 条，仅保留问题线索，不用于品牌比较。", "", "## 相同功能维度：样本反馈矩阵", "", "每格为正面 / 负面独立评论数；整体属性提及基数另列，不是满意率。Mixed 可同时贡献一次正面和负面。", "", "| 功能维度 | " + " | ".join(md(b) for b in sorted(brands)) + " |", "|---|" + "---|" * len(brands)]
        for attribute in ordered:
            group = groups[attribute]
            cells = []
            for brand in sorted(brands):
                polarities = group["brands"].get(brand, {})
                positive, negative = polarities.get("Positive", set()), polarities.get("Negative", set())
                ids = set().union(*polarities.values()) if polarities else set()
                cells.append(f"{len(positive)} / {len(negative)}；n={len(ids)} {cite(ids)}")
            lines.append(f"| {md(attribute)} | " + " | ".join(cells) + " |")
        lines += ["", "## 消费者认知差异与潜在差异化方向", ""]
        for attribute, shared in comparisons:
            lines += ["### " + EDITORIAL[attribute][0], ""]
            any_difference = False
            for scene, ids in shared:
                cells = []
                directions = set()
                for brand in sorted(brands):
                    selected = {rid for rid in ids if originals[rid]["brand"] == brand}
                    if selected:
                        directions.add((bool(selected & groups[attribute]['Positive']), bool(selected & groups[attribute]['Negative']), bool(selected & groups[attribute]['Neutral'])))
                        cells.append(f"{brand}：正面 {len(selected & groups[attribute]['Positive'])}、负面 {len(selected & groups[attribute]['Negative'])}，n={len(selected)} {cite(selected)}")
                different = len(directions) > 1
                any_difference = any_difference or different
                note = "存在正反方向不同的自述线索，不是可证明的品牌优势" if different else "方向一致，未观察到品牌认知差异"
                lines.append(f"- **共同场景 {md(scene)} 的样本认知：** " + "；".join(cells) + f"。{note}；未控制产品版本、使用条件或样本选择。")
            hypothesis_label = "人工 Mock 差异化假设" if any_difference else "共同需求研究问题（非差异化机会）"
            lines += [f"- **{hypothesis_label}：** {EDITORIAL[attribute][2]}；此方向为人工编写的待验证解释，不证明某品牌独有优势。", f"- **验证问题：** {EDITORIAL[attribute][4]}，核实是否存在可重复的差异。", ""]
        if not comparisons:
            lines += ["保留研究问题：能否取得相同使用场景、相同功能维度的多品牌反馈，并通过同条件复现验证？不输出品牌差异或排名。"]
        lines += ["小样本无法进行可靠竞品比较；上表只用于发现应进一步核实的问题。"]
    lines += ["", "## Evidence Appendix", "", "### Sources & Methodology", "",
              "正文 E 编号仅为本地合成证据索引，不是 YouTube 评论 ID。synthetic: 前缀明确标识虚构记录；旧 youtube:pipeline-* 也是旧合成样例编号，绝非真实 YouTube 评论。",
              "分类、聚类属性和场景为人工测试标注；数量由代码汇总。推断来源为 human_mock，没有模型生成的需求结论。旧字段 ai_inference 仅为兼容字段，在本报告解释为人工 Mock 推断。raw_feedback 指逐字合成自述。",
              "Navigation & Obstacle Handling 指导航、台阶、障碍与缠绕；Reliability 指硬件失效等一般故障。前者在旧分类结构映射为 Reliability，扩展标签独立保存，不改旧模型提示词或旧检查点。",
              "同评论/同属性/同情绪只计一次，属性两极反馈允许各计一次；聚类只按人工标准属性，场景只按完全相同的标注引句分组，不执行自动语义聚类。共同场景是可比线索，不是受控试验。",
              "需求/建议不从负面数量推导销量或付费意愿。单条需求可形成探索性假设，必须标证据不足。所有品牌不足 20 条的阈值仅为项目提示，不是统计显著性标准。",
              "生成前复用原报告对原文、ID、品牌、输入指纹和属性统计的一致性校验；需求结论和引句重新校验。没有附加通用报告。", ""]
    qualification = research["qualification"]
    if qualification.get("summary"):
        q = qualification["summary"]
        lines += [f"资格筛选：输入 {q['total_records']} 条；使用体验候选 {q['usage_review_candidates']} 条；购买咨询 {q['purchase_inquiries']} 条；视频内容反馈 {q['content_feedback']} 条；无关/不明确 {q['irrelevant_or_unclear']} 条。类别可重叠，不能相加为总样本。", ""]
    for row in rows:
        rid = row["review_id"]
        ann = research.get("annotations", {}).get(rid, {})
        lines += [f"<a id=\"{refs[rid].lower()}\"></a>", f"### {refs[rid]} · {md(rid)} · {md(row['brand'])}", "",
                  "**合成原文（非外部消费者证据）：** " + md(originals[rid]["review_text"]),
                  "**来源：** synthetic，本地人工样例，无真实 source_url。",
                  "**明确表达需求（逐字）：** " + md(ann.get("explicit_need_quote") or "未明确表达，不补写"),
                  "**属性 / 情绪：** " + md("; ".join(f"{ann.get('attribute', item['aspect'])}: {item['sentiment']}" for item in row["product_aspects"])), ""]
    excluded = [r for r in qualification["results"] if r["review_id"] not in refs]
    if excluded:
        lines += ["### 未纳入产品体验分析的记录", "", "| 合成编号 | 原文 | 筛选类型 / 状态 |", "|---|---|---|"]
        for row in excluded:
            lines.append("| " + " | ".join(md(v) for v in (row["review_id"], originals[row["review_id"]]["review_text"], row["primary_type"] + " / " + row["qualification_status"])) + " |")
    spaced = []
    for line in lines:
        spaced.append(line)
        if line.startswith("**"):
            spaced.append("")
    return "\n".join(spaced) + "\n"


def run_expanded(purpose="both", *, output_root=None):
    from consumer_needs import FIELDS, PURPOSES, render_research_report, research_insights
    if purpose not in (*PURPOSES, "both"):
        raise ClassificationError("Unsupported research purpose.")
    fixture = json.loads((Path(__file__).parent / "tests/fixtures/research_quality_synthetic.json").read_text())
    if fixture.get("is_synthetic") is not True:
        raise ClassificationError("Explicit synthetic corpus required.")
    reviews, labels, annotations = [], {}, {}
    for index, (brand, text, attribute, polarity, scenario, explicit) in enumerate(fixture["cases"], 1):
        rid = f"synthetic:needs-{index:03d}"
        reviews.append({"review_id": rid, "review_text": text, "source_platform": "synthetic", "source_url": "", "brand": brand})
        if attribute:
            polarities = ["Positive", "Negative"] if polarity == "Mixed" else [polarity]
            labels[rid] = {"review_text": text, "classification": {"sentiment": polarity,
                "positive_aspects": [text] if "Positive" in polarities else [], "pain_points": [text] if "Negative" in polarities else [],
                "product_aspects": [{"aspect": "Reliability" if attribute == NAV else attribute, "sentiment": p, "feedback": text} for p in polarities]}}
            annotations[rid] = {"attribute": attribute, "scenario_quote": scenario, "explicit_need_quote": explicit, "origin": "human_mock"}
    root = Path(output_root) if output_root is not None else Path(__file__).parent / "outputs/test/pipeline"
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="quality-", dir=root))
    source = directory / "synthetic_reviews.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader(); writer.writerows(reviews)
    validation, reviews = load_reviews(source)
    qualification = qualify_batch([{**r, "is_synthetic": True} for r in reviews], catalog=fixture["catalog"])
    qualified = {r["review_id"]: r for r in qualification["results"]}
    selected = [r for r in reviews if qualified[r["review_id"]]["eligible_as_usage_review"] and r["review_id"] in labels]
    # A fixture brand is not trusted over qualification (ambiguous targets stay unknown).
    for row in selected:
        row["brand"] = qualified[row["review_id"]]["brand"]
    classified = analyze_batch(selected, validation, "mock", "offline-fixtures", directory / "classifications.json", fixtures=labels)
    envelopes = {}
    selected_annotations = {}
    for row in classified["results"]:
        rid = row["review_id"]
        selected_annotations[rid] = annotations[rid]
        fields = {f: [] for f in FIELDS}
        if annotations[rid]["explicit_need_quote"]:
            quote = annotations[rid]["explicit_need_quote"]
            fields["unmet_needs"] = [{"text": quote, "claim_type": "raw_feedback", "quote": quote,
                "uncertainty": "Synthetic self-report, not verified demand.", "validation_step": "Interview and reproduce before investment."}]
        envelopes[rid] = {"classification": {k: row[k] for k in CLASSIFICATION_FIELDS}, "consumer_needs": fields}
    research = research_insights(classified, reviews, envelopes, qualification, annotations=selected_annotations)
    save_json(directory / "qualification.json", qualification)
    save_json(directory / "consumer_needs.json", research)
    paths = []
    for name in PURPOSES if purpose == "both" else (purpose,):
        path = directory / (name + "_research_report.md")
        save_report(path, render_research_report(name, research, classified, reviews))
        paths.append(path)
    return paths
