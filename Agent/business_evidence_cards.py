"""Translate independent evidence into the visual report's reading model."""

from business_report_view import ReportItem


# Topics to replace for this source only. Other comments in a shared topic
# retain their cards and their own evidence.
REPLACES = {
    "priced_choice": {"型号选择", "型号选择与比较", "价格与预算", "未进一步分类"},
    "regional_quote": {"价格与预算", "未进一步分类"},
    "price_question": {"价格与预算", "未进一步分类"},
    "paid_quote": {"价格与预算", "未进一步分类"},
    "battery_repair": {"续航与充电", "可靠性与维护", "价格与预算", "未进一步分类"},
    "fit": {"未进一步分类"},
    "interruption": {"未进一步分类"},
    "return_choice": {"未进一步分类"},
}

RESEARCH = {
    "access_question": ("功能要付费吗？", "先核对原文所问功能是否附带使用条件，再研究在选购页提前说明能否减少疑问。"),
    "return_choice": ("试戴能否提前发现密封问题？", "研究试戴提示或不同耳塞尺寸能否帮用户在购买前识别密封困难。"),
    "battery_repair": ("买家会怎样权衡换电池和换新？", "先核对电池更换选项和费用，再了解这些信息是否会影响选购。"),
}


def observation_card(claim, ref):
    names = " / ".join(claim.names)
    value = claim.value
    detail, meaning = "", ""
    section = "purchase"
    if claim.kind == "priced_choice":
        section, title, badge = "competitors", names, "原文选购候选"
        detail = f"评论者列出的候选报价分别为 {value}。原文未说明预算或最终选择。"
        meaning = "这两项报价是比较背景。品牌可用原文中的使用场景判断哪些差异值得介绍。"
    elif claim.kind in {"regional_quote", "paid_quote"}:
        title, badge = ("地区报价", "评论者提供的报价") if claim.kind == "regional_quote" else ("购买成交价", "购买自述")
        detail = f"{names} · {value}。金额来自评论，未核实当前价格。"
        meaning = "地区报价可作为核对当地价格的线索。" if claim.kind == "regional_quote" else "这笔支出反映一位买家的评价背景。"
    elif claim.kind == "price_question":
        title, badge = "简单询价", "选购咨询"
        detail = "评论者只询问售价。"
    elif claim.kind == "access_question":
        badge = "选购咨询"
        conditions = []
        if "paid subscription" in claim.quote.casefold():
            conditions.append("付费订阅")
        if "party agreement" in claim.quote.casefold():
            conditions.append("同意第三方协议")
        requirements = "和".join(conditions)
        title = f"使用功能前是否需要{requirements}"
        detail = f"评论者想确认{requirements}是否是使用功能的条件。"
        meaning = "购买前能否看懂功能的使用条件，值得单独研究。"
    elif claim.kind == "listening_context":
        title, badge = "连接手机听歌", "使用场景自述"
        platform = "在 YouTube" if value == "YouTube" else ""
        detail = f"评论者说平时连接手机{platform}听歌。未说明用过哪款候选。"
    elif claim.kind == "return_choice":
        section, title, badge = "experience", "密封不合适后退货", "退货与后续选择 · 自述"
        a, b = claim.names
        detail = f"评论者说因无法贴合密封而退回 {a}，随后改选 {b}。"
        meaning = "试戴时能否形成密封，可能影响买家是否留下产品。"
    elif claim.kind == "subjective_comparison":
        section, title, badge = "competitors", names, "原文对比"
        detail = f"评论者用自己的 {claim.names[0]} 与 {claim.names[1]} 作比较，认为前者更好。这是个人评价。"
    elif claim.kind == "interruption":
        section, title, badge = "experience", "听音乐时断音", "使用自述 · 探索性"
        detail = f"评论者说用 {names} 听音乐时多次遇到断音。"
        meaning = "播放中断可作为检查日常聆听体验的具体场景。"
    elif claim.kind == "fit":
        section, title, badge = "experience", "佩戴贴合感", "使用自述 · 探索性"
        detail = f"评论者不喜欢 {names} 戴在耳中的感觉。"
    elif claim.kind == "third_party":
        section, title, badge = "experience", "通话质量反馈", "转述他人反馈"
        detail = f"评论者转述朋友对 {names} 通话质量的抱怨。"
    elif claim.kind == "battery_repair":
        section, title, badge = "preferences", "电池老化后的维修与换新", "长期使用顾虑 · 一般观点"
        detail = "评论者担心电池衰减后难以维修"
        detail += "，换新会带来额外支出。" if value else "。"
        meaning = "值得了解买家在意哪些维修选项，以及换新费用是否影响选择。"
    return section, ReportItem(title, detail, (ref,), badge, meaning)
