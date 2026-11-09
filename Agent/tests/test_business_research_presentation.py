import json
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

import business_research_preview as preview
from business_research_presentation import describe_evidence, purchase_groups, upgrade_phase_k
from business_report_view import BusinessReportView, CommentSource, ReportItem


def source(label):
    return CommentSource(label, "demoVideo01", "synthetic-" + label, "Synthetic source", "", "exploratory")


class BusinessResearchPresentationTests(unittest.TestCase):
    def test_topics_union_counts_and_distinct_feedback_types(self):
        notes = (
            ReportItem("听音乐时断音", "明确描述了听歌中断。", ("S01", "S02"), "使用自述 · 探索性"),
            ReportItem("通话质量反馈", "朋友说通话质量不佳。", ("S02",), "转述他人反馈"),
            ReportItem("佩戴贴合感", "不喜欢佩戴时的感觉。", ("S02",), "使用自述 · 探索性"),
        )
        topics = (*notes, ReportItem("连接与软件体验", "", ("S01",)))
        view = upgrade_phase_k(BusinessReportView("Earbuds", False, (source("S01"), source("S02")), needs=notes), topics)
        group = next(group for group in view.topic_groups if group.parent.title == "音频与连接")
        self.assertEqual(set(group.parent.sources), {"S01", "S02"})
        self.assertEqual(len(group.children), 3)
        self.assertEqual({item.title: len(item.sources) for item in view.information_types},
                         {"亲身使用问题": 2, "第三方转述": 1})
        self.assertFalse(view.scenarios)
        self.assertTrue(any(item.title == "通话质量反馈" and item.badge.startswith("转述")
                            for item in view.needs))
        self.assertTrue(all(item.business_meaning for item in view.summary))

    def test_pricing_roles_remain_distinct(self):
        items = tuple(ReportItem(title, "", ("S01",)) for title in (
            "明确预算上限", "简单询价", "地区报价", "购买成交价", "价格评价", "使用功能前是否需要付费订阅",
        ))
        groups = dict(purchase_groups(items))
        self.assertEqual([item.title for item in groups["预算与询价"]], ["明确预算上限", "简单询价"])
        self.assertEqual([item.title for item in groups["报价、成交价与价值判断"]],
                         ["地区报价", "购买成交价", "价格评价"])
        self.assertIsNone(describe_evidence("价格与预算", "选购评价", "Price 90 dollars."))

    def test_report_is_ungrouped_across_independent_product_mentions(self):
        mentions = (ReportItem("Atlas", "当前使用", ("S01",), "原文产品提及"),
                    ReportItem("Nova", "已购买", ("S02",), "原文产品提及"))
        view = upgrade_phase_k(BusinessReportView("Earbuds", False, (source("S01"), source("S02")),
                                                 competitors=mentions), ())
        self.assertEqual([item.badge for item in view.competitors], ["原文使用自述", "原文购买自述"])
        self.assertFalse(view.scenarios)
        self.assertFalse(view.opportunities)

    def test_synthetic_preview_keeps_specific_findings_and_research_separate(self):
        before = preview.build_preview(preview.synthetic_samples(), upgraded=False)
        after = preview.build_preview(preview.synthetic_samples())
        self.assertEqual(before.coverage, after.coverage)
        refs = {source.comment_id: source.label for source in after.sources}
        self.assertEqual(set(next(item for item in after.summary if item.title == "听音乐时断音").sources),
                         {refs["mock-1"], refs["mock-2"]})
        self.assertTrue(1 <= len(after.summary) <= 3)
        self.assertTrue(all(item.business_meaning for item in after.summary))
        direction = next(item for item in after.opportunities if item.title == "说清功能使用条件")
        self.assertEqual(set(direction.sources), {refs["mock-4"], refs["mock-5"]})
        self.assertIn("不能证明需要付费", direction.evidence_limit)
        self.assertTrue(direction.observation and direction.business_meaning)
        self.assertTrue(any(item.title == "购买成交价" for item in after.purchase))
        self.assertTrue(any(item.title == "连接手机听歌" for item in after.scenarios))
        self.assertNotIn("连接手机听歌", {item.title for item in after.purchase})
        self.assertFalse(any(item.badge == "原文对比" for item in after.competitors))
        choice = next(item for item in after.competitors if item.badge == "原文选购候选")
        quote = next(item for item in after.purchase if item.title.endswith("候选对照"))
        self.assertEqual(choice.sources, quote.sources)
        self.assertIn("$89 / $69", quote.detail)
        self.assertNotIn("$89 / $69", choice.detail)

    def test_history_requires_local_manifest_and_valid_archive_retention(self):
        with TemporaryDirectory() as root:
            runtime = Path(root)
            row = {"comment_id": "synthetic-local-id", "video_id": "testVideo01",
                   "review_text": "What does this model cost?"}
            archive = runtime / "fixture.json"
            def write_archive(expiry):
                archive.write_text(json.dumps({"delete_by": expiry, "rows": [row]}))
            write_archive("2099-01-01T00:00:00+00:00")
            self.assertEqual(preview.historical_samples(runtime), [])
            manifest = runtime / "phase_k_preview_sources.json"
            request = {row["comment_id"]: ["Purchase Inquiry", "unknown", "unknown"]}
            manifest.write_text(json.dumps({"../fixture.json": request}))
            self.assertEqual(preview.historical_samples(runtime), [])
            manifest.write_text(json.dumps({"fixture.json": request}))
            self.assertEqual(len(preview.historical_samples(runtime)), 1)
            write_archive("2000-01-01T00:00:00+00:00")
            self.assertEqual(preview.historical_samples(runtime), [])

    def test_streamlit_renders_synthetic_report_without_external_links(self):
        path = Path(preview.__file__)
        app = AppTest.from_file(str(path)).run()
        app.radio[0].set_value("全合成示例").run()
        self.assertFalse(app.exception)
        html = "".join(node.value for node in app.get("html"))
        self.assertIn('id="scenarios-title">消费者使用场景', html)
        self.assertIn('id="opportunities-title">研究启示与商业机会', html)
        self.assertIn("全合成评论 · 模拟分析", html)
        self.assertNotIn("youtube.com/watch", html)
