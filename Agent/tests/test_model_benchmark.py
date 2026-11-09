from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch
from urllib.error import URLError

import model_benchmark as bench
from analysis_control import ControlError
from benchmark_diagnostics import BenchmarkStructureError, parse_benchmark_batch
from business_research_dashboard import dashboard_markup
from multi_comment_research import batch_messages, evidence_spans, process_batch_comment
from test_multi_comment_research import batch_policy, inquiry, rows


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.ledger = self.directory / "budget.sqlite"
        self.batches = []
        manifest = {"prompt_sha256": bench._digest(bench.BATCH_PROMPT), "schema": bench.VERSION,
                    "python_sha256": {}, "batches": []}
        for topic in ("Earbuds", "Air Purifier", "Smartphone Battery"):
            rows = [{"comment_id": f"{topic.split()[0]}-{n}", "video_id": "testVideo01",
                     "review_text": f"What price should I pay for synthetic model {n}?"}
                    for n in range(4)]
            self.batches.append((topic, rows))
            manifest["batches"].append({"topic": topic, "sources": [
                {"comment_id": row["comment_id"], "video_id": row["video_id"],
                 "text_sha256": bench._digest(row["review_text"])} for row in rows]})
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(manifest))
        self.policy = {**batch_policy(), "_config_digest": "fake-approved-config"}
        settings = {"DASHSCOPE_API_KEY": "fake-key"}
        for mock in (
            patch.multiple(bench, MANIFEST=path, MANIFEST_SHA256=sha256(path.read_bytes()).hexdigest(),
                           LEDGER_PATH=self.ledger),
            patch.object(bench, "load_policy", side_effect=lambda: self.policy),
            patch.object(bench, "load_local_settings", return_value=settings),
            patch("classify_reviews.request.build_opener"),
        ):
            result = mock.start()
            self.addCleanup(mock.stop)
            if result:
                self.opener = result.return_value
        self.opener.open.side_effect = self.response
        self.run_flags = {"data_confirmed": True, "paid_confirmed": True, "workspace_confirmed": True}

    def response(self, request, **kwargs):
        payload = json.loads(request.data)
        model_text = json.dumps({"reviews": [{"key": f"R{i:02d}", "analysis": inquiry()} for i in range(1, 5)]})
        return StringIO(json.dumps({"model": payload["model"],
                                    "usage": {"prompt_tokens": 1500, "completion_tokens": 250, "total_tokens": 1750},
                                    "choices": [{"finish_reason": "stop", "message": {"content": model_text}}]}))

    def run_benchmark(self):
        return bench.run_benchmark(self.batches, **self.run_flags)

    def test_exact_caps_same_messages_and_blind_stages(self):
        session = self.run_benchmark()
        self.addCleanup(session.clear)
        self.assertEqual(self.opener.open.call_count, 6)
        requests = [json.loads(call.args[0].data) for call in self.opener.open.call_args_list]
        self.assertEqual([p.pop("model") for p in requests], [bench.CANDIDATE] * 3 + [bench.QWEN_MODEL] * 3)
        self.assertEqual(requests[:3], requests[3:])
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})
        self.assertFalse(requests[0]["enable_thinking"])
        with closing(sqlite3.connect(self.ledger)) as db, db:
            costs = [Decimal(row[0]) for row in db.execute("SELECT cost FROM reservations ORDER BY rowid")]
        self.assertEqual(costs, [Decimal(".046")] * 3 + [Decimal(".0148")] * 3)
        self.assertNotIn(b"synthetic model", self.ledger.read_bytes())
        self.assertEqual(set(session.raw_outputs()), {"A", "B"})
        self.assertNotIn(bench.CANDIDATE, str(session.raw_outputs()))
        with self.assertRaises(ControlError):
            session.reports()
        session.score("raw", {label: dict.fromkeys(bench.RAW_SCORES, 0) for label in "AB"})
        self.assertEqual(len(session.reports()["A"]), 3)
        with self.assertRaises(ControlError):
            session.reveal()
        session.score("report", {label: dict.fromkeys(bench.REPORT_SCORES, 0) for label in "AB"})
        self.assertEqual(set(session.reveal()), set(bench.RATES))
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 6)

    def test_offline_phase_k_replay_separates_model_claims_and_display(self):
        source = rows()[:3]
        source[0]["review_text"] = (
            "I am not happy with my Echo Wave R4, friends complain about call quality "
            "and I keep having the earbuds cutting the sound when I listen to music "
            "and I don't like how they sit in my ear."
        )
        source[1]["review_text"] = "Thanks!"
        ids = [span["id"] for span in evidence_spans(source[0]["review_text"])]
        wrong_brand = {**inquiry(), "brand": {"name": "Uncited Brand", "evidence_ids": ids},
                       "product_model": {"name": "Echo Wave R4", "evidence_ids": ids},
                       "feedback_types": [{"type": "Actual Usage Experience", "evidence_ids": ids}]}
        irrelevant = {**inquiry(), "feedback_types": [{"type": "Irrelevant", "evidence_ids": ["S01"]}]}
        decoded = {"reviews": [{"key": "R01", "analysis": wrong_brand},
                               {"key": "R02", "analysis": irrelevant}]}
        # A valid request plan is needed for authorization checks even when replaying.
        plans = bench._locked_batches(self.batches, json.loads(bench.MANIFEST.read_text()))
        execution = bench._BenchmarkExecution(self.policy, self.ledger, plans, monotonic() + 60)
        replay = bench.replay_phase_k("Wireless Earbuds", source, decoded,
                                      execution=execution, model=bench.QWEN_MODEL)
        self.assertTrue(replay.batch_structure_ok)
        self.assertTrue(replay.view.research_layout)
        self.assertEqual(replay.view.coverage.formal, 0)
        self.assertEqual(replay.reviews["R01"]["validation"], "Invalid")
        self.assertTrue(replay.reviews["R01"]["entity_rechecked"])
        self.assertIsNotNone(replay.reviews["R01"]["report_source"])
        self.assertIsNone(replay.reviews["R02"]["report_source"])
        self.assertEqual(replay.reviews["R03"]["validation"], "Missing")
        self.assertIsNone(replay.reviews["R03"]["report_source"])
        markup = dashboard_markup(replay.view, mode="synthetic")
        self.assertIn("听音乐时断音", markup)
        self.assertIn("转述他人反馈", markup)
        self.assertNotIn("Uncited Brand", markup)
        self.assertEqual(decoded["reviews"][0]["analysis"], wrong_brand)
        self.opener.open.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_price_tradeoff_is_qualitative_purchase_evidence_only(self):
        source = rows()[:4]
        cases = (
            ("I am choosing between the fictional Slatefin Arc A and Cedarloop Mini earbuds. "
             "Is the Arc A worth paying $20 more for if I mostly use them for phone calls?",
             "Purchase Inquiry"),
            ("Thanks for the video!", "Irrelevant"),
            ("I bet the batteries will eventually fail.", "Actual Usage Experience"),
            ("My friend says these earbuds keep cutting out.", "Actual Usage Experience"),
        )
        replies = []
        for index, (row, (text, label)) in enumerate(zip(source, cases), 1):
            row["review_text"] = text
            analysis = inquiry()
            analysis["feedback_types"] = [{"type": label, "evidence_ids": [
                span["id"] for span in evidence_spans(text)
            ]}]
            replies.append({"key": f"R{index:02d}", "analysis": analysis})

        plans = bench._locked_batches(self.batches, json.loads(bench.MANIFEST.read_text()))
        execution = bench._BenchmarkExecution(self.policy, self.ledger, plans, monotonic() + 60)
        replay = bench.replay_phase_k("Wireless Earbuds", source, {"reviews": replies},
                                      execution=execution, model=bench.QWEN_MODEL)

        self.assertEqual(replay.view.coverage.formal, 0)
        self.assertIsNotNone(replay.reviews["R01"]["report_source"])
        self.assertTrue(replay.view.purchase)
        self.assertFalse(replay.view.needs)
        self.assertTrue(all(replay.reviews[key]["validation"] != "Valid" for key in ("R03", "R04")))
        self.assertIsNone(replay.reviews["R02"]["report_source"])
        self.opener.open.assert_not_called()

    def test_three_independent_confirmations_and_source_integrity(self):
        for flag in self.run_flags:
            with self.subTest(flag=flag), self.assertRaises(ControlError):
                bench.run_benchmark(self.batches, **{**self.run_flags, flag: False})
        self.batches[0][1][0]["review_text"] += " changed"
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.opener.open.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_transport_failure_stops_and_reserved_call_cannot_retry(self):
        self.opener.open.side_effect = URLError("synthetic private diagnostic")
        with self.assertRaisesRegex(ControlError, "^Benchmark stopped"):
            self.run_benchmark()
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 1)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            self.assertEqual(db.execute("SELECT cost FROM reservations").fetchall(), [("0.046",)])

    def test_wrong_mode_stops_before_baseline(self):
        def response(request, **kwargs):
            body = json.load(self.response(request))
            body["choices"][0]["message"]["reasoning_content"] = "synthetic thinking"
            return StringIO(json.dumps(body))
        self.opener.open.side_effect = response
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 1)

    def test_full_reservation_must_fit_shared_utc_day_before_first_call(self):
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("CREATE TABLE reservations(day TEXT, run TEXT, cost TEXT, tokens INTEGER)")
            db.execute("INSERT INTO reservations VALUES(?, 'web-research', '0.83', 0)", (day,))
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.opener.open.assert_not_called()

    def test_non_json_object_stops_before_baseline(self):
        def response(request, **kwargs):
            body = json.load(self.response(request))
            body["choices"][0]["message"]["content"] = "[]"
            return StringIO(json.dumps(body))
        self.opener.open.side_effect = response
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 1)

    def test_structural_failure_stops_before_next_request_and_only_reserves(self):
        def response(request, **kwargs):
            body = json.load(self.response(request))
            content = json.loads(body["choices"][0]["message"]["content"])
            content["reviews"][2]["analysis"]["sentiment"] = "PRIVATE_MOCK_GENERATED_VALUE"
            body["choices"][0]["message"]["content"] = json.dumps(content)
            return StringIO(json.dumps(body))
        self.opener.open.side_effect = response
        with self.assertRaises(BenchmarkStructureError) as caught:
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 1)
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic["first_stage"], "schema")
        self.assertEqual(diagnostic["entries"][2]["expected_ordinal"], 3)
        self.assertIn(("INVALID_ENUM", "sentiment"), diagnostic["entries"][2]["errors"])
        self.assertNotIn("PRIVATE_MOCK_GENERATED_VALUE", repr(diagnostic))
        self.assertNotIn(b"PRIVATE_MOCK_GENERATED_VALUE", self.ledger.read_bytes())
        with closing(sqlite3.connect(self.ledger)) as db:
            self.assertEqual(db.execute("SELECT cost FROM reservations").fetchall(), [("0.046",)])

    def test_revoked_authorization_stops_before_next_request(self):
        def response(request, **kwargs):
            body = self.response(request)
            self.policy = None
            return body
        self.opener.open.side_effect = response
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.assertEqual(self.opener.open.call_count, 1)

    def test_manifest_edit_prevents_sending_and_reservation(self):
        bench.MANIFEST.write_text(bench.MANIFEST.read_text() + " ")
        with self.assertRaises(ControlError):
            self.run_benchmark()
        self.opener.open.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_expiration_removes_content_and_prevents_late_reveal(self):
        expired = bench.BenchmarkSession({"A": ["synthetic"]}, {}, {"A": bench.CANDIDATE}, {}, monotonic() - 1)
        expired._data._timer.join(1)
        self.assertEqual(expired.raw_outputs(), {})
        with self.assertRaises(ControlError):
            expired.reveal()


class BenchmarkDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.rows = rows()[:3]
        self.items = [{"key": f"R{i:02d}", "analysis": inquiry()} for i in range(1, 4)]

    def parse(self):
        return parse_benchmark_batch(json.dumps({"reviews": self.items}), self.rows)

    def failure(self):
        with self.assertRaises(BenchmarkStructureError) as caught:
            self.parse()
        return caught.exception.diagnostic

    def test_valid_and_reordered_items_match_prompt_keys(self):
        messages = batch_messages(self.rows, "Test")
        self.assertIn('{"reviews":[{"key":"R01","analysis":{...}}]}', messages[0]["content"])
        self.assertIn('schema_version="real-analysis-4"', messages[0]["content"])
        requested = json.loads(messages[1]["content"])["reviews"]
        self.assertEqual([item["key"] for item in requested], [item["key"] for item in self.items])
        self.items.reverse()
        decoded, diagnostic = self.parse()
        self.assertEqual(decoded["reviews"], self.items)
        self.assertTrue(diagnostic["json_parsed"] and diagnostic["mapping_ok"] and diagnostic["item_count_ok"])
        self.assertEqual([entry["expected_ordinal"] for entry in diagnostic["entries"]], [3, 2, 1])
        self.assertTrue(all(entry["wire_schema_ok"] and entry["evidence_ok"] for entry in diagnostic["entries"]))

    def test_json_and_envelope_are_separate_stages(self):
        for content, stage, code, parsed in (
            ("[", "json", "JSON_INVALID", False),
            (None, "json", "CONTENT_TYPE", False),
            ('{"reviews": [], "PRIVATE_FIELD": 1}', "envelope", "BATCH_ENVELOPE", True),
        ):
            with self.subTest(stage=stage), self.assertRaises(BenchmarkStructureError) as caught:
                parse_benchmark_batch(content, self.rows)
            d = caught.exception.diagnostic
            self.assertEqual((d["first_stage"], d["code"], d["json_parsed"]), (stage, code, parsed))
            self.assertNotIn("PRIVATE_FIELD", repr(d))

    def test_unrecognized_duplicate_and_missing_keys_have_distinct_counts(self):
        self.items[0]["key"] = "PRIVATE_UNKNOWN_KEY"
        self.items[1]["key"] = "R03"
        d = self.failure()
        self.assertEqual(d["first_stage"], "mapping")
        self.assertTrue(d["item_count_ok"])
        self.assertFalse(d["mapping_ok"])
        self.assertEqual((d["missing_ordinals"], d["duplicate_ordinals"], d["unrecognized_keys"]), ([1, 2], [3], 1))
        self.assertNotIn("PRIVATE_UNKNOWN_KEY", repr(d))

    def test_missing_entry_preserves_other_entry_status(self):
        self.items.pop(1)
        d = self.failure()
        self.assertEqual((d["first_stage"], d["expected_items"], d["returned_items"]), ("mapping", 3, 2))
        self.assertEqual(d["missing_ordinals"], [2])
        self.assertTrue(all(entry["schema_ok"] for entry in d["entries"]))

    def test_missing_analysis_is_an_entry_failure(self):
        del self.items[1]["analysis"]
        d = self.failure()
        self.assertEqual(d["first_stage"], "entry")
        self.assertEqual(d["entries"][1]["errors"], [("MISSING_ANALYSIS", "$")])

    def test_safe_schema_errors_and_nonexistent_source_span(self):
        del self.items[0]["analysis"]["sentiment"]
        self.items[0]["analysis"]["brand"]["name"] = ["PRIVATE_CONTENT"]
        self.items[1]["analysis"]["feedback_types"][0]["evidence_ids"] = ["PRIVATE_FACT_ID"]
        self.items[2]["analysis"]["feedback_types"][0]["evidence_ids"] = ["S99"]
        self.items[2]["analysis"]["brand"]["PRIVATE_UNKNOWN_FIELD"] = "PRIVATE_VALUE"
        d = self.failure()
        self.assertEqual(d["first_stage"], "schema")
        self.assertIn(("MISSING_FIELD", "sentiment"), d["entries"][0]["errors"])
        self.assertIn(("TYPE_MISMATCH", "brand.name"), d["entries"][0]["errors"])
        self.assertIn(("EVIDENCE_STRUCTURE", "feedback_types.*.evidence_ids.*"), d["entries"][1]["errors"])
        self.assertIn(("UNEXPECTED_FIELD", "brand"), d["entries"][2]["errors"])
        self.assertNotIn("PRIVATE", repr(d))
        del self.items[2]["analysis"]["brand"]["PRIVATE_UNKNOWN_FIELD"]
        d = self.failure()
        self.assertTrue(d["entries"][2]["schema_ok"])
        self.assertFalse(d["entries"][2]["evidence_ok"])
        self.assertIn(("UNKNOWN_EVIDENCE_REFERENCE", "feedback_types.*.evidence_ids"), d["entries"][2]["errors"])
        self.items[:2] = [{"key": f"R{i:02d}", "analysis": inquiry()} for i in range(1, 3)]
        self.assertEqual(self.failure()["first_stage"], "evidence")
        self.assertNotIn("S99", repr(self.failure()))

    def test_existing_normalization_keeps_raw_schema_distinct(self):
        self.items[0]["analysis"]["facts"] = [{
            "id": "F01", "kind": "Usage Scenario", "summary": "The user asks about price.", "evidence_ids": ["S01"],
        }]
        decoded, d = self.parse()
        entry = d["entries"][0]
        self.assertEqual((entry["wire_schema_ok"], entry["schema_ok"], entry["normalization_count"]), (False, True, 2))
        raw = decoded["reviews"][0]["analysis"]
        self.assertEqual(raw["facts"][0]["id"], "F01")
        self.assertEqual(raw["facts"][0]["kind"], "Usage Scenario")
        processed = process_batch_comment(raw, self.rows[0])
        self.assertEqual(len(processed["normalizations"]), 2)
