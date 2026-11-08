"""Air Purifier example. Load existing source text without importing its runner."""

import ast
from hashlib import sha256
from pathlib import Path

from business_report_view import BusinessReportView, CommentSource, ReportItem


FROZEN_IDS = (
    "Ugyw4YqbExGZoxzSlJZ4AaABAg",
    "UgxUyEIqis8fqz698Vt4AaABAg",
    "UgyGJWnHY5sWdGYcfX14AaABAg",
)

FROZEN_TEXT_HASHES = (
    "f6c09c836defbc4d8741167339f6b4064d003ac5ccb7705e2befafb8ddeaa4e7",
    "0214ef9c5ad55c50d3032e22431f143b123e09104fb7444b5194dd70da89e948",
    "a7915b430fbf0850f2e854951cec1704f0c738cd9851e6c4bea2e828fe298f09",
)


def load_demo_sources(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FROZEN" for target in node.targets
        ):
            rows = ast.literal_eval(node.value)
            break
    else:
        raise ValueError("Missing frozen evidence.")
    if tuple(row[1] for row in rows) != FROZEN_IDS:
        raise ValueError("Unexpected frozen evidence.")
    if tuple(sha256(row[3].encode("utf-8")).hexdigest() for row in rows) != FROZEN_TEXT_HASHES:
        raise ValueError("Frozen evidence text was changed.")
    return tuple(
        CommentSource(f"S{index:02}", video, comment, raw, published, "unverified")
        for index, (video, comment, published, raw) in enumerate(rows, start=1)
    )


def build_air_purifier_demo(sources):
    performance, budget, noise = (source.label for source in sources)
    return BusinessReportView(
        topic="Air Purifier",
        demo=True,
        sources=sources,
        summary=(
            ReportItem("预算与净化效果一起被讨论",
                       "两条评论将价格与预期效果放在同一语境中，一条询问预算内除尘，一条用 CADR 和评论者所述价格评价产品。",
                       (performance, budget)),
            ReportItem("减少桌面清洁是一个具体场景",
                       "一位评论者希望空气净化器减少空气中的灰尘，从而降低清洁桌面设备的频率。实际效果尚待验证。",
                       (budget,)),
            ReportItem("噪声是一个待回答的选购问题",
                       "一位评论者想知道哪款更安静。评论未列出型号或实测噪声。",
                       (noise,)),
        ),
        topics=(
            ReportItem("净化效果", "", (performance, budget)),
            ReportItem("价格与预算", "", (performance, budget)),
            ReportItem("运行噪声", "", (noise,)),
        ),
        needs=(
            ReportItem("预算内减少桌面落尘", "目标是少清理桌面设备。评论表达了期待，未提供使用后的效果。",
                       (budget,), "明确需求"),
            ReportItem("选购前比较运行噪声", "评论者询问哪款最安静，未说明房间、档位或使用时段。",
                       (noise,), "购买咨询"),
        ),
        purchase=(
            ReportItem("价格与效果", "一位评论者认为某型号的 CADR 和价格有吸引力。",
                       (performance,), "购买驱动"),
            ReportItem("预算内能否除尘", "一位评论者在找符合预算、又能满足基本除尘需求的型号。",
                       (budget,), "待解决障碍"),
            ReportItem("哪款更安静", "原文显示存在比较问题，尚无同档位噪声证据。",
                       (noise,), "待解决障碍"),
        ),
        competitors=(
            ReportItem("AIR FANTA PURIFIER PRO5",
                       "评论者提到 CADR 与报价，并给出正面评价。产品参数、报价及使用角色均未独立核实。",
                       (performance,), "具名评价"),
            ReportItem("未指明型号的比较",
                       "评论者想了解哪款更安静。原文没有足够信息确认比较对象。",
                       (noise,), "比较咨询"),
        ),
        opportunities=(
            ReportItem("验证入门款的除尘价值主张",
                       "考虑把预算内的基本除尘定位作为研究方向。先检验目标房间内的实际除尘表现，再看用户是否认为它值得购买。",
                       (budget, performance), "产品定位"),
            ReportItem("让噪声信息更容易比较",
                       "考虑在选购页提供同条件、同档位的噪声对照，观察用户能否更容易缩小候选范围。",
                       (noise,), "选购体验"),
        ),
        limitations=(
            "这是从历史采集中选出的三条公开顶层评论。报告只描述这个小样本，同一条评论可支持多个主题。",
            "三条原文都曾提交历史 Shadow 实验，Phase E 整体输出未通过验收。本页未导入任何通过校验的模型结论。",
            "主题、角色说明和机会由人工为界面演示整理。机会是待验证的方向，评论者所述规格、价格和效果未经独立核实。",
        ),
    )
