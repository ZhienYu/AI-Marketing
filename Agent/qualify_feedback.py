"""Conservative English feedback qualification using synthetic data only; no AI/API."""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parent
FEEDBACK_TYPES = (
    "Actual Usage Experience", "Purchase Inquiry", "Product Discussion",
    "Content Feedback", "Irrelevant/Unclear",
)
DEMO_CATALOG = (
    {"brand": "DemoAqua", "product_model": "DemoAqua R1"},
    {"brand": "DemoPool", "product_model": "DemoPool X2"},
)
PRODUCT_TERMS = r"\b(?:pool cleaners?|robotic pool cleaners?|pool robots?|battery|filter|robot|cleaner|charging|suction|price|expensive|overpriced|affordable|maintenance|cleans?|cleaning|reliable|broke|broken|gets stuck)\b"
CONTENT_TERMS = r"\b(?:video|reviewer|editing|camera work|tutorial|filming|explanation)\b"
INQUIRY = r"\b(?:price|how much|where (?:can|do|should) i buy|should i buy|worth buying|thinking (?:of|about) buying|planning to buy|want to buy|does it|can it|will it|how long)\b"
USAGE = r"\bi (?:have )?(?:used|tested|ran|operated)\b|\bi have been using\b|\bi['’]ve (?:used|tested|been using)\b|\bmy\b[^.!?]{0,60}\b(?:gets stuck|stopped working|cleans|lasts|broke|runs)\b"
INDIRECT = r"\b(?:my friend|my neighbor|someone|they|he|she) (?:says|said|told|used|owns)|\bmy (?:friend|neighbor|brother|sister|partner)['’]s\b|\b(?:according to|i heard|people say|the reviewer says|the reviewer said)\b"
UNCERTAIN = r"\b(?:maybe|not sure|i guess|sarcasm|yeah right)\b|/s\b"
POSITIVE = r"\b(?:great|excellent|good|amazing|easy|affordable|reliable|love|works well|cleans well)\b"
NEGATIVE = r"\b(?:bad|terrible|poor|expensive|overpriced|difficult|hate|broke|broken|gets stuck|stopped working|too short|too quickly)\b"


def contains(pattern, text):
    return bool(re.search(pattern, text, re.IGNORECASE))


def sentiment(clause):
    lowered = clause.casefold()
    positive = contains(r"\bnot (?:bad|expensive)\b", lowered)
    negative = contains(r"\bnot (?:good|great|reliable|easy)\b", lowered)
    lowered = re.sub(r"\bnot (?:bad|expensive|good|great|reliable|easy)\b", "", lowered)
    if contains(r"\b(?:not|never|isn't|doesn't|don't|neither)\b", lowered) and contains(POSITIVE + "|" + NEGATIVE, lowered):
        return "Unclear"
    positive = positive or contains(POSITIVE, lowered)
    negative = negative or contains(NEGATIVE, lowered)
    if positive and negative:
        return "Mixed"
    if positive:
        return "Positive"
    if negative:
        return "Negative"
    return "Not Expressed"


def combine_sentiments(values):
    if "Unclear" in values:
        return "Unclear"
    positive = bool(set(values) & {"Positive", "Mixed"})
    negative = bool(set(values) & {"Negative", "Mixed"})
    return "Mixed" if positive and negative else "Positive" if positive else "Negative" if negative else "Not Expressed"


