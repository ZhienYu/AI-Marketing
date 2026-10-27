"""Generate an evidence-linked Markdown report entirely offline."""

import argparse
import csv
import html
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

from classify_reviews import AGENT_DIR, ClassificationError, review_fingerprint
from generate_insights import ASPECT_ORDER, generate_insights
from validate_reviews import load_reviews


def markdown(value):
    text = html.escape(str(value), quote=False).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*\[\]()|#])", r"\\\1", text)


def render_report(insights, classified, reviews, dataset="test"):
    computed = generate_insights(classified)
    if computed != insights:
        raise ClassificationError("Insights do not match classifications; regenerate matching insights first.")
    results = classified["results"]
    if not results:
        raise ClassificationError("No classified reviews available; report was not generated.")
    if dataset == "test" and insights["synthetic_records"] != len(results):
        raise ClassificationError("Test report requires entirely synthetic review data.")
    if dataset == "real" and (insights["synthetic_records"] or classified["mode"] == "mock"):
        raise ClassificationError("Synthetic/mock results cannot be used for a real report.")
    originals = {review["review_id"]: review for review in reviews}
    if len(originals) != len(reviews):
        raise ClassificationError("Source reviews contain duplicate IDs.")
    for result in results:
        original = originals.get(result["review_id"])
        if original is None or any(result.get(field) != original[field] for field in ("brand", "source_platform", "source_url")):
            raise ClassificationError("Classification evidence does not match the source CSV.")
        if result.get("input_sha256") and result["input_sha256"] != review_fingerprint(original):
            raise ClassificationError("Source review content changed since classification.")

    def evidence(aspect, polarity):
        return [row for row in results if any(
            item["aspect"] == aspect and item["sentiment"] == polarity
            for item in row["product_aspects"]
        ) and row["brand"].strip() and row["brand"].strip().casefold() != "unknown"]

    def references(rows):
        return "; ".join(f"{markdown(row['brand'])}: review_id={markdown(row['review_id'])}" for row in rows) or "无"

    totals = {
        aspect: {polarity: sum(brand["aspect_counts"][aspect][polarity] for brand in insights["brands"].values())
                 for polarity in ("Positive", "Negative", "Neutral")}
        for aspect in ASPECT_ORDER
    }
    ranked = sorted(ASPECT_ORDER, key=lambda aspect: (-totals[aspect]["Negative"], aspect))
    sentiment_counts = Counter(row["sentiment"] for row in results)
    lines = ["# Product Insight Agent — Market Research Report", ""]
    if dataset == "test":
        lines += ["> **DEMO — SYNTHETIC DATA**", "> 本报告使用合成评论，仅展示技术流程；不构成真实消费者研究或市场结论。", ""]
    lines += [
        f"成功分类样本：**{len(results)}** 条；未知品牌：{insights['unknown_brand_records']} 条；本轮失败未纳入：{insights['failed_records_excluded']} 条。",
        f"分类方式：{markdown(classified['mode'])}；模型：{markdown(classified.get('model') or '未提供')}。报告由离线模板生成，未调用模型。",
        "", "## 1. Executive Summary", "",
    ]
    findings = [aspect for aspect in ranked if totals[aspect]["Negative"]][:3]
    for index, aspect in enumerate(findings, 1):
        lines.append(f"{index}. **样本事实：{aspect}** 有 {totals[aspect]['Negative']} 条负面提及。证据：{references(evidence(aspect, 'Negative'))}。仅描述当前样本。")
    if len(findings) < 3:
        lines.append("可支持的独立发现不足三项；Insufficient Evidence，不补造结论。")
    lines += ["", "每品牌样本不足 20 条时为 Insufficient Data，不作真实市场品牌排名。原文与属性反馈见第六部分。", "", "## 2. Consumer Pain Points", "",
              "| 品牌 | 具体痛点 | 独立评论数 | review_id |", "|---|---|---:|---|"]
    for brand, data in insights["brands"].items():
        for pain in data["top_pain_points"]:
            lines.append(f"| {markdown(brand)} | {markdown(pain['feedback'])} | {pain['review_count']} | {markdown(', '.join(pain['review_ids']))} |")
    if not any(data["top_pain_points"] for data in insights["brands"].values()):
        lines.append("| — | Insufficient Evidence：没有可提取的痛点 | — | — |")
    lines += ["", "痛点文字仅合并大小写和空白差异；不把不同措辞自动当作同一个问题。属性层面的汇总见下表。", "", "## 3. Consumer Sentiment", "",
              "| 评论整体情绪 | 评论数 |", "|---|---:|"]
    for sentiment in ("Positive", "Negative", "Neutral", "Mixed"):
        lines.append(f"| {sentiment} | {sentiment_counts[sentiment]} |")
    lines += ["", "| 产品属性 | 正面评论数 | 负面评论数 | 中性评论数 | 正面证据 | 负面证据 |", "|---|---:|---:|---:|---|---|"]
    for aspect, counts in totals.items():
        lines.append(f"| {aspect} | {counts['Positive']} | {counts['Negative']} | {counts['Neutral']} | {references(evidence(aspect, 'Positive'))} | {references(evidence(aspect, 'Negative'))} |")
    lines += ["", "整体情绪与属性情绪分别统计；同一评论可涉及多个属性，也可同时有正面与负面反馈，属性列不能相加当作评论总数。未知品牌只纳入整体情绪，不进入品牌属性汇总。", "", "## 4. Competitive Intelligence", "",
              "| 品牌 | 有效分类样本量 | 比较限制 |", "|---|---:|---|"]
    for brand, data in insights["brands"].items():
        lines.append(f"| {markdown(brand)} | {data['sample_size']} | {data['comparison_status']} |")
    brands = list(insights["brands"])
    lines += ["", "每格为 **正面 / 负面** 独立评论提及次数，不能视为市场份额或品牌表现评分。", "",
              "| 产品属性 | " + " | ".join(markdown(brand) for brand in brands) + " |",
              "|---|" + "---|" * len(brands)]
    for row in insights["comparison_table"]:
        cells = [f"{row['brands'][brand]['Positive']} / {row['brands'][brand]['Negative']}" for brand in brands]
        lines.append(f"| {row['aspect']} | " + " | ".join(cells) + " |")
    lines += ["", "**零提及不代表满意，也不代表没有问题。** 小样本不支持“某品牌在真实市场最好”等结论。", "", "## 5. Business Opportunities", ""]
    candidates = [aspect for aspect in ranked if totals[aspect]["Negative"] >= 2][:3]
    if not candidates:
        lines += ["Insufficient Evidence：没有至少两条独立评论支持的属性痛点，不生成具体商业建议；需补充获准的真实评论及访谈验证。"]
    for index, aspect in enumerate(candidates, 1):
        lines += [
            f"### {index}. 待验证方向：{aspect}", "",
            f"- **数据事实：** 当前样本有 {totals[aspect]['Negative']} 条相关负面评论。证据：{references(evidence(aspect, 'Negative'))}。",
            f"- **分析假设：** 在真实用户中验证 {aspect} 反馈是否反复出现，再评估相关产品改进或说明材料是否有帮助；尚无购买意愿、销量或投资回报证据。",
            "- **下一步验证：** 获取获准的真实评论并访谈目标用户，核对具体场景、复现问题，再测试改进方案；当前不建议据此直接投入产品或营销预算。", "",
        ]
    if dataset == "test":
        lines += ["以上方向只是合成数据上的演示假设，不是已发现的真实市场机会。", ""]
    lines += ["## 6. Sources & Methodology", "",
              "- 输入为配对的 insights JSON、分类 JSON 和原始 CSV；生成前重新汇总分类，并逐项核对统计一致性。",
              "- 只使用成功分类记录。每条评论对同一属性、同一情绪最多计数一次；同一属性的正负反馈可各计一次。",
              "- 品牌来自 CSV，不由报告猜测。有效样本量为该品牌成功分类的评论数；不代表市场覆盖率或代表性。",
              "- 原始 CSV 用于核对 ID、品牌、来源；已有输入指纹时还核对整行内容。",
              "- 未提供的来源链接不补写。下列原文只是本地证据，synthetic 不是外部消费者来源。",
              "- Mock 为人工预置分类，不是模型分析；Qwen 分类也可能出错，需要人工复核。相对品牌比较不代表绝对产品表现。",
              "- 不足 20 条的品牌默认 Insufficient Data；该阈值是项目展示规则，不是统计显著性保证。", "",
              "- 机会方向仅选至少两条独立负面评论提及的标准属性，最多三项；这只是演示筛选规则，不证明商业价值。", "",
              "### 原始反馈与证据索引", "",
              "| review_id | 品牌 | 来源平台 | 原始评论 | 属性反馈（分类结果） | source_url |", "|---|---|---|---|---|---|"]
    for result in results:
        original = originals[result["review_id"]]
        feedback = "; ".join(f"{item['aspect']} — {item['sentiment']}: {item['feedback']}" for item in result["product_aspects"])
        lines.append("| " + " | ".join(markdown(value) for value in (
            result["review_id"], result["brand"], result["source_platform"], original["review_text"], feedback,
            original["source_url"] or "未提供（无外部引用链接）",
        )) + " |")
    return "\n".join(lines) + "\n"


