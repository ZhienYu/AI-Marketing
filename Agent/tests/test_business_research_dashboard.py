from dataclasses import replace
import re
import unittest

from business_report_view import CommentSource, ReportItem, ReportTopic
from business_research_dashboard import dashboard_markup, _display_text, _price_rows
from business_research_preview import build_preview, synthetic_samples


class BusinessResearchDashboardTests(unittest.TestCase):
    def test_modes_do_not_confuse_simulated_and_real_sources(self):
        report = build_preview(synthetic_samples())
        synthetic = dashboard_markup(report, mode="synthetic")
        self.assertIn("合成示例 · 模拟分析 · 预览输入 12 条", synthetic)
        self.assertNotIn("采集评论", synthetic)
        self.assertNotIn("youtube.com/watch", synthetic)
        self.assertNotIn("第一页公开顶层评论", synthetic)
        historical = dashboard_markup(report, mode="historical")
        self.assertIn("历史真实评论 · 模拟分析", historical)
        self.assertIn("历史原文样本", historical)
        self.assertIn("youtube.com/watch", historical)
        self.assertNotIn("Qwen 自动分析", historical)
        self.assertIn("真实 YouTube 评论 · Qwen 自动分析", dashboard_markup(report, mode="live"))

    def test_topic_and_evidence_links_keep_original_counts_and_escape_content(self):
        report = build_preview(synthetic_samples())
        original = report.sources[0]
        poisoned = CommentSource(original.label, original.video_id, original.comment_id,
                                 "<script>alert(1)</script>", "", original.analysis_status)
        view = replace(report, sources=(poisoned, *report.sources[1:]))
        markup = dashboard_markup(view, mode="synthetic")
        self.assertNotIn("<script>alert", markup)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", markup)
        self.assertIn('data-evidence="S01"', markup)
        self.assertIn('id="source-s01"', markup)
        self.assertIn("对应分析", markup)
        for index, group in enumerate(report.topic_groups, 1):
            self.assertIn(f'data-topic="research-topic-{index}"', markup)
            self.assertEqual(len(group.parent.sources), len({ref for child in group.children for ref in child.sources}))

    def test_subtopics_link_to_matching_cards_or_keep_evidence_only(self):
        report = build_preview(synthetic_samples())
        specific = ReportItem("可核对的发现", "评论者明确描述实际问题。", ("S01",))
        placeholder = ReportItem("归类线索", "展开来源查看消费者描述。", ("S02",))
        excerpt = ReportItem("另一条线索", "原文示例 「The fit is loose.」", ("S02",))
        children = (ReportItem(specific.title, "", specific.sources),
                    ReportItem(placeholder.title, "", placeholder.sources),
                    ReportItem(specific.title, "", ("S03",)))
        group = ReportTopic(ReportItem("主题", "", ("S01", "S02", "S03")), children)
        view = replace(report, needs=(specific, placeholder, excerpt), topic_groups=(group,))
        markup = dashboard_markup(view, mode="synthetic")
        self.assertNotIn("<summary>对应洞察</summary>", markup)
        self.assertNotIn(placeholder.detail, markup)
        self.assertIn("The fit is loose.", markup)
        self.assertIn("原文线索 · 2 项", markup)
        panel = markup.split('id="research-topic-1"', 1)[1].split("</ul>", 1)[0]
        self.assertEqual(panel.count('href="#finding-needs-1"'), 1)
        self.assertIn('href="#source-s03"', panel)
        for target in re.findall(r'href="#(finding-[^"]+)" data-finding', markup):
            self.assertEqual(markup.count(f'id="{target}"'), 1)

    def test_executive_uses_mode_and_independent_video_coverage(self):
        report = build_preview(synthetic_samples())
        findings = (
            ReportItem("第一条观察", "使用自述", ("S01",)),
            ReportItem("第二条观察", "同一评论的不同反馈", ("S01",)),
            ReportItem("第三条观察", "另一条评论", ("S02",)),
        )
        report = replace(report, summary=findings)
        historical = dashboard_markup(report, mode="historical")
        self.assertIn("本轮观察", historical)
        self.assertIn("引用的历史评论 <strong>2</strong>", historical)
        self.assertIn("观察数 <strong>3</strong>", historical)
        self.assertIn("获多条评论支持的观察 <strong>0</strong>", historical)
        self.assertIn("引用评论来自的视频 <strong>1</strong>", historical)
        self.assertIn("S01 支持 2 条观察，按一条评论计。", historical)
        self.assertIn("同一视频中的评论共享讨论背景", historical)
        self.assertLess(historical.index("证据说明"), historical.index("本轮观察"))
        self.assertIn('<details class="rd-more"><summary>证据标签说明</summary>', historical)
        synthetic = dashboard_markup(report, mode="synthetic")
        self.assertIn("引用的合成评论 <strong>2</strong>", synthetic)
        self.assertNotIn("引用评论来自的视频", synthetic)
        self.assertIn("值得进一步关注", synthetic)
        live = dashboard_markup(report, mode="live")
        self.assertIn("引用的去重评论 <strong>2</strong>", live)

    def test_prices_require_three_traceable_records_and_keep_currency_unknown(self):
        report = build_preview(synthetic_samples())
        rows, covered = _price_rows(report.purchase, report.sources)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(covered)
        self.assertTrue(any(row[1] == "$89" and row[2] == "未注明（$）" for row in rows))
        self.assertTrue(any(row[2] == "USD" and row[4].casefold() == "canada" for row in rows))
        rendered = dashboard_markup(report, mode="synthetic")
        self.assertIn("评论中的价格对照", rendered)
        self.assertIn("展开价格条目说明", rendered)
        budget = next(item for item in report.purchase if item.title == "明确预算上限")
        fake = replace(budget, detail="评论者明确表示最多支出 $1（原文金额）。")
        self.assertFalse(_price_rows((fake,), report.sources)[0])
        sparse = dashboard_markup(replace(report, purchase=(budget,)), mode="synthetic")
        self.assertNotIn("评论中的价格对照", sparse)
        self.assertIn("明确预算上限", sparse)

    def test_money_display_preserves_the_source_currency_and_amount(self):
        self.assertEqual(_display_text("Atlas · Canada · 70 usd", regional=True), "Atlas · 加拿大 · USD 70")
        self.assertEqual(_display_text("评论者报价：$ 1,099.50。"), "评论者报价：$1,099.50。")
        self.assertEqual(_display_text("Atlas · Unknown district · EUR 70", regional=True),
                         "Atlas · Unknown district · EUR 70")