def qualify_feedback(review, catalog=DEMO_CATALOG):
    if not isinstance(review, dict) or review.get("is_synthetic") is not True:
        raise ValueError("This milestone accepts explicitly synthetic examples only; real comments are not supported.")
    review_id = review.get("review_id")
    text = review.get("review_text")
    if not isinstance(review_id, str) or not review_id.strip() or not isinstance(text, str):
        raise ValueError("Synthetic feedback requires a non-empty review_id and review_text string.")
    model_matches = [item for item in catalog if contains(r"\b" + re.escape(item["product_model"]) + r"\b", text)]
    matches = [item for item in catalog if contains(r"\b" + re.escape(item["brand"]) + r"\b", text)]
    brand = matches[0]["brand"] if len(matches) == 1 else "unknown"
    model = model_matches[0]["product_model"] if len(model_matches) == 1 else "unknown"
    category_mentioned = contains(r"\b(?:pool cleaners?|robotic pool cleaners?|pool robots?)\b", text)
    scope = "product" if model_matches else "brand" if matches else "category" if category_mentioned else "unknown"
    types = set()
    evidence = []
    product_sentiments = []
    content_sentiments = []
    usage = []
    uncertain_usage = []
    substantive_statements = []
    reasons = []
    ambiguity = []
    if len(matches) > 1:
        brand, model = "unknown", "unknown"
        ambiguity.append("Multiple explicit entities; no single reviewed brand/product can be assigned.")
    if contains(UNCERTAIN, text):
        ambiguity.append("Uncertainty or possible sarcasm requires manual review.")
    for clause in re.split(r"(?<=[.!?;])\s+|\s+but\s+", text.strip()):
        if not clause:
            continue
        buying_intention = contains(r"\b(?:thinking (?:of|about) buying|planning to buy|want to buy)\b", clause)
        is_question = buying_intention or "?" in clause or contains(r"^\s*(?:price\b|how\b|where\b|does\b|can\b|will\b|should\b|i wonder\b|i would like to know\b|please tell me\b|is\b.*\?)", clause)
        has_entity = any(contains(r"\b" + re.escape(item["brand"]) + r"\b", clause) for item in matches)
        product = has_entity or contains(PRODUCT_TERMS, clause)
        content = contains(CONTENT_TERMS, clause)
        indirect = contains(INDIRECT, clause)
        usage_pattern = contains(USAGE, clause)
        quoted = contains(r'["“”]', clause)
        self_usage = usage_pattern and not is_question and not indirect and not quoted and not contains(r"\b(?:not|never|haven't|hadn't|hypothetically|if|would)\b", clause)
        if usage_pattern and (indirect or quoted):
            uncertain_usage.append(clause)
            ambiguity.append("Quoted/indirect first-person wording does not establish the author's own use.")
        if self_usage:
            types.add("Actual Usage Experience")
            usage.append(clause)
        if (is_question and (product or contains(INQUIRY, clause))) or buying_intention:
            types.add("Purchase Inquiry")
            evidence.append({"kind": "inquiry", "text": clause})
        if content:
            types.add("Content Feedback")
        if indirect:
            ambiguity.append("Reported or quoted experience is not verified first-person usage.")
        if product and not is_question:
            types.add("Product Discussion")
        if content and product:
            ambiguity.append("Content and product references share a clause; sentiment target is ambiguous.")
            product_sentiments.append("Unclear")
            content_sentiments.append("Unclear")
        elif not is_question:
            polarity = sentiment(clause)
            if product:
                product_sentiments.append(polarity)
                evidence.append({"kind": "product_statement", "text": clause, "sentiment": polarity})
                non_use = contains(r"\b(?:not used|never used|haven't used|not tried|haven't tried)\b", clause)
                buying_only = contains(r"\bi (?:bought|own|purchased|have bought|have purchased)\b", clause)
                if not non_use and (self_usage or polarity != "Not Expressed" or (contains(PRODUCT_TERMS, clause) and not buying_only)):
                    substantive_statements.append(clause)
            elif content:
                content_sentiments.append(polarity)
                evidence.append({"kind": "content_statement", "text": clause, "sentiment": polarity})
    if usage:
        reasons.append("Explicit first-person use/operation claim; self-reported only, not verified purchase.")
        evidence.extend({"kind": "usage_claim", "text": clause} for clause in usage)
    if "Purchase Inquiry" in types:
        reasons.append("Purchase/product question or buying intention; a question alone is not an expressed negative opinion.")
    if "Product Discussion" in types:
        reasons.append("A declarative product-related statement was detected; this alone does not imply use or purchase.")
    if "Content Feedback" in types:
        reasons.append("Video/reviewer/presentation references are tracked separately from product feedback.")
    if scope == "unknown":
        ambiguity.append("Product target/category cannot be established from the text alone.")
    if any(value == "Unclear" for value in product_sentiments):
        ambiguity.append("Product sentiment has unresolved negation or target ambiguity.")
    if not types:
        types.add("Irrelevant/Unclear")
        reasons.append("No supported product, purchase, usage or content-feedback pattern; abstain.")
    has_product_statement = "Product Discussion" in types or bool(usage)
    eligible = bool(substantive_statements or usage) and scope != "unknown" and not ambiguity
    if has_product_statement and not substantive_statements and not usage:
        reasons.append("A product mention, ownership/purchase claim or explicit non-use alone is not substantive product feedback.")
    status = "qualified" if eligible else "ambiguous" if ambiguity and has_product_statement else "insufficient evidence"
    strength = "strong" if eligible and usage and any(value in {"Positive", "Negative", "Mixed"} for value in product_sentiments) else "moderate" if eligible else "weak" if types != {"Irrelevant/Unclear"} else "insufficient evidence"
    reasons.append("Entity attribution uses explicit catalog names in comment text only; video metadata is ignored.")
    labels = [label for label in FEEDBACK_TYPES if label in types]
    return {
        "review_id": review_id, "is_synthetic": True,
        "primary_type": labels[0], "feedback_types": labels,
        "product_sentiment": combine_sentiments(product_sentiments),
        "content_sentiment": combine_sentiments(content_sentiments),
        "usage_evidence": {"status": "self_reported" if usage else "ambiguous" if uncertain_usage else "none", "verified_purchase": False, "quotes": usage, "ambiguous_quotes": uncertain_usage},
        "feedback_scope": scope, "brand": brand, "product_model": model,
        "entity_candidates": matches,
        "qualification_status": status, "evidence_strength": strength,
        "eligible_for_product_insights": eligible,
        "eligible_as_usage_review": eligible and bool(usage),
        "reasons": reasons, "ambiguities": list(dict.fromkeys(ambiguity)), "evidence": evidence,
    }


