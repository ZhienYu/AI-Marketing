from dataclasses import replace
import unittest

from business_report_view import CommentSource
from business_research_dashboard import dashboard_markup, _display_text
from business_research_preview import build_preview, synthetic_samples


class BusinessResearchDashboardTests(unittest.TestCase):
    def test_modes_do_not_confuse_simulated_and_real_sources(self):
        report = build_preview(synthetic_samples())
        synthetic = dashboard_markup(report, mode="synthetic")
        self.assertIn("合成示例评论 <strong>12</strong>", synthetic)
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

    def test_money_display_preserves_the_source_currency_and_amount(self):
        self.assertEqual(_display_text("Atlas · Canada · 70 usd", regional=True), "Atlas · 加拿大 · USD 70")
        self.assertEqual(_display_text("评论者报价：$ 1,099.50。"), "评论者报价：$1,099.50。")
        self.assertEqual(_display_text("Atlas · Unknown district · EUR 70", regional=True),
                         "Atlas · Unknown district · EUR 70")