def save_report(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("test", "real"), default="test")
    parser.add_argument("--insights", type=Path)
    parser.add_argument("--classifications", type=Path)
    parser.add_argument("--reviews", type=Path)
    arguments = parser.parse_args(argv)
    directory = AGENT_DIR / "outputs" / arguments.dataset
    if arguments.dataset == "real" and not all((arguments.insights, arguments.classifications, arguments.reviews)):
        parser.error("Real reports require explicit --insights, --classifications and --reviews paths")
    paths = (
        arguments.insights or directory / "insights_mock.json",
        arguments.classifications or directory / "classification_mock.json",
        arguments.reviews or AGENT_DIR / "data" / "sample_reviews.csv",
    )
    output = directory / "market_research_report.md"
    try:
        if any(path.resolve() == output.resolve() for path in paths):
            raise ClassificationError("Report output cannot overwrite an input.")
        insights = json.loads(paths[0].read_text(encoding="utf-8"))
        classified = json.loads(paths[1].read_text(encoding="utf-8"))
        _, reviews = load_reviews(paths[2])
        content = render_report(insights, classified, reviews, arguments.dataset)
        source_note = "\n".join(f"- {label}文件：{markdown(path.name)}" for label, path in zip(("统计", "分类", "原始评论"), paths))
        content = content.replace("## 6. Sources & Methodology\n", "## 6. Sources & Methodology\n\n" + source_note + "\n", 1)
        save_report(output, content)
    except FileNotFoundError:
        print("Missing input: provide matching insights JSON, classifications JSON and source CSV. Run the offline Mock pipeline first.", file=sys.stderr)
        return 2
    except ClassificationError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError, csv.Error):
        print("Invalid report input or output permission; check JSON/CSV structure. No classification file was changed.", file=sys.stderr)
        return 2
    print(f"Saved offline Markdown report to Agent/outputs/{arguments.dataset}/{output.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