def qualify_batch(reviews, minimum_sample_size=20):
    if not isinstance(reviews, list) or type(minimum_sample_size) is not int or minimum_sample_size < 1:
        raise ValueError("Provide a synthetic review list and positive minimum sample size.")
    results = [qualify_feedback(review) for review in reviews]
    ids = [result["review_id"] for result in results]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate review IDs; no double counting allowed.")
    eligible = [result for result in results if result["eligible_for_product_insights"]]
    by_brand = Counter(result["brand"] for result in eligible if result["brand"] != "unknown")
    summary = {
        "total_records": len(results), "valid_product_feedback": len(eligible),
        "usage_review_candidates": sum(result["eligible_as_usage_review"] for result in results),
        "purchase_inquiries": sum("Purchase Inquiry" in result["feedback_types"] for result in results),
        "content_feedback": sum("Content Feedback" in result["feedback_types"] for result in results),
        "irrelevant_or_unclear": sum(result["primary_type"] == "Irrelevant/Unclear" for result in results),
        "ambiguous": sum(result["qualification_status"] == "ambiguous" for result in results),
        "insufficient_evidence": sum(result["qualification_status"] == "insufficient evidence" for result in results),
        "qualified_by_brand": dict(sorted(by_brand.items())),
        "qualified_unknown_brand": sum(result["brand"] == "unknown" for result in eligible),
        "type_counts": {label: sum(label in result["feedback_types"] for result in results) for label in FEEDBACK_TYPES},
        "minimum_sample_size": minimum_sample_size,
        "sample_warning": "Insufficient Data" if len(eligible) < minimum_sample_size else "Sample only; not representative of the market",
        "brand_sample_warnings": {brand: "Insufficient Data" if count < minimum_sample_size else "Sample only" for brand, count in sorted(by_brand.items())},
        "counting_note": "Feedback types overlap; do not sum type counts. Usage is self-reported, never verified purchase. Threshold is an engineering reminder, not statistical validity.",
    }
    return {"mode": "synthetic-rules", "notice": "DEMO — SYNTHETIC DATA. Conservative English rules, not validated AI or real consumer research.", "summary": summary, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-only", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        payload = json.loads((AGENT_DIR / "tests" / "fixtures" / "feedback_qualification_synthetic.json").read_text(encoding="utf-8"))
        if payload.get("is_synthetic") is not True:
            raise ValueError("Fixture must explicitly identify synthetic data.")
        result = qualify_batch(payload["reviews"])
        if arguments.summary_only:
            result = {"mode": result["mode"], "notice": result["notice"], "summary": result["summary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("Cannot qualify synthetic fixture: check schema, synthetic flags and unique review IDs.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
