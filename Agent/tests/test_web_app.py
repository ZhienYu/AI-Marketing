"""Automatic UI boundary tests; substitute responses only, no live requests."""
import contextlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_automatic_research import batch, policy
import automatic_research
import classify_reviews

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, "Install Agent/requirements.txt for UI tests")
class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.policy = self.stack.enter_context(patch("analysis_control.load_config", return_value=None))
        self.start = self.stack.enter_context(patch.object(automatic_research, "start_research", return_value={"mode": "live-read-only", "batch": batch(), "report": None, "reason": "权限未配置"}))
        self.settings = self.stack.enter_context(patch.object(classify_reviews, "load_local_settings", side_effect=AssertionError("No real key read")))
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "web_app.py"))

    def ready(self):
        self.app.run()
        self.app.text_input(key="keyword").set_value("Robotic Pool Cleaner").run()
        self.app.checkbox(key="privacy_accepted").check().run()

    def test_initial_ui_has_only_research_inputs_and_no_upload_or_requests(self):
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.text_input), 1)
        self.assertEqual(len(self.app.selectbox), 2)
        self.assertFalse(self.app.get("file_uploader"))
        self.assertFalse(self.app.get("download_button"))
        self.start.assert_not_called()

    def test_read_only_start_is_explicit_and_does_not_load_keys(self):
        self.ready()
        self.start.assert_not_called()
        self.app.button(key="start_research").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.start.call_count, 1)
        self.assertIsNone(self.start.call_args.kwargs["policy"])
        self.assertFalse(self.start.call_args.kwargs["paid_confirmed"])
        self.settings.assert_not_called()
        self.assertIn("research_result", self.app.session_state)

    def test_refresh_never_repeats_requests(self):
        self.ready()
        self.app.button(key="start_research").click().run()
        self.app.run()
        self.start.assert_called_once()

    def test_preview_groups_by_video_and_shows_metadata_audit(self):
        self.ready()
        self.app.button(key="start_research").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn(batch()["videos"][0]["video"]["title"], self.app.subheader[0].value)
        captions = " ".join(c.value for c in self.app.caption)
        self.assertIn("实际 1 条", captions)
        self.assertIn("异常 0 项", captions)
        self.start.assert_called_once()

    def test_long_comment_is_collapsible(self):
        self.start.return_value["batch"]["videos"][0]["comments"][0]["review_text"] *= 10
        self.ready()
        self.app.button(key="start_research").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("展开长评论" in e.label for e in self.app.expander))

    def test_paid_permission_needs_additional_explicit_confirmation(self):
        self.policy.return_value = policy()
        self.ready()
        self.assertFalse(self.app.button(key="start_research").disabled)
        self.app.checkbox(key="paid_confirmed").check().run()
        self.assertFalse(self.app.button(key="start_research").disabled)
        self.start.assert_not_called()
        self.app.button(key="start_research").click().run()
        self.assertTrue(self.start.call_args.kwargs["paid_confirmed"])

    def test_unpaid_start_remains_available_for_collection(self):
        self.policy.return_value = policy()
        self.ready()
        self.app.button(key="start_research").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.start.call_args.kwargs["paid_confirmed"])
        self.assertEqual(len(self.app.subheader), 1)

    def test_technical_issue_displays_separately_from_youtube_permission(self):
        self.policy.return_value = {**policy(), "token_bound_verified": False}
        self.ready()
        captions = " ".join(c.value for c in self.app.caption)
        self.assertIn("YouTube 用途授权：记录检查通过", captions)
        self.assertIn("技术与预算：模型", captions)
        self.assertFalse(self.app.button(key="start_research").disabled)

    def test_config_price_changes_revoke_stale_paid_confirmation(self):
        self.policy.return_value = policy()
        self.ready()
        self.app.checkbox(key="paid_confirmed").check().run()
        self.policy.return_value = {**policy(), "run_cny_limit": "0.9"}
        self.app.run()
        self.assertFalse(self.app.checkbox(key="paid_confirmed").value)
        self.assertFalse(self.app.button(key="start_research").disabled)

    def test_each_paid_run_requires_fresh_confirmation(self):
        self.policy.return_value = policy()
        self.ready()
        self.app.checkbox(key="paid_confirmed").check().run()
        self.app.button(key="start_research").click().run()
        self.app.run()
        self.assertFalse(self.app.checkbox(key="paid_confirmed").value)
        self.assertFalse(self.app.button(key="start_research").disabled)
        self.start.assert_called_once()

    def test_purpose_keyword_and_window_changes_clear_result(self):
        self.ready()
        for key, value in (("keyword", "Vacuum"), ("research_purpose", "competitor"), ("video_months", 3)):
            self.app.button(key="start_research").click().run()
            widget = self.app.text_input(key=key) if key == "keyword" else self.app.selectbox(key=key)
            widget.set_value(value).run()
            self.assertNotIn("research_result", self.app.session_state)
        self.assertEqual(self.start.call_count, 3)

    def test_report_display_uses_returned_result_not_new_generation(self):
        self.policy.return_value = policy()
        self.start.return_value = {"mode": "research", "batch": batch(), "report": "EXISTING RESPONSE SENTINEL"}
        self.ready()
        self.app.checkbox(key="paid_confirmed").check().run()
        self.app.button(key="start_research").click().run()
        self.assertIn("EXISTING RESPONSE SENTINEL", " ".join(m.value for m in self.app.markdown))
        self.app.run()
        self.start.assert_called_once()
        self.policy.return_value = None
        self.app.run()
        self.assertNotIn("research_result", self.app.session_state)

    def test_friendly_error_removes_old_result_without_sensitive_details(self):
        self.ready()
        self.app.button(key="start_research").click().run()
        self.start.side_effect = RuntimeError("FAKE_SECRET https://private.example")
        self.app.button(key="start_research").click().run()
        self.assertNotIn("research_result", self.app.session_state)
        self.assertNotIn("FAKE_SECRET", self.app.error[0].value)
        self.assertNotIn("https://", self.app.error[0].value)

    def test_clear_and_expiry_remove_results(self):
        self.ready()
        self.app.button(key="start_research").click().run()
        self.app.button(key="clear_session").click().run()
        self.assertNotIn("research_result", self.app.session_state)
        self.app.button(key="start_research").click().run()
        self.app.session_state["result_expiry"] = 0
        self.app.run()
        self.assertNotIn("research_result", self.app.session_state)


if __name__ == "__main__":
    unittest.main()
