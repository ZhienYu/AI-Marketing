"""Safe, content-free diagnostics for the benchmark's structured response gate."""

from collections import Counter
import json

from analysis_control import ControlError
from evidence_analysis import VALIDATOR, evidence_spans, normalize_structure
from multi_comment_research import map_response, normalize_batch_wire


_FIELDS = frozenset({
    "schema_version", "feedback_types", "brand", "product_model", "sentiment",
    "facts", "potential_needs", "id", "kind", "summary", "name", "evidence_ids",
    "aspect", "type", "uncertainty", "validation_method",
})
_RULES = {
    "required": "MISSING_FIELD", "type": "TYPE_MISMATCH", "enum": "INVALID_ENUM",
    "const": "INVALID_CONSTANT", "additionalProperties": "UNEXPECTED_FIELD",
}
_ENTRY_LIMIT = 12
_ERROR_LIMIT = 8


class BenchmarkStructureError(ControlError):
    """The diagnostic may be surfaced without storing the rejected response."""

    def __init__(self, diagnostic):
        super().__init__("Benchmark stopped at the structured response gate.")
        self.diagnostic = diagnostic


def _safe_path(parts):
    return ".".join(
        "*" if type(part) is int else part if part in _FIELDS else "other"
        for part in parts
    ) or "$"


def _schema_codes(value):
    codes = set()
    for error in VALIDATOR.iter_errors(value):
        path = list(error.absolute_path)
        if error.validator == "required":
            missing = (key for key in error.validator_value if key not in error.instance)
            codes.update(("MISSING_FIELD", _safe_path([*path, key])) for key in missing)
        else:
            code = _RULES.get(error.validator, "SCHEMA_CONSTRAINT")
            if "evidence_ids" in path:
                code = "EVIDENCE_STRUCTURE"
            codes.add((code, _safe_path(path)))
    return sorted(codes)


def _reference_codes(value, row):
    allowed = {span["id"] for span in evidence_spans(row["review_text"])}
    groups = [(name, [value[name]]) for name in ("brand", "product_model")]
    groups.extend((name + ".*", value[name]) for name in ("feedback_types", "facts", "potential_needs"))
    return [("UNKNOWN_EVIDENCE_REFERENCE", path + ".evidence_ids")
            for path, items in groups if any(set(item["evidence_ids"]) - allowed for item in items)]


def parse_benchmark_batch(content, rows):
    """Validate the same wire contract for both models, without repairing facts or keys."""
    diagnostic = {
        "json_parsed": False, "expected_items": len(rows), "returned_items": None,
        "item_count_ok": None, "mapping_ok": None, "entries": [],
    }
    if not isinstance(content, str):
        raise BenchmarkStructureError({**diagnostic, "first_stage": "json", "code": "CONTENT_TYPE"})
    try:
        decoded = json.loads(content)
    except (ValueError, RecursionError):
        raise BenchmarkStructureError({**diagnostic, "first_stage": "json", "code": "JSON_INVALID"}) from None
    diagnostic["json_parsed"] = True
    if not isinstance(decoded, dict) or set(decoded) != {"reviews"} or not isinstance(decoded["reviews"], list):
        returned = decoded.get("reviews") if isinstance(decoded, dict) else None
        if isinstance(returned, list):
            diagnostic.update(returned_items=len(returned), item_count_ok=len(returned) == len(rows))
        raise BenchmarkStructureError({**diagnostic, "first_stage": "envelope", "code": "BATCH_ENVELOPE"})

    items = decoded["reviews"]
    expected = {f"R{index:02d}": index for index in range(1, len(rows) + 1)}
    keys = [expected.get(item["key"]) if isinstance(item, dict) and isinstance(item.get("key"), str)
            else None for item in items]
    counts = Counter(key for key in keys if key is not None)
    missing = [n for n in expected.values() if not counts[n]]
    duplicate = [n for n in expected.values() if counts[n] > 1]
    try:
        map_response(decoded, rows)
        mapped = True
    except ValueError:
        mapped = False
    diagnostic.update(
        returned_items=len(items), item_count_ok=len(items) == len(rows),
        mapping_ok=mapped and not missing,
        missing_ordinals=missing, duplicate_ordinals=duplicate,
        unrecognized_keys=sum(key is None and isinstance(item, dict) and isinstance(item.get("key"), str)
                              for item, key in zip(items, keys)),
        unusable_keys=sum(not isinstance(item, dict) or not isinstance(item.get("key"), str) for item in items),
        omitted_diagnostic_entries=max(0, len(items) - _ENTRY_LIMIT),
    )
    failures = set()
    for position, (item, ordinal) in enumerate(zip(items[:_ENTRY_LIMIT], keys[:_ENTRY_LIMIT]), 1):
        entry = {"position": position, "expected_ordinal": ordinal,
                 "wire_schema_ok": None, "schema_ok": None, "evidence_ok": None,
                 "normalization_count": 0}
        if not isinstance(item, dict) or set(item) != {"key", "analysis"}:
            codes = [("MISSING_ANALYSIS", "$") if isinstance(item, dict) and "analysis" not in item
                     else ("ENTRY_ENVELOPE", "$")]
            failures.add("entry")
        else:
            raw = item["analysis"]
            canonical, aliases = normalize_batch_wire(raw)
            value, normalized, issues = normalize_structure(canonical)
            wire_codes = _schema_codes(raw)
            codes = _schema_codes(value) if issues else []
            if issues and not codes:
                codes = [("DUPLICATE_FACT_ID", "facts.*.id")]
            entry.update(wire_schema_ok=not wire_codes, schema_ok=not codes,
                         normalization_count=len(aliases) + len(normalized),
                         wire_errors=wire_codes[:_ERROR_LIMIT])
            if codes:
                failures.add("schema")
            elif ordinal is not None and counts[ordinal] == 1:
                codes = _reference_codes(value, rows[ordinal - 1])
                entry["evidence_ok"] = not codes
                if codes:
                    failures.add("evidence")
        entry["errors"] = codes[:_ERROR_LIMIT]
        diagnostic["entries"].append(entry)

    first = next((stage for stage in ("entry", "schema", "evidence") if stage in failures), None)
    if not diagnostic["mapping_ok"]:
        first = "mapping"
    diagnostic["first_stage"] = first
    if first:
        raise BenchmarkStructureError(diagnostic)
    return decoded, diagnostic
