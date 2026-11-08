"""Conservative, literal evidence recovery for qualitative reports only."""

from dataclasses import dataclass
import re

from business_purchase_signals import AREA, CONSUMABLE_COST


MENTION = r"[a-z][\w .+-]{1,42}"
RECOMMENDATION = re.compile(
    rf"\bwhy (?P<a>{MENTION}?) (?:isn['’]t|is not|wasn['’]t) (?:on|in|included in) "
    rf"(?:the )?recommendations?(?: list)? together with (?P<b>{MENTION}?) and (?P<c>{MENTION})[?？]", re.I)
CHOICE = re.compile(
    rf"^(?:what['’]?s your thoughts on (?:the )?)?(?P<a>{MENTION}?)\s+vs\.?\s+(?P<b>{MENTION}?)"
    r"(?:\s+(?:can|could) you (?:please )?(?:suggest|recommend)[?？.]?|[?？])$", re.I)
UNDECIDED = re.compile(
    rf"^i(?:['’]m| am) (?:confused|torn) (?:between )?(?P<a>{MENTION}?) or "
    rf"(?P<b>{MENTION}?)\s+(?P<filter>\d+[- ]year filter\s+)?i should choose[?？]$", re.I)
SINGLE_INQUIRY = re.compile(rf"^(?:what|how) about (?:the )?(?P<a>{MENTION})[?？]$", re.I)
BUY_OR_NOT = re.compile(r"\bbuy or not\b", re.I)
BOUGHT = re.compile(rf"(?:^\s*|\bi\s+)(?:bought|purchased)\s+(?:a |an |the )?(?P<name>{MENTION}?)"
                    r"(?=\s+(?:for|from|but|because)\b|[.!?]|$)", re.I)
REPORTED = re.compile(r"\b(?:my friend|someone (?:said|wrote)|according to|(?:he|she|they) (?:said|bought))\b", re.I)
PREFERENCE = re.compile(r"^not (?:having|needing|requiring|using) (?P<feature>[^.!?]{2,45}) "
                        r"is (?:a (?:selling (?:feature|point)|plus|benefit)|an advantage)\b", re.I)
GENERAL_COMPLAINT = re.compile(r"^i(?:['’]m| am) (?:sick|tired) of having .{1,50} (?:for everything|everywhere)\b", re.I)
DUST = re.compile(r"\b(?:remov\w* dust|clean the air|dust removal|airborne dust)\b", re.I)
BUDGET = re.compile(r"\b(?:budget|affordable|low[- ]cost)\b", re.I)
REQUEST = re.compile(r"\b(?:looking for|recommendations?|recommend(?:ed)?|suggest(?:ions?)?|specific models)\b", re.I)
AIR_CATEGORY = re.compile(r"\b(?:air purifier|air purification)\b|空气净化", re.I)
USE_LOCATION = re.compile(r"\s+but only in (?:the |my |our )?(bedroom|living room|office)\b", re.I)
LINK = re.compile(r"https?://", re.I)
FILTER_TERMS = re.compile(r"\bfilters?\b", re.I)


@dataclass(frozen=True)
class LiteralClaim:
    kind: str
    quote: str
    names: tuple[str, ...] = ()
    value: str = ""


def _names(match):
    names = tuple(value.strip() for key, value in match.groupdict().items()
                  if key in {"a", "b", "c"} and value)
    if not all(len(name.split()) <= 5 and name.casefold() not in
               {"air purifier", "purifier", "this one", "that one", "the other one", "it"} for name in names):
        return ()
    return names if len(set(name.casefold() for name in names)) == len(names) else ()


def literal_claims(query, spans):
    """Return source-backed roles and conditions, never inferred performance."""
    quotes = tuple(span["text"].strip() for span in spans)
    text = " ".join(quotes)
    if re.match(r"\s*(?:purchase|affiliate|shop) links?\s*:", text, re.I) and LINK.search(text):
        return ()
    claims = []
    for quote in quotes:
        if LINK.search(quote) or REPORTED.search(quote) or quote.startswith(('"', '“')):
            continue
        if match := RECOMMENDATION.search(quote):
            if names := _names(match):
                claims.append(LiteralClaim("recommendation", quote, names))
        else:
            match = CHOICE.fullmatch(quote) or UNDECIDED.fullmatch(quote)
            if match and (REQUEST.search(quote) or match.re is UNDECIDED
                          or re.search(r"\b(?:stuck|choosing|deciding) between\b", text, re.I)):
                if names := _names(match):
                    claims.append(LiteralClaim("choice", quote, names, (match.groupdict().get("filter") or "").strip()))
        if BUY_OR_NOT.search(text) and (match := SINGLE_INQUIRY.fullmatch(quote)):
            if names := _names(match):
                claims.append(LiteralClaim("inquiry", quote, names))
        if match := PREFERENCE.search(quote):
            claims.append(LiteralClaim("preference", quote, value=match["feature"]))
        if AIR_CATEGORY.search(query):
            if DUST.search(quote) and REQUEST.search(quote):
                claims.append(LiteralClaim("dust_budget" if BUDGET.search(quote) else "dust_request", quote,
                                           value="桌面清洁" if re.search(r"\bclean my setup\b", quote, re.I) else ""))
            if AREA.search(quote) and REQUEST.search(text) and re.search(r"\b(?:room|range size|area|space)\b", text, re.I):
                claims.append(LiteralClaim("room", quote, value=AREA.search(quote).group()))
    # Purchase wording and the accessory-cost sentence are separate claims.
    # A filter or air-cleaning context can establish relevance, not product type.
    if AIR_CATEGORY.search(query) and (FILTER_TERMS.search(text) or DUST.search(text) or AIR_CATEGORY.search(text)):
        for quote in quotes:
            if not LINK.search(quote) and not REPORTED.search(quote) and (match := BOUGHT.search(quote)):
                name = match["name"].strip()
                if not AIR_CATEGORY.fullmatch(name) and len(name.split()) >= 2:
                    location = USE_LOCATION.match(quote[match.end():])
                    claims.append(LiteralClaim("purchase", match.group().strip(), (name,),
                                               location[1] if location else ""))
        if any(claim.kind == "purchase" for claim in claims):
            for quote in quotes:
                if not LINK.search(quote) and not REPORTED.search(quote) and FILTER_TERMS.search(quote) and CONSUMABLE_COST.search(quote):
                    claims.append(LiteralClaim("filter_cost", quote))
    return tuple(dict.fromkeys(claims))
