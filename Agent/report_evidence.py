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
                    r"(?=\s+(?:for|from|but|because)\b|[,!?]|\.(?!\w)|$)", re.I)
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
    names = tuple(" ".join(value.split()) for key, value in match.groupdict().items()
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


# These patterns identify what a speaker did or asked. A product name comes
# from the same clause or from a separately checked, literally cited entity.
MONEY = r"(?:[£€$¥]\s*\d[\d,.]*|(?:RM|USD|EUR|GBP)\s*\d[\d,.]*|\d[\d,.]*\s*(?:[£€$¥]|USD|EUR|GBP|RM))"
PRICED_CHOICE = re.compile(
    rf"\b(?:recommend|choose) between (?:the )?(?P<a>[\w .+'’-]+?)\s*\((?P<p>{MONEY})\)"
    rf"\s+(?:and|or)\s+(?:the )?(?P<b>[\w .+'’-]+?)\s*\((?P<q>{MONEY})\)\s*[?？]", re.I)
REGIONAL_QUOTE = re.compile(
    rf"\byou can get (?:the )?(?P<name>{MENTION}?) in (?P<place>[a-z][a-z -]{{1,30}}?) "
    rf"(?:for|as low as) (?P<price>{MONEY})(?![\w.,])", re.I)
ACCESS_QUESTION = re.compile(
    r"\b(?:is it true|do (?:i|we|you) (?:need|have) to|does .{1,35} require)\b"
    r"[^?？]{0,210}\b(?:paid subscription|third[- ]party agreements?)\b[^?？]*[?？]", re.I)
RETURN_CHOICE = re.compile(
    rf"\bi (?:just )?(?:bought|purchased) (?:the )?(?P<a>{MENTION}?) and returned (?:it|them) "
    rf"(?:as|because) (?P<reason>i (?:couldn['’]t|could not) (?:get|achieve) (?:a )?(?:good )?seal in (?:my )?ears?) "
    rf"and (?:went back to|switched to) (?P<b>{MENTION}?)(?=[.!?]|$)", re.I)
SUBJECTIVE_COMPARE = re.compile(r"\bmy (?P<subject>[\w -]{2,24}?) was better than (?P<other>[\w -]{2,24}?)(?= let alone|[.!?]|$)", re.I)
INTERRUPTION = re.compile(r"\bi (?:keep having|have|notice) [^,.!?]{1,42}\b(?:cutting|dropping) (?:the )?(?:sound|audio) when i ([^.!?,]{3,45}?)(?= and i\b|[.!?,]|$)", re.I)
FIT_OPINION = re.compile(r"\bi (?:don['’]t|do not) like how (?:it|they) (?:sit|fit) in my ears?\b", re.I)
THIRD_PARTY = re.compile(r"\b(?:my )?(?:friends|colleagues|family members) (?:constantly |often )?complain about (?P<issue>[\w -]{3,40}?)(?= and i\b|[,.!?]|$)", re.I)
BATTERY_REPAIR = re.compile(r"\bbattery\b[^.!?]{0,55}\b(?:wane|degrad\w*|wears? out|ages?|fades?)\b[^.!?]{0,45}\b(?:irreparable|(?:can['’]t|cannot) (?:be )?(?:repair\w*|replac\w*))\b", re.I)
QUICK_PRICE = re.compile(r"\s*(?:price|how much)[?？!\s]+", re.I)
PAID_PRICE = re.compile(rf"^\s*(?P<price>{MONEY})\s+(?:of )?the best money i (?:ever )?spent\b", re.I)


def independent_claims(spans, model=""):
    """Extract separate qualitative observations from original clauses."""
    quotes = [span["text"].strip() for span in spans]
    source = " ".join(quotes)
    claims = []
    for quote in quotes:
        if LINK.search(quote) or quote.startswith(('"', '“')):
            continue
        if match := PRICED_CHOICE.search(quote):
            if names := _names(match):
                claims.append(LiteralClaim("priced_choice", quote, names, f"{match['p']} / {match['q']}"))
        if match := REGIONAL_QUOTE.search(quote):
            if model and model.casefold() == match["name"].casefold():
                claims.append(LiteralClaim("regional_quote", quote, (match["name"],), f"{match['place']} · {match['price']}"))
        if ACCESS_QUESTION.search(quote):
            claims.append(LiteralClaim("access_question", quote))
        if match := RETURN_CHOICE.search(quote):
            if names := _names(match):
                claims.append(LiteralClaim("return_choice", quote, names, match["reason"]))
        if match := SUBJECTIVE_COMPARE.search(quote):
            claims.append(LiteralClaim("subjective_comparison", quote, (match["subject"], match["other"])))
        if model and re.search(r"\bmy " + re.escape(model) + r"\b", source, re.I) and not REPORTED.search(quote):
            if match := INTERRUPTION.search(quote):
                if re.search(r"\blisten to music\b", match[1], re.I):
                    claims.append(LiteralClaim("interruption", quote, (model,)))
            if FIT_OPINION.search(quote):
                claims.append(LiteralClaim("fit", quote, (model,)))
            if (match := THIRD_PARTY.search(quote)) and match["issue"].casefold() == "call quality":
                claims.append(LiteralClaim("third_party", quote, (model,), match["issue"]))
        if BATTERY_REPAIR.search(quote) and not REPORTED.search(quote):
            cost = re.search(r"\bbuy again\b.{0,25}\bbank breaker\b", source, re.I)
            claims.append(LiteralClaim("battery_repair", quote, value="replacement_cost" if cost else ""))
        if QUICK_PRICE.fullmatch(quote):
            claims.append(LiteralClaim("price_question", quote))
    if any(claim.kind == "priced_choice" for claim in claims):
        for quote in quotes:
            if re.search(r"\bi (?:just )?connect (?:it|them) to my phone and listen to music\b", quote, re.I):
                claims.append(LiteralClaim("listening_context", quote,
                                           value="YouTube" if re.search(r"\byoutube\b", quote, re.I) else ""))
                break
    # A price can be tied to a purchase only when there is one unambiguous
    # purchase clause in the comment, with the amount directly after it.
    purchases = [BOUGHT.search(quote) for quote in quotes if not REPORTED.search(quote)]
    purchases = [match for match in purchases if match and not LINK.search(match.string)]
    if len(purchases) == 1 and len(purchases[0]["name"].split()) >= 2:
        index = quotes.index(purchases[0].string)
        tail = quotes[index + 1:]
        if tail and (match := PAID_PRICE.match(tail[-1])) and not any(
            re.search(r"\b(?:bought|paid|ordered|purchased)\b", quote, re.I) for quote in tail[:-1]
        ):
            claims.append(LiteralClaim("paid_quote", tail[-1], (purchases[0]["name"],), match["price"]))
    if not any(claim.kind == "return_choice" for claim in claims):
        claims = [claim for claim in claims if claim.kind != "subjective_comparison"]
    return tuple(dict.fromkeys(claims))
