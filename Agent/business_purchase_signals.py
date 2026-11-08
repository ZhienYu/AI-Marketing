"""Literal buying signals used by the visual report, outside formal statistics."""

from dataclasses import dataclass
import re


CHOICE = re.compile(
    r"\b(?:should|could|would) (?:i|we) (?:buy|choose|get|pick)\s+"
    r"(?P<left>[^?!.;\n,]{2,65}?)\s+or\s+(?P<right>[^?!.;\n,]{2,65})[?？]"
    r"|\b(?:choosing|deciding|torn) between\s+(?P<first>[^?!.;\n,]{2,65}?)"
    r"\s+and\s+(?P<second>[^?!.;\n,]{2,65})(?:[?？.!]|$)",
    re.I,
)
AREA = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?(?:\s*(?:[-–]|to)\s*\d+(?:[.,]\d+)?)?"
    r"\s*(?:sq\.?\s*(?:ft|m)|square\s+(?:feet|foot|met(?:er|re)s?)|ft²|m²|平方米)(?!\w)",
    re.I,
)
ROOM_CONTEXT = re.compile(r"\b(?:room|bedroom|space|office|area)\b|房间|卧室|面积", re.I)
CONSUMABLE_COST = re.compile(
    r"\b(?:filters?|cartridges?|refills?|consumables?)\b.{0,30}\b(?:costs?|price[ds]?|fees?|priced)\b"
    r"|\b(?:costs?|price[ds]?|fees?)\b.{0,30}\b(?:filters?|cartridges?|refills?|consumables?)\b"
    r"|(?:滤芯|耗材).{0,12}(?:费用|价格|成本)",
    re.I,
)
MODEL = re.compile(r"(?=.*\d)[a-z][\w .+/-]{1,63}", re.I)


@dataclass(frozen=True)
class PurchaseChoice:
    options: tuple[str, str]
    area: str | None
    consumable_cost: bool


def purchase_choice(text):
    """Recognize a bounded first-person choice with two named model strings."""
    match = CHOICE.search(text)
    if not match:
        return None
    if re.search(r"\b(?:asked|said|wrote|quoted)\b.{0,35}$", text[max(0, match.start() - 45):match.start()], re.I):
        return None
    options = ((match["left"] or match["first"]).strip(), (match["right"] or match["second"]).strip())
    if (options[0].casefold() == options[1].casefold()
        or not all(MODEL.fullmatch(name) and len(name.split()) <= 7 for name in options)):
        return None
    area = next((m.group() for m in AREA.finditer(text)
                 if ROOM_CONTEXT.search(text[max(0, m.start() - 30):m.end() + 35])), None)
    return PurchaseChoice(options, area, bool(CONSUMABLE_COST.search(text)))

MONEY = r"(?:[£€$¥]\s*\d[\d.,]*|\d[\d.,]*\s*(?:[£€$¥]|USD\b|GBP\b|EUR\b|dollars?\b|euros?\b|元))"
SPENDING_LIMIT = re.compile(
    r"(?:\b(?:don['’]t|do not|can['’]t|cannot|won['’]t|will not|not to) (?:want to )?(?:spend|pay) more than|"
    r"\b(?:spend|pay) no more than|"
    r"\b(?:my|our) budget (?:is|of)|\b(?:a )?(?:max(?:imum)?|upper) budget(?: of| is)?|"
    r"\b(?:spend|pay) (?:at most|up to)|(?:预算|最多)(?:是|花)?)\s+(?P<amount>" + MONEY + r")",
    re.I,
)
NO_OZONE = re.compile(
    r"\b(?:don['’]t want|do not want|must not (?:release|emit|produce))\s+(?:any\s+)?ozone\b"
    r"|不(?:要|希望|能)(?:产生|释放)?臭氧",
    re.I,
)


def purchase_constraints(text):
    """Extract an explicitly stated spending cap or ozone preference."""
    limit = SPENDING_LIMIT.search(text)
    return (limit["amount"] if limit else None), bool(NO_OZONE.search(text))
