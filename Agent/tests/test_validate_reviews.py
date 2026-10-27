import contextlib
import csv
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate_reviews.py"
SPEC = importlib.util.spec_from_file_location("validate_reviews", SCRIPT)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ValidateReviewsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "reviews.csv"

    def write_rows(self, rows, headers=validator.REQUIRED_COLUMNS):
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_existing_sample(self):
        report = validator.validate_reviews(validator.DEFAULT_CSV)
        self.assertEqual(report["total_records"], 9)
        self.assertEqual(report["valid_records"], 9)
        self.assertEqual(report["excluded_records"], 0)
        self.assertEqual(report["valid_records_by_brand"], {"Brand A": 3, "Brand B": 3, "Brand C": 3})
        self.assertEqual(report["synthetic_records"], 9)
        self.assertEqual(report["evidence_eligible_records"], 0)

    def test_invalid_duplicate_and_conflicting_records(self):
        original = ["1", "Good cleaning", "synthetic", "", "Brand A"]
        self.write_rows([
            original, original,
            ["1", "Different review", "synthetic", "", "Brand B"],
            ["2", "  ", "synthetic", "", "Brand A"],
            ["3", "Good battery", "synthetic", "", "Brand B"],
        ])
        report = validator.validate_reviews(self.path)
        self.assertEqual(report["total_records"], 5)
        self.assertEqual(report["valid_records"], 2)
        self.assertEqual(report["invalid_records"], 2)
        self.assertEqual(report["duplicate_records"], 1)
        self.assertEqual(report["excluded_records"], 3)
        self.assertEqual(report["duplicates"], [{"line": 3, "original_line": 2}])
        self.assertEqual(report["valid_records_by_brand"], {"Brand A": 1, "Brand B": 1})

    def test_each_required_value(self):
        for index in range(3):
            with self.subTest(index=index):
                row = ["1", "Good cleaning", "synthetic", "", "Brand A"]
                row[index] = " "
                self.write_rows([row])
                self.assertEqual(validator.validate_reviews(self.path)["invalid_records"], 1)

    def test_unknown_brands_are_retained_but_not_compared(self):
        self.write_rows([
            ["1", "Good", "synthetic", "", " Unknown "],
            ["2", "Good", "synthetic", "", ""],
        ])
        report = validator.validate_reviews(self.path)
        self.assertEqual(report["valid_records"], 2)
        self.assertEqual(report["unknown_brand_records"], 2)
        self.assertEqual(report["valid_records_by_brand"], {})

    def test_links_and_synthetic_evidence(self):
        self.write_rows([
            ["1", "Good", "review", "https://example.com/1", "Brand A"],
            ["2", "Good", "review", "", "Brand A"],
            ["3", "Good", "review", "not-a-url", "Brand A"],
            ["4", "Good", "synthetic", "https://example.com/4", "Brand A"],
        ])
        report = validator.validate_reviews(self.path)
        self.assertEqual(report["valid_records"], 4)
        self.assertEqual(report["evidence_eligible_records"], 1)

    def test_bom_quoted_comma_multiline_and_optional_columns(self):
        self.write_rows(
            [["1", "Good, but\nexpensive", "synthetic", "", " Brand A ", "Model X"]],
            (*validator.REQUIRED_COLUMNS, "product_model"),
        )
        self.assertEqual(validator.validate_reviews(self.path)["valid_records_by_brand"], {"Brand A": 1})

    def test_bad_row_width(self):
        self.write_rows([
            ["1", "Good", "synthetic", "", "Brand A", "extra"],
            ["2", "Good", "synthetic"],
        ])
        self.assertEqual(validator.validate_reviews(self.path)["invalid_records"], 2)

    def test_empty_input_and_bad_headers(self):
        for content in ("", "review_id,review_text\n", "review_id,review_text,source_platform,source_url,brand,brand\n"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    validator.validate_reviews(self.path)

    def test_header_only_is_zero_records(self):
        self.write_rows([])
        self.assertEqual(validator.validate_reviews(self.path)["total_records"], 0)

    def test_blank_lines_preserve_physical_line_numbers(self):
        self.path.write_text(
            '\n\nreview_id,review_text,source_platform,source_url,brand\n'
            '\n1,Good,synthetic,,Brand A\n1,Good,synthetic,,Brand A\n',
            encoding="utf-8",
        )
        report = validator.validate_reviews(self.path)
        self.assertEqual(report["total_records"], 2)
        self.assertEqual(report["duplicates"], [{"line": 6, "original_line": 5}])

    def test_cli_exit_codes_and_no_raw_data_in_output(self):
        secret = "PRIVATE_REVIEW_SENTINEL"
        self.write_rows([["1", secret, "synthetic", "", "Brand A"]])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(validator.main([str(self.path)]), 0)
        self.assertNotIn(secret, output.getvalue())
        self.write_rows([["1", "", "synthetic", "", "Brand A"]])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validator.main([str(self.path)]), 1)
        for content in ('review_id,review_text,source_platform,source_url,brand\n1,"unterminated', secret):
            self.path.write_text(content, encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(validator.main([str(self.path)]), 2)
            self.assertNotIn(secret, errors.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(validator.main([str(self.path.parent / "missing.csv")]), 2)


if __name__ == "__main__":
    unittest.main()
