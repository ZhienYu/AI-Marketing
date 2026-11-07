"""Real-shaped transport contracts using existing synthetic text; no external calls."""
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import automatic_research as auto
import analysis_control as control
import classify_reviews as classifier
import orchestrator
from real_analysis_schema import VERSION


def policy():
    return {"approved": True, "scopes": list(control.SCOPES | {"competitor_comparison"}),
        "approval_reference": "OFFLINE_TEST_NOT_AN_AUTHORIZATION", "project_reference": "TEST", "provider_terms_reference": "TEST",
        "expires_at": "2099-01-01T00:00:00Z", "source_scope": "public_videos_any_channel", "provider_region": "cn-beijing",
        "raw_storage": "memory_only", "model": control.QWEN_MODEL, "prices_verified": True, "token_bound_verified": True,
        "api_base_url": control.QWEN_BASE_URL, "enable_thinking": False, "response_format": "json_object", "token_bound_reference": "OFFLINE_TEST_ONLY",
        "price_reference": "TEST_PRICES_NOT_A_QUOTE", "input_cny_per_million": "0.8", "output_cny_per_million": "2",
        "daily_cny_limit": "1", "run_cny_limit": "1", "max_calls": 10, "max_input_tokens": 8000, "max_output_tokens": 2000, "run_token_limit": 100000}


def batch():
    fixture = orchestrator.read_fixture("pipeline_synthetic.json")
    comment = orchestrator.youtube_comments.normalize_comments(fixture["comment_threads"], "TESTvideo01", synthetic=True)[0]
    # Simulate an official response in memory only; this is NOT actual collected evidence.
    comment["is_synthetic"] = False
    video = orchestrator.youtube_search.normalize_videos(orchestrator.read_fixture("youtube_search_mock.json"))[0]
    return {"mode": "live-read-only", "collected_at": "2026-01-01T00:00:00Z", "searched_videos": 1,
        "comment_count": 1, "videos_with_comments": 1,
        "videos": [{"video": video, "comments": [comment], "failure_reason": None}]}


def response():
    original = batch()["videos"][0]["comments"][0]["review_text"]
    fixture = orchestrator.read_fixture("pipeline_synthetic.json")["classifications"]["youtube:pipeline-01"]["classification"]
    for item in fixture["product_aspects"]:
        if item["sentiment"] == "Positive":
            item["feedback"] = fixture["positive_aspects"][0]
    return {"schema_version": VERSION, "feedback_types": [{"type": "Actual Usage Experience", "quotes": [original]}],
        "brand": {"name": "DemoAqua", "quotes": ["DemoAqua"]}, "product_model": {"name": "DemoAqua R1", "quotes": ["DemoAqua R1"]},
        "sentiment": "Positive", "facts": [{"id": "good1", "kind": "positive_feedback", "summary": fixture["positive_aspects"][0], "quotes": [original], "aspect": "Battery Life"}], "potential_needs": []}


class AutomaticResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "budget.sqlite3"
        self.p = policy()

    def context(self, **updates):
        return control.Execution({**self.p, **updates}, "improvement", paid_confirmed=True, run_id="unit-run", ledger_path=self.ledger)

    def install_response(self, stack, value=None, usage=None):
        from evidence_analysis import VERSION as WIRE_VERSION, evidence_spans
        value = copy.deepcopy(response() if value is None else value)
        source = "price?" if value["feedback_types"][0]["type"] == "Purchase Inquiry" else batch()["videos"][0]["comments"][0]["review_text"]
        spans = evidence_spans(source)
        value["schema_version"] = WIRE_VERSION
        for item in value["feedback_types"] + value["facts"] + [value["brand"], value["product_model"]]:
            quotes = item.pop("quotes")
            ids = set()
            for quote in quotes:
                start = source.index(quote)
                ids.update(s["id"] for s in spans if s["start"] < start + len(quote) and s["end"] > start)
            item["evidence_ids"] = sorted(ids)
        body = {"model": control.QWEN_MODEL, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60} if usage is None else usage}
        opener = stack.enter_context(patch.object(classifier.request, "build_opener"))
        opener.return_value.open.side_effect = lambda *a, **k: io.StringIO(json.dumps(body))
        return opener

    def test_keyword_run_binds_one_real_source_and_reserves_once(self):
        import contextlib
        p = {**self.p, "budget_mode": control.KEYWORD_BUDGET_MODE,
             "token_bound_verified": False, "token_estimate_risk_acknowledged": True,
             "analysis_schema_version": auto.EVIDENCE_VERSION, "max_calls": 1,
             "analysis_prompt_sha256": hashlib.sha256(auto.PROMPT.encode()).hexdigest(),
             "max_output_tokens": 1500, "run_token_limit": 9500}
        with self.assertRaises(control.ControlError):
            control.Execution(p, "improvement", paid_confirmed=True, run_id="unbound", ledger_path=self.ledger)
        captured = batch()
        another = {**captured["videos"][0]["comments"][0], "comment_id": "secondary",
                   "source_url": "https://www.youtube.com/watch?v=TESTvideo01&lc=secondary",
                   "review_text": "different comment"}
        captured["videos"][0]["comments"].append(another)
        captured["comment_count"] = 2
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "multi_video_research", return_value=captured))
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE_UNIT_KEY"}))
            opener = self.install_response(stack)
            result = auto.start_research("Cleaner", "improvement", 6, policy=p, paid_confirmed=True, ledger_path=self.ledger)
        opener.return_value.open.assert_called_once()
        payload = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertNotIn("different comment", payload["messages"][1]["content"])
        self.assertEqual(result["audit"]["valid_records"], 2)
        self.assertEqual(result["collected"], 1)
        self.assertEqual(result["estimated_cny"], "0.000096")

    def test_missing_permission_is_read_only_and_never_loads_qwen_settings(self):
        with patch.object(orchestrator, "multi_video_research", return_value=batch()), patch.object(classifier, "load_local_settings", side_effect=AssertionError("No credentials")), patch.object(classifier, "classify_qwen", side_effect=AssertionError("No Qwen")):
            result = auto.start_research("Cleaner", "improvement", 6)
        self.assertEqual(result["mode"], "live-read-only")
        self.assertIsNone(result["report"])
        self.assertFalse(self.ledger.exists())

    def test_invalid_permission_or_no_paid_confirmation_still_collects_without_analysis(self):
        with patch.object(orchestrator, "multi_video_research", return_value=batch()) as fetch, patch.object(classifier, "load_local_settings", side_effect=AssertionError("No Qwen credentials")):
            for p, paid in (({**self.p, "approved": False}, True), (self.p, False), ({**self.p, "expires_at": "2020-01-01T00:00:00Z"}, True)):
                result = auto.start_research("Cleaner", "improvement", 6, policy=p, paid_confirmed=paid)
                self.assertEqual(result["mode"], "live-read-only")
                self.assertEqual(len(result["records"]), 1)
                self.assertEqual(result["audit"]["issues"], [])
                self.assertIsNone(result["report"])
            self.assertEqual(fetch.call_count, 3)
        self.assertFalse(self.ledger.exists())

    def test_full_pipeline_calls_existing_qwen_transport_and_returns_evidence_report(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "multi_video_research", return_value=batch()))
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE_UNIT_KEY"}))
            opener = self.install_response(stack)
            result = auto.start_research("Cleaner", "improvement", 6, policy=self.p, paid_confirmed=True, ledger_path=self.ledger)
            payload = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(result["mode"], "research")
        self.assertEqual(len(result["results"]), 1)
        self.assertIn("Evidence Appendix", result["report"])
        self.assertIn("TESTvideo01", result["report"])
        self.assertNotIn("人工 Mock", result["report"])
        self.assertNotIn("video_title", json.loads(payload["messages"][1]["content"]))
        self.assertIn("evidence", json.loads(payload["messages"][1]["content"]))
        self.assertEqual(payload["max_tokens"], 2000)
        self.assertEqual(list(Path(self.temp.name).glob("*.md")), [])

    def test_normalization_preserves_metadata_and_deduplicates(self):
        source = batch()
        source["videos"] *= 2
        records = auto.normalize_batch(source)
        self.assertEqual(len(records), 1)
        for field in ("comment_id", "video_id", "video_title", "video_url", "source_url", "published_at", "collected_at", "review_text", "brand"):
            self.assertIn(field, records[0])
        self.assertEqual(records[0]["brand"], "unknown")

    def test_normalization_rejects_preview_synthetic_and_wrong_source(self):
        for field, value in (("text_is_preview", True), ("is_synthetic", True), ("source_url", "https://example.com")):
            source = batch()
            source["videos"][0]["comments"][0][field] = value
            with self.assertRaises(ValueError):
                auto.normalize_batch(source)

    def test_no_direct_real_qwen_or_csv_bypass(self):
        for review in ({"review_text": "test"}, {"review_text": "test", "source_platform": "youtube"}):
            with patch.object(classifier.request, "build_opener") as opener, self.assertRaises(classifier.ClassificationError):
                classifier.classify_qwen(review, {}, "qwen-plus")
            opener.assert_not_called()

    def test_unsupported_quotes_and_brand_are_rejected(self):
        review = auto.normalize_batch(batch())[0]
        for field in ("brand", "feedback_types"):
            value = response()
            if field == "brand":
                value[field] = {"name": "InventedBrand", "quotes": ["InventedBrand"]}
            else:
                value[field][0]["quotes"] = ["invented quote"]
            with self.assertRaises(classifier.ClassificationError):
                auto.validate_output(value, review)

    def test_token_and_money_limits_before_http(self):
        review = auto.normalize_batch(batch())[0]
        for limits in ({"max_input_tokens": 1}, {"run_cny_limit": "0.000001"}, {"run_token_limit": 1}):
            ctx = self.context(**limits)
            with patch.object(classifier.request, "build_opener") as opener, self.assertRaises(control.ControlError):
                classifier.classify_qwen(review, {"DASHSCOPE_API_KEY": "FAKE"}, self.p["model"], automatic=ctx)
            opener.assert_not_called()

    def test_reservations_survive_new_run_and_no_comments_in_ledger(self):
        ctx = self.context(daily_cny_limit="0.012")
        payload = {"messages": [], "model": self.p["model"], "enable_thinking": False, "stream": False,
                   "max_tokens": self.p["max_output_tokens"], "response_format": {"type": "json_object"}}
        ctx.reserve(payload)
        second = control.Execution({**self.p, "daily_cny_limit": "0.012"}, "improvement", paid_confirmed=True, run_id="second-run", ledger_path=self.ledger)
        with self.assertRaises(control.ControlError):
            second.reserve(payload)
        self.assertNotIn(batch()["videos"][0]["comments"][0]["review_text"].encode(), self.ledger.read_bytes())

    def test_failed_request_records_failure_and_does_not_retry(self):
        records = auto.normalize_batch(batch())
        with patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}), patch.object(classifier.request, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("FAKE_SECRET https://private")
            result = auto.analyze_records(records, self.context())
        self.assertEqual(len(result["failures"]), 1)
        opener.return_value.open.assert_called_once()
        self.assertNotIn("FAKE_SECRET", result["report"])
        self.assertEqual(result["results"], [])

    def test_unknown_usage_stops_after_success_without_second_request(self):
        import contextlib
        records = auto.normalize_batch(batch())
        records.append({**records[0], "review_id": "youtube:unit-second", "comment_id": "unit-second", "source_url": "https://www.youtube.com/watch?v=TESTvideo01&lc=unit-second"})
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            opener = self.install_response(stack, usage={})
            result = auto.analyze_records(records, self.context())
        self.assertEqual(result["status"], "usage_unknown_stopped")
        self.assertEqual(result["unprocessed"], 1)
        opener.return_value.open.assert_called_once()

    def test_purchase_question_does_not_enter_usage_report(self):
        import contextlib
        value = response()
        record = auto.normalize_batch(batch())[0]
        record["review_text"] = "price?"
        value["feedback_types"] = [{"type": "Purchase Inquiry", "quotes": [record["review_text"]]}]
        value["brand"] = {"name": "unknown", "quotes": []}
        value["product_model"] = {"name": "unknown", "quotes": []}
        value["sentiment"] = "Neutral"
        value["facts"] = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            self.install_response(stack, value=value)
            result = auto.analyze_records([record], self.context())
        self.assertIn("有效自述使用反馈 0 条", result["report"])
        self.assertIn("Insufficient Evidence", result["report"])
        self.assertIn("购买／产品咨询", result["report"])
        self.assertIn("[S01 · YouTube 原文]", result["report"])
        self.assertIn("price?", result["report"])

    def test_rejected_model_output_displays_only_original_source_and_keeps_usage(self):
        import contextlib
        record = auto.normalize_batch(batch())[0]
        value = response()
        value["facts"][0]["summary"] = "UNSUPPORTED MODEL CLAIM"
        value["brand"]["name"] = "Unsupported Brand"
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            self.install_response(stack, value=value)
            result = auto.analyze_records([record], self.context())
        self.assertEqual(result["status"], "failed_stopped")
        self.assertEqual(result["results"], [])
        self.assertEqual(result["estimated_cny"], "0.000096")
        self.assertIn("模型结果未通过校验的来源", result["report"])
        self.assertIn(f"[S01 · YouTube 原文]({record['source_url']})", result["report"])
        self.assertIn("进入属性统计 0 条", result["report"])
        self.assertNotIn("UNSUPPORTED MODEL CLAIM", result["report"])

    def test_competitor_scope_is_separate(self):
        p = self.p.copy()
        p["scopes"] = list(control.SCOPES)
        with self.assertRaises(control.ControlError):
            control.Policy(p).check("competitor")

    def test_legacy_statistics_and_csv_batch_cannot_bypass_permission(self):
        from generate_insights import generate_insights
        from real_analysis_schema import compatibility_view
        original = auto.normalize_batch(batch())[0]
        row = {**original, **compatibility_view(response(), original)["classification"]}
        with self.assertRaises(classifier.ClassificationError):
            generate_insights({"mode": "qwen", "results": [row]})
        with patch.object(classifier, "save_json") as save, self.assertRaises(classifier.ClassificationError):
            classifier.analyze_batch([row], {}, "qwen", "qwen-plus", Path(self.temp.name) / "forbidden.json")
        save.assert_not_called()

    def test_changed_permission_config_stops_existing_execution(self):
        p = {**self.p, "_config_digest": "TEST_DIGEST"}
        ctx = control.Execution(p, "improvement", paid_confirmed=True, run_id="unit", ledger_path=self.ledger)
        with patch.object(control, "load_policy", return_value=None), self.assertRaises(control.ControlError):
            ctx.check()

    def test_per_run_call_limit_stops_with_remaining_records(self):
        import contextlib
        records = auto.normalize_batch(batch())
        records.append({**records[0], "review_id": "youtube:unit-second", "comment_id": "unit-second", "source_url": "https://www.youtube.com/watch?v=TESTvideo01&lc=unit-second"})
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            opener = self.install_response(stack)
            result = auto.analyze_records(records, self.context(max_calls=1))
        opener.return_value.open.assert_called_once()
        self.assertEqual(result["unprocessed"], 1)
        self.assertEqual(result["status"], "budget_stopped")

    def test_competitor_pipeline_uses_real_template_without_mock_labels(self):
        import contextlib
        ctx = control.Execution(self.p, "competitor", paid_confirmed=True, run_id="competitor-test", ledger_path=self.ledger)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            self.install_response(stack)
            result = auto.analyze_records(auto.normalize_batch(batch()), ctx)
        self.assertIn("Competitor Research", result["report"])
        self.assertIn("无法进行可靠竞品比较", result["report"])
        self.assertNotIn("人工 Mock", result["report"])

    def test_inactive_session_has_background_expiry_without_api_or_files(self):
        import session_memory
        with patch.object(session_memory, "Timer") as timer:
            stored = session_memory.SessionResult({"private_comment": "UNIT_ONLY"})
            self.assertEqual(stored.get("private_comment"), "UNIT_ONLY")
            callback = timer.call_args.args[1]
            callback()
            self.assertEqual(stored.snapshot(), {})
            timer.return_value.cancel.assert_called_once()

    def test_bad_source_identity_stops_before_key_access(self):
        records = auto.normalize_batch(batch())
        records[0]["source_url"] = "https://www.youtube.com/watch?v=TESTvideo01&lc=another-id"
        with patch.object(classifier, "load_local_settings") as settings, self.assertRaises(ValueError):
            auto.analyze_records(records, self.context())
        settings.assert_not_called()

    def test_budget_ledger_error_stops_before_http(self):
        ctx = self.context()
        with patch("analysis_control.sqlite3.connect", side_effect=__import__("sqlite3").OperationalError("locked")), self.assertRaises(control.ControlError):
            ctx.reserve({"messages": [], "model": self.p["model"], "enable_thinking": False, "stream": False,
                         "max_tokens": self.p["max_output_tokens"], "response_format": {"type": "json_object"}})

    def test_first_experiment_configuration_is_priced_but_not_authorized(self):
        p = json.loads((Path(auto.__file__).parent / "config/research_access.example.json").read_text())
        self.assertEqual(p["model"], control.QWEN_MODEL)
        self.assertEqual(p["api_base_url"], classifier.BEIJING_BASE_URL)
        self.assertFalse(p["enable_thinking"])
        self.assertEqual(p["price_input_tier_max_tokens"], 128000)
        self.assertEqual(p["max_calls"], 40)
        from decimal import Decimal
        fee = (Decimal(p["input_cny_per_million"]) * p["max_input_tokens"] + Decimal(p["output_cny_per_million"]) * p["max_output_tokens"]) / 1000000
        self.assertEqual(fee, Decimal("0.0104"))
        self.assertEqual(fee * p["max_calls"], Decimal("0.4160"))
        with self.assertRaises(control.ControlError):
            control.Policy(p).check("improvement")

    def test_wrong_model_thinking_price_and_budget_are_rejected(self):
        for updates in ({"model": "qwen-plus"}, {"enable_thinking": True}, {"response_format": "text"},
                        {"input_cny_per_million": "0.1"}, {"output_cny_per_million": "1"},
                        {"run_cny_limit": "1.01"}, {"daily_cny_limit": "2"},
                        {"api_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"},
                        {"token_bound_verified": False}, {"token_bound_reference": ""}):
            with self.subTest(updates=updates), self.assertRaises(control.ControlError):
                control.Policy({**self.p, **updates}).check("improvement")

    def test_actual_payload_mismatch_cannot_reserve_or_send(self):
        payload = {"messages": [], "model": self.p["model"], "enable_thinking": False, "stream": False,
                   "max_tokens": 2000, "response_format": {"type": "json_object"}}
        for updates in ({"model": "qwen-plus"}, {"enable_thinking": True}, {"max_tokens": 3000}, {"stream": True}, {"response_format": {"type": "text"}}):
            with self.subTest(updates=updates), self.assertRaises(control.ControlError):
                self.context().reserve({**payload, **updates})
        self.assertFalse(self.ledger.exists())

    def test_settings_endpoint_override_is_blocked_before_request(self):
        review = auto.normalize_batch(batch())[0]
        with patch.object(classifier.request, "build_opener") as opener, self.assertRaises(control.ControlError):
            classifier.classify_qwen(review, {"DASHSCOPE_API_KEY": "FAKE", "DASHSCOPE_BASE_URL": "https://unit.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"}, self.p["model"], automatic=self.context())
        opener.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_response_model_drift_stops_and_keeps_reservation(self):
        review = auto.normalize_batch(batch())[0]
        body = {"model": "different-model", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response())}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}}
        with patch.object(classifier.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.StringIO(json.dumps(body))
            with self.assertRaises(classifier.ClassificationError):
                classifier.classify_qwen(review, {"DASHSCOPE_API_KEY": "FAKE"}, self.p["model"], automatic=self.context())
        self.assertTrue(self.ledger.exists())
        opener.return_value.open.assert_called_once()

    def test_qualification_needs_evidence_and_improvement_report_contract(self):
        import contextlib
        value = response()
        from evidence_analysis import evidence_spans
        quote = evidence_spans(batch()["videos"][0]["comments"][0]["review_text"])[0]["text"]
        value["facts"].append({"id": "scene1", "kind": "usage_scenario", "summary": quote, "quotes": [quote]})
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(classifier, "load_local_settings", return_value={"DASHSCOPE_API_KEY": "FAKE"}))
            self.install_response(stack, value=value)
            result = auto.analyze_records(auto.normalize_batch(batch()), self.context())
        self.assertEqual(result["results"][0]["analysis"]["feedback_types"][0]["type"], "Actual Usage Experience")
        self.assertIn("Product Improvement Research", result["report"])
        self.assertIn("明确原始表达", result["report"])
        self.assertIn("E01", result["report"])
        self.assertIn("Insufficient Evidence", result["report"])
        self.assertFalse(list(Path(self.temp.name).glob("*.md")))

    def test_usage_above_reserved_bounds_is_rejected(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            self.install_response(stack, usage={"prompt_tokens": 8001, "completion_tokens": 40, "total_tokens": 8041})
            with self.assertRaises(classifier.ClassificationError):
                classifier.classify_qwen(auto.normalize_batch(batch())[0], {"DASHSCOPE_API_KEY": "FAKE"}, self.p["model"], automatic=self.context())

    def test_old_experiment_contract_cannot_enable_new_model_prompt(self):
        with self.assertRaises(control.ControlError):
            self.context(analysis_schema_version="real-analysis-2")

    def test_technical_readiness_is_not_platform_permission(self):
        gates = control.analysis_readiness({**self.p, "approved": False}, "improvement")
        self.assertTrue(gates["technical"]["ready"])
        self.assertFalse(gates["youtube"]["ready"])
        self.assertFalse(gates["ready"])
        self.assertTrue(gates["collection_enabled"])

    def test_missing_token_bound_does_not_claim_missing_youtube_permission(self):
        gates = control.analysis_readiness({**self.p, "token_bound_verified": False}, "improvement")
        self.assertTrue(gates["youtube"]["ready"])
        self.assertTrue(gates["provider"]["ready"])
        self.assertFalse(gates["technical"]["ready"])

    def test_third_party_and_competitor_scopes_are_independent(self):
        gates = control.analysis_readiness({**self.p, "provider_terms_reference": ""}, "improvement")
        self.assertTrue(gates["youtube"]["ready"])
        self.assertFalse(gates["provider"]["ready"])
        p = {**self.p, "scopes": list(control.SCOPES)}
        self.assertTrue(control.analysis_readiness(p, "improvement")["ready"])
        self.assertFalse(control.analysis_readiness(p, "competitor")["youtube"]["ready"])

    def test_technical_switch_off_only_skips_analysis(self):
        with patch.object(control, "ANALYSIS_ENABLED", False), patch.object(orchestrator, "multi_video_research", return_value=batch()), patch.object(classifier, "load_local_settings", side_effect=AssertionError("No Qwen key")):
            result = auto.start_research("Cleaner", "improvement", 6, policy=self.p, paid_confirmed=True)
        self.assertEqual(result["mode"], "live-read-only")
        self.assertEqual(len(result["records"]), 1)
        self.assertTrue(result["controls"]["youtube"]["ready"])
        self.assertFalse(result["controls"]["technical"]["ready"])
        with patch.object(control, "ANALYSIS_ENABLED", False), self.assertRaises(control.ControlError):
            self.context()

    def test_revocation_after_collection_retains_only_raw_preview(self):
        p = {**self.p, "_config_digest": "REVOKED_UNIT_CONFIG"}
        with patch.object(orchestrator, "multi_video_research", return_value=batch()), patch.object(control, "load_policy", return_value=None), patch.object(classifier, "load_local_settings", side_effect=AssertionError("No Qwen key")):
            result = auto.start_research("Cleaner", "improvement", 6, policy=p, paid_confirmed=True, ledger_path=self.ledger)
        self.assertEqual(result["mode"], "live-read-only")
        self.assertEqual(len(result["records"]), 1)
        self.assertIsNone(result["report"])
        self.assertFalse(self.ledger.exists())

    def test_invalid_source_keeps_validation_and_preview_without_qwen(self):
        data = batch()
        data["videos"][0]["comments"][0]["source_url"] += "wrong-id"
        with patch.object(orchestrator, "multi_video_research", return_value=data), patch.object(classifier, "load_local_settings", side_effect=AssertionError("No Qwen key")):
            result = auto.start_research("Cleaner", "improvement", 6, policy=self.p, paid_confirmed=True)
        self.assertTrue(result["audit"]["issues"])
        self.assertEqual(result["batch"]["comment_count"], 1)
        self.assertIsNone(result["report"])


if __name__ == "__main__":
    unittest.main()
