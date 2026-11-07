import unittest

from commercial_insights import competitor_evidence
from evidence_analysis import evidence_spans
from multi_comment_research import render_consumer_report


def row(ident, text, facts=()):
    spans = evidence_spans(text)
    return {"review_id": ident, "review_text": text, "source_url": f"https://www.youtube.com/watch?lc={ident}",
            "processing": {"status": "Partial", "raw": {"facts": list(facts)}, "evidence_spans": spans,
                           "claim_quality": [{"path": ["facts", i], "status": "Needs Review",
                                              "evidence_ids": ["S01"]} for i, _ in enumerate(facts)]}}


def state(rows):
    return {"results": rows, "selected_sources": rows, "collected": len(rows), "selected": len(rows),
            "selected_videos": 2, "submitted": len(rows), "failures": [], "unprocessed": 0}


def scan(rows, focus=()):
    return competitor_evidence(state(rows), focus, lambda source: False)


class CommercialInsightsTests(unittest.TestCase):
    def test_current_device_considered_device_and_video_have_separate_roles(self):
        text = ("I use Acme X2 and it broke yesterday. I am considering Nova Z4. "
                "The video reviews Halo Q3.")
        mentions, pairs = scan([row("a", text)])
        self.assertEqual({role for _, role in mentions["acme x2"]}, {"当前使用"})
        self.assertEqual({role for _, role in mentions["nova z4"]}, {"拟购买或考虑"})
        self.assertEqual({role for _, role in mentions["halo q3"]}, {"视频中介绍"})
        self.assertNotIn("broke", next(iter(mentions["nova z4"].values()))[2])
        self.assertFalse(pairs)

    def test_comparison_needs_two_names_and_linked_cue_and_deduplicates_comments(self):
        yes = row("a", "Acme X2 vs Nova Z4 for battery life. Acme X2 vs Nova Z4 for charging.")
        no = row("b", "185hz vs 120hz. Acme X2 is cheaper than I expected, and Nova Z4 is on sale.")
        choice = row("c", "I am choosing between Acme X2 and Nova Z4 for charging.")
        _, pairs = scan([yes, no, choice])
        self.assertEqual(set(pairs[("acme x2", "nova z4")]), {"a", "c"})
        self.assertEqual(pairs[("acme x2", "nova z4")]["c"][2], "选购备选比较")
        _, focused = scan([row("d", "Acme X2 vs Nova Z4 for RAM.")], ("续航与充电",))
        self.assertFalse(focused)

    def test_relayed_usage_does_not_become_author_experience(self):
        mentions, _ = scan([row("a", "My friend said I use Acme X2.")])
        self.assertEqual({role for _, role in mentions["acme x2"]}, {"提及，角色未确认"})

    def test_report_insight_counts_sources_and_links_to_concrete_validation(self):
        a = row("a", "I want to cancel my subscription without calling support.")
        b = row("b", "I hope the subscription cancellation takes fewer steps.")
        report = render_consumer_report("Software Subscription", state([a, b]), [])
        self.assertIn("2 条独立评论 · 多条评论共同提到", report)
        self.assertIn("明确期待 2 条", report)
        self.assertIn("lc=a", report)
        self.assertIn("lc=b", report)
        self.assertIn("消费者原文", report)
        self.assertIn("测试更清晰的取消或续订入口", report)
        self.assertIn("记录完成率、步骤和账单结果", report)
        self.assertIn("**0** 条进入正式属性统计", report)
        self.assertLess(report.index("## Competitive Discussion"), report.index("## Product Experience"))
