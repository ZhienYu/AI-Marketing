"""Offline sample statistics from classified reviews; never calls an API."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from classify_reviews import AGENT_DIR, CLASSIFICATION_FIELDS, ClassificationError, check_classification, save_json


ASPECT_ORDER = (
    "Battery Life", "Cleaning Performance", "Ease of Use", "Price",
    "Maintenance", "Reliability", "Customer Support", "Other",
)
BRANDS = ("Brand A", "Brand B", "Brand C")


def generate_insights(classified):
    if not isinstance(classified, dict) or classified.get("mode") not in {"mock", "qwen"}:
        raise ClassificationError("Input must be a mock or qwen classification report.")
    results = classified.get("results")
    if not isinstance(results, list):
        raise ClassificationError("Input results must be an array.")
    brands = {}
    seen_ids = set()
    unknown_ids = []
    synthetic_count = 0
    for result in results:
        review_id = result["review_id"]
        if not isinstance(review_id, str) or not review_id or review_id in seen_ids:
            raise ClassificationError("Duplicate or invalid review ID in insights input.")
        seen_ids.add(review_id)
        classification = {field: result[field] for field in CLASSIFICATION_FIELDS}
        aspects = classification["product_aspects"]
        if isinstance(aspects, list):
            unique = {}
            for item in aspects:
                unique[json.dumps(item, sort_keys=True)] = item
            classification["product_aspects"] = list(unique.values())
        check_classification(classification)
        if result.get("is_synthetic") is True or result.get("source_platform", "").casefold() == "synthetic":
            synthetic_count += 1
        brand = result["brand"]
        if not isinstance(brand, str):
            raise ClassificationError("Invalid brand in insights input.")
        brand = brand.strip()
        if not brand or brand.casefold() == "unknown":
            unknown_ids.append(review_id)
            continue
        if brand not in brands:
            brands[brand] = {
                "sample_size": 0,
                "aspect_ids": {aspect: {polarity: set() for polarity in ("Positive", "Negative", "Neutral")} for aspect in ASPECT_ORDER},
                "negative_feedback": defaultdict(set),
                "pain_ids": defaultdict(set),
                "pain_labels": {},
            }
        data = brands[brand]
        data["sample_size"] += 1
        for item in classification["product_aspects"]:
            data["aspect_ids"][item["aspect"]][item["sentiment"]].add(review_id)
            if item["sentiment"] == "Negative":
                data["negative_feedback"][item["aspect"]].add(item["feedback"])
        for pain in classification["pain_points"]:
            normalized = " ".join(pain.split()).casefold()
            data["pain_ids"][normalized].add(review_id)
            data["pain_labels"].setdefault(normalized, pain.strip())

    output_brands = {}
    comparison = []
    for brand in sorted(set(BRANDS) | set(brands)):
        data = brands.get(brand)
        sample_size = data["sample_size"] if data else 0
        counts = {
            aspect: {polarity: len(data["aspect_ids"][aspect][polarity]) if data else 0 for polarity in ("Positive", "Negative", "Neutral")}
            for aspect in ASPECT_ORDER
        }
        negative_aspects = []
        if data:
            for aspect in ASPECT_ORDER:
                ids = data["aspect_ids"][aspect]["Negative"]
                if ids:
                    negative_aspects.append({
                        "aspect": aspect, "review_count": len(ids), "review_ids": sorted(ids),
                        "feedback_examples": sorted(data["negative_feedback"][aspect]),
                    })
        output_brands[brand] = {
            "sample_size": sample_size,
            "comparison_status": "Insufficient Data" if sample_size < 20 else "Sample statistics only",
            "aspect_counts": counts,
            "top_negative_aspects": sorted(negative_aspects, key=lambda item: (-item["review_count"], item["aspect"])),
            "top_pain_points": sorted([
                {"feedback": data["pain_labels"][pain], "review_count": len(ids), "review_ids": sorted(ids)}
                for pain, ids in data["pain_ids"].items()
            ], key=lambda item: (-item["review_count"], item["feedback"])) if data else [],
        }
    for aspect in ASPECT_ORDER:
        comparison.append({"aspect": aspect, "brands": {
            brand: {"sample_size": data["sample_size"], **data["aspect_counts"][aspect]}
            for brand, data in output_brands.items()
        }})
    return {
        "schema_version": "2.4", "source_mode": classified["mode"],
        "notice": "Counts describe this collected sample only, not market prevalence or brand rankings. Synthetic reviews and mock classifications are test data, not market evidence. Zero mentions are not evidence of absence.",
        "methodology": "Each review counts once per aspect and sentiment. Pain text is matched by case/whitespace only; semantic paraphrases are not merged. Negative aspects group pains by standard category. Brands below 20 classified reviews have insufficient data for strong comparisons.",
        "classified_sample_size": len(results), "synthetic_records": synthetic_count,
        "unknown_brand_records": len(unknown_ids), "unknown_brand_review_ids": unknown_ids,
        "failed_records_excluded": len(classified.get("failures", [])),
        "brands": output_brands, "comparison_table": comparison,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--dataset", choices=("test", "real"), default="test")
    arguments = parser.parse_args(argv)
    try:
        directory = AGENT_DIR / "outputs" / arguments.dataset
        input_path = arguments.input or directory / "classification_mock.json"
        classified = json.loads(input_path.read_text(encoding="utf-8"))
        result = generate_insights(classified)
        if arguments.dataset == "real" and (result["source_mode"] == "mock" or result["synthetic_records"]):
            raise ClassificationError("Synthetic or mock data cannot be saved under real outputs.")
        if arguments.dataset == "test" and result["synthetic_records"] != result["classified_sample_size"]:
            raise ClassificationError("Real review statistics require --dataset real.")
        output = directory / ("insights_mock.json" if result["source_mode"] == "mock" else "insights_qwen.json")
        if input_path.resolve() == output.resolve():
            raise ClassificationError("Refusing to overwrite classification input.")
        save_json(output, result)
    except (ClassificationError, OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Could not generate insights: check input structure and unique review IDs. No source file changed.", file=sys.stderr)
        return 2
    print(f"Saved offline insights to Agent/outputs/{arguments.dataset}/{output.name}")
    print("Aspect | Brand A (+/-/neutral; n) | Brand B (+/-/neutral; n) | Brand C (+/-/neutral; n)")
    for row in result["comparison_table"]:
        cells = [row["aspect"]]
        for brand in BRANDS:
            cell = row["brands"][brand]
            cells.append(f"{cell['Positive']}/{cell['Negative']}/{cell['Neutral']}; n={cell['sample_size']}")
        print(" | ".join(cells))
    print("Sample statistics only. Synthetic/mock data are not real market evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
