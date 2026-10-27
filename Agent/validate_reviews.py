"""Validate local review CSV files without network access or dependencies."""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED_COLUMNS = ("review_id", "review_text", "source_platform", "source_url", "brand")
REQUIRED_VALUES = ("review_id", "review_text", "source_platform")
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "sample_reviews.csv"


def usable_url(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not any(
            character.isspace() for character in value
        )
    except ValueError:
        return False


def validate_reviews(path):
    report = {
        "total_records": 0,
        "valid_records": 0,
        "invalid_records": 0,
        "duplicate_records": 0,
        "excluded_records": 0,
        "unknown_brand_records": 0,
        "synthetic_records": 0,
        "evidence_eligible_records": 0,
        "valid_records_by_brand": {},
        "invalid": [],
        "duplicates": [],
        "warnings": [],
    }
    brands = Counter()
    seen_rows = {}
    seen_ids = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        headers = next((fields for fields in reader if fields), [])
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(missing))
        if len(headers) != len(set(headers)) or any(not header.strip() for header in headers):
            raise ValueError("CSV headers must be unique and non-empty")

        for fields in reader:
            if not fields:
                continue
            report["total_records"] += 1
            line = reader.line_num
            reasons = []
            if len(fields) != len(headers):
                reasons.append("Column count does not match header")
            row = dict(zip(headers, fields))
            values = {
                column: (row.get(column) or "").strip() for column in headers
            }
            for column in REQUIRED_VALUES:
                if not values[column]:
                    reasons.append("Missing value: " + column)
            if reasons:
                report["invalid"].append({"line": line, "reasons": reasons})
                continue

            signature = tuple(values[column] for column in headers)
            if signature in seen_rows:
                report["duplicates"].append(
                    {"line": line, "original_line": seen_rows[signature]}
                )
                continue
            review_id = values["review_id"]
            if review_id in seen_ids:
                report["invalid"].append({
                    "line": line,
                    "reasons": ["Conflicting review_id; first seen on line " + str(seen_ids[review_id])],
                })
                continue
            seen_rows[signature] = line
            seen_ids[review_id] = line
            report["valid_records"] += 1

            brand = values["brand"]
            if not brand or brand.casefold() == "unknown":
                report["unknown_brand_records"] += 1
                report["warnings"].append({"line": line, "reason": "Unknown brand; excluded from brand counts"})
            else:
                brands[brand] += 1

            synthetic = values["source_platform"].casefold() == "synthetic"
            if synthetic:
                report["synthetic_records"] += 1
                report["warnings"].append({"line": line, "reason": "Synthetic test data; not real evidence"})
            link_usable = usable_url(values["source_url"])
            if not link_usable:
                report["warnings"].append({"line": line, "reason": "Missing or unusable source_url; internal testing only"})
            if not synthetic and link_usable:
                report["evidence_eligible_records"] += 1

    report["invalid_records"] = len(report["invalid"])
    report["duplicate_records"] = len(report["duplicates"])
    report["excluded_records"] = report["invalid_records"] + report["duplicate_records"]
    report["valid_records_by_brand"] = dict(sorted(brands.items()))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV)
    arguments = parser.parse_args(argv)
    try:
        report = validate_reviews(arguments.csv_path)
    except (OSError, UnicodeError, csv.Error, ValueError):
        print(
            "Cannot validate CSV: check file access, UTF-8 encoding, CSV syntax, "
            "and unique headers including " + ", ".join(REQUIRED_COLUMNS),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["excluded_records"] else 0


if __name__ == "__main__":
    sys.exit(main())
