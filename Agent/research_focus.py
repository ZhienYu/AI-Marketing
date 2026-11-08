"""Conservative topic and source signals for research presentation, not eligibility."""

import re

# Query triggers name a feature or research dimension. Comment cues can use
# different wording, but neither video titles nor inferred brands supply a match.
FACETS = {
    "续航与充电": (
        r"\b(?:battery|battery life|charging|runtime|power consumption|baterai)\b|续航|电池|充电",
        r"\b(?:batter(?:y|ies)|baterai|pengisian daya|isi daya|daya tahan|charg(?:e|es|ed|ing)(?:nya)?|"
        r"recharg\w*|runtime|screen.on time|drain(?:s|ed|ing)?|\d[\d.,]*\s*mah)\b|续航|电池|充电",
    ),
    "清洁效果": (
        r"\b(?:cleaning (?:performance|effectiveness)|filtration|filter(?:s|ing)?)\b|清洁效果|过滤",
        r"\b(?:clean(?:s|ed|ing)?|filter\w*|debris|dirt|suction|dust|vacuuming)\b|清洁|过滤|吸力",
    ),
    "佩戴与人体工学": (
        r"\b(?:comfort|fit|ergonomics|wearability)\b|舒适|佩戴",
        r"\b(?:comfort\w*|wore|wear\w*|ear tips|fit|fits|pressure|ears? hurt|hurts? my ears?)\b|舒适|佩戴|压耳",
    ),
    "交付与订阅流程": (
        r"\b(?:subscription|billing|cancell?ation)\b|订阅|账单|取消",
        r"\b(?:subscription|billing|billed|cancel\w*|payment|refund|trial|renew\w*|charged)\b|订阅|扣费|取消|试用|退款",
    ),
    "连接与软件体验": (
        r"\b(?:bluetooth|connectivity|pairing)\b|连接|配对",
        r"\b(?:connect\w*|bluetooth|pair\w*|disconnect\w*|dropouts?)\b|连接|配对|断连",
    ),
}
DIRECT_WISH = re.compile(
    r"\b(?:(?:i|we) (?:wish|hope|want|need|would (?:love|like))|i['’]d (?:love|like))\b|"
    r"^\s*(?:would (?:love|like) to see|(?:saya |aku )?(?:ingin|berharap|pengen))\b|(?:我|我们)(?:希望|想要|需要)", re.I
)
MEDIA_ONLY = re.compile(r"\s*(?:nice|great|good|excellent|awesome) (?:test|video|review)[\s!.?👏👍]*", re.I)
BARE_COMPARISON = re.compile(
    r"\s*\d+(?:\.\d+)?\s*[a-z%]*\s+(?:vs\.?|versus)\s+\d+(?:\.\d+)?\s*[a-z%]*[.!?\s]*", re.I
)
CONDITIONAL = re.compile(r"^\s*(?:if|when(?:ever)?|as long as)\b", re.I)
HEALTH_READING = re.compile(
    r"(?:battery health|health of (?:the |my )?battery|life battery|kesehatan baterai|电池健康).{0,45}\d+\s*%"
    r"|\d+\s*%.{0,32}(?:battery health|life battery|电池健康)", re.I
)
RUNTIME_MEASURE = re.compile(r"\b(?:\d+\s*(?:hr|hrs|hours?|menit|jam)|screen.on time)\b|\d+\s*小时", re.I)
# A denominator such as m³/hr, km per hour or cycles/hour is not a duration.
RATE_TIME = re.compile(r"(?:/|\bper\s+)\s*(?:h|hrs?|hours?|minutes?|min|seconds?|sec)\b", re.I)
RESEARCH_AXES = (
    (r"\b(?:battery capacity|[\d.,]+\s*mah|larger batter(?:y|ies)|baterai jumbo)\b|电池容量", "电池容量"),
    (r"\b(?:fast(?:er)? charg\w*|charging (?:speed|time))\b|充电速度", "充电速度"),
    (r"\b(?:thin(?:ner|nest)?|thickness|lightweight|(?:device|unit|phone|product) weight|tipis|ringan)\b|轻薄|机身重量", "机身厚度或重量"),
    (r"\b(?:all day|full day|runtime|\d+(?:\.\d+)?\s*(?:h|hrs?|hours?)|hours? of)\b|全天|小时", "指定使用场景下的持续时间"),
    (r"\b(?:comfort(?:able|ably)?|ear tips|(?:fit|fits) (?:snugly|comfortably))\b|佩戴|压耳", "连续使用后的舒适度与贴合度"),
    (r"\b(?:cancel(?:ling|ing|lation)? (?:my |the |a )?(?:subscription|plan|trial)|(?:subscription|plan|trial) cancellation|renewal|billing)\b|取消订阅|续订|扣费", "取消或续订的步骤与实际扣费"),
    (r"\b(?:debris|suction|dust removal|remov\w* dust|filter (?:debris|dust|particles))\b|滤网|过滤颗粒|除尘", "不同污物条件下的清洁效果"),
)
TOPIC_AXES = {
    "续航与充电": {"电池容量", "充电速度", "机身厚度或重量", "指定使用场景下的持续时间"},
    "佩戴与人体工学": {"连续使用后的舒适度与贴合度", "机身厚度或重量"},
    "交付与订阅流程": {"取消或续订的步骤与实际扣费"},
    "清洁效果": {"不同污物条件下的清洁效果"},
}


def focus_for(query):
    return tuple(name for name, (trigger, _) in FACETS.items() if re.search(trigger, query, re.I))


def matching_focus(focus, source):
    return [name for name in focus if re.search(FACETS[name][1], source, re.I)]


def direct_wish(source):
    text = source.strip()
    return (not text.endswith(("?", "？")) and bool(DIRECT_WISH.search(text))
            and not bool(re.search(r"\b(?:my friend|someone|he|she) (?:said|wrote|told)\b"
                                   r"|\bto (?:know|learn|find out)\b|^[\"“]", text, re.I)))


def research_axes(source, *, topic=None):
    if topic is not None:
        allowed = TOPIC_AXES.get(topic, set())
    else:
        allowed = {axis for _, axis in RESEARCH_AXES}
    text = RATE_TIME.sub(" ", source)
    return [axis for pattern, axis in RESEARCH_AXES if axis in allowed and re.search(pattern, text, re.I)]
