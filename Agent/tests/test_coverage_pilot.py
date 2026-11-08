import io
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch

import analysis_control as control
import classify_reviews as classifier
import multi_comment_research as multi
from test_multi_comment_research import batch_policy, inquiry, rows


def candidates():
    return [{**row, "comment_id": f"coverage-{i}", "review_id": f"youtube:coverage-{i}",
             "source_url": f"https://www.youtube.com/watch?v={row['video_id']}&lc=coverage-{i}",
             "review_text": f"What price should I pay if I buy the model {i} cleaner?"}
            for i, row in enumerate(rows() * 2)]


class CoveragePilotTests(unittest.TestCase):
    def test_immutable_profiles_and_permission_gates(self):
        base = batch_policy()
        pilot = control.with_batch_profile(base, "pilot15")
        self.assertEqual((base["max_calls"], base["run_cny_limit"]), (3, "0.0444"))
        self.assertEqual((pilot["max_calls"], pilot["run_token_limit"], pilot["run_cny_limit"]), (4, 56000, "0.0592"))
        self.assertTrue(control.analysis_readiness(pilot, "improvement")["ready"])
        for bad in ({**pilot, "max_calls": 5}, {**pilot, "run_cny_limit": "0.0600"},
                    {**pilot, "approved": False}, {**pilot, "scopes": []}):
            self.assertFalse(control.analysis_readiness(bad, "improvement")["ready"])
        self.assertFalse(control.analysis_readiness(pilot, "invalid-purpose")["ready"])
        with self.assertRaises(control.ControlError):
            control.with_batch_profile(base, "pilot20")
        with self.assertRaises(control.ControlError):
            multi.run_batch_research("cleaner", candidates(), pilot, "improvement", paid_confirmed=False)

    def test_frozen_execution_rejects_sixteen_comments(self):
        pilot = control.with_batch_profile(batch_policy(), "pilot15")
        source = candidates()
        batches = [multi.batch_messages(source[i:i + 4]) for i in range(0, 16, 4)]
        with self.assertRaises(control.ControlError):
            control.Execution(pilot, "improvement", paid_confirmed=True, run_id="test", batch_messages=batches)

    def test_malformed_middle_batch_does_not_erase_good_batches(self):
        pilot = control.with_batch_profile(batch_policy(), "pilot15")
        source = candidates()
        groups, _ = multi.select_comments("cleaner", source, 11000, profile=control.BATCH_PROFILES["pilot15"])
        baseline, _ = multi.select_comments("cleaner", source, 11000)
        self.assertEqual([len(group) for group in groups], [4, 4, 4, 3])
        self.assertEqual(sum(groups, [])[:10], sum(baseline, []))
        calls = []

        def respond(req, *, timeout):
            payload = json.loads(req.data)
            supplied = json.loads(payload["messages"][1]["content"])["reviews"]
            calls.append(len(supplied))
            entries = [{"key": row["key"], "analysis": inquiry()} for row in supplied]
            if len(calls) == 3:
                entries[0]["analysis"]["feedback_types"][0]["evidence_ids"] = ["S99"]
            if len(calls) == 4:
                entries[0]["analysis"]["feedback_types"][0]["type"] = "Product Discussion"
            return io.StringIO(json.dumps({
                "model": pilot["model"], "usage": {"prompt_tokens": 600, "completion_tokens": 200, "total_tokens": 800},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": '{"reviews":[{"key":"R01' if len(calls) == 2 else json.dumps({"reviews": entries})
                }}],
            }))

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            classifier, "load_local_settings", return_value={"QWEN_API_KEY": "FAKE"}
        ), patch.object(classifier.request, "build_opener") as opener:
            opener.return_value.open.side_effect = respond
            ledger = Path(tmp) / "budget.sqlite3"
            result = multi.run_batch_research("cleaner", source, pilot, "improvement",
                                              paid_confirmed=True, ledger_path=ledger)
            with closing(sqlite3.connect(ledger)) as db:
                self.assertEqual(db.execute("SELECT cost, tokens FROM reservations").fetchall(),
                                 [("0.0148", 14000)] * 4)
        self.assertEqual(calls, [4, 4, 4, 3])
        self.assertEqual(result["status"], "partially_completed")
        self.assertEqual(result["submitted"], 15)
        self.assertEqual(len(result["results"]), 10)
        self.assertEqual([item["stage"] for item in result["failures"]], ["batch_json", "comment_validation"])
        self.assertEqual(result["batch_runs"][1]["status"], "批次 JSON 解析失败")
        self.assertEqual(sum(item == "报告层过滤" for item in result["report_outcomes"].values()), 1)

    def test_switching_profile_requires_fresh_paid_confirmation(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(multi.__file__).with_name("web_app.py")
        with patch.object(control, "load_config", return_value=batch_policy()):
            app = AppTest.from_file(str(app_file)).run()
            self.assertEqual(app.radio(key="batch_profile").value, "standard")
            self.assertTrue(any("¥0.0444" in item.value for item in app.caption))
            app.checkbox(key="paid_confirmed").check().run()
            app.radio(key="batch_profile").set_value("pilot15").run()
            self.assertFalse(app.exception)
            self.assertFalse(app.checkbox(key="paid_confirmed").value)
            self.assertTrue(any("目标 15 条" in item.value and "4 次" in item.value
                                and "¥0.0592" in item.value for item in app.caption))
