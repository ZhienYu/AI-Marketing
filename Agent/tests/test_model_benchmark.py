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
from test_multi_comment_research import batch_policy, inquiry


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
