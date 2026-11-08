from hashlib import sha256
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from streamlit.testing.v1 import AppTest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from business_report_demo import FROZEN_IDS, build_air_purifier_demo, load_demo_sources
from business_report_view import BusinessReportView, CommentSource, ReportItem


def source(label="S01", status="raw"):
    return CommentSource(label, "abcdefghijk", f"comment-{label}", "Test evidence.", "", status)


class BusinessReportViewTests(unittest.TestCase):
    def test_counts_distinct_comments_and_videos(self):
        item = ReportItem("Need", "", ("S01", "S01", "S02"))
        report = BusinessReportView("Topic", True, (source(), source("S02")), topics=(item,))
        self.assertEqual(report.mentions(item), 2)
        self.assertEqual(report.video_count, 1)

    def test_production_view_rejects_raw_evidence(self):
        item = ReportItem("Need", "", ("S01",))
        with self.assertRaisesRegex(ValueError, "eligible source"):
            BusinessReportView("Topic", False, (source(),), needs=(item,))
        view = BusinessReportView("Topic", False, (source(status="validated"),), needs=(item,))
        self.assertEqual(view.validated_count, 1)

    def test_demo_cannot_reference_missing_source(self):
        with self.assertRaisesRegex(ValueError, "eligible source"):
            BusinessReportView("Topic", True, (source(),), needs=(ReportItem("Need", "", ("S02",)),))

    def test_demo_source_is_parsed_without_executing_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.py"
            raw = "Example  text\nwith original spacing."
            rows = [("abcdefghijk", comment, "2026-01-01T00:00:00Z", raw) for comment in FROZEN_IDS]
            path.write_text(f"raise RuntimeError('Do not run')\nFROZEN = {rows!r}\n")
            with self.assertRaisesRegex(ValueError, "evidence text was changed"):
                load_demo_sources(path)
            with patch("business_report_demo.FROZEN_TEXT_HASHES", (sha256(raw.encode()).hexdigest(),) * 3):
                sources = load_demo_sources(path)
            self.assertEqual(sources[0].text, raw)
            view = build_air_purifier_demo(sources)
            self.assertEqual(view.validated_count, 0)
            self.assertEqual([view.mentions(item) for item in view.topics], [2, 2, 1])

    def test_streamlit_renders_sections_and_chart(self):
        demo = build_air_purifier_demo(tuple(source(f"S{i:02}", "unverified") for i in range(1, 4)))
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from business_report_ui import render_business_report\n"
            "render_business_report(st.session_state.demo)\n"
        )
        app.session_state["demo"] = demo
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 3)
        self.assertIn("商业机会", [heading.value for heading in app.header])
        self.assertEqual(len(app.get("vega_lite_chart")), 1)
