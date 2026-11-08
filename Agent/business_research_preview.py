"""Local-only Phase K preview. Historical text is read from existing archives."""

from datetime import datetime, timezone
import json
from pathlib import Path

import streamlit as st

from business_report_live import build_business_view
from business_report_ui import render_business_report
from evidence_analysis import evidence_spans
from multi_comment_research import entity_source_observations, process_batch_comment, VERSION
from session_memory import SessionResult


def _response(text, label, brand="unknown", model="unknown", *, facts=()):
    ids = [span["id"] for span in evidence_spans(text)]
    def entity(name):
        return {"name": name, "evidence_ids": ids if name != "unknown" else []}
    return {"schema_version": VERSION, "feedback_types": [{"type": label, "evidence_ids": ids}],
            "brand": entity(brand), "product_model": entity(model), "sentiment": "Neutral",
            "facts": [{"id": f"f{i:02d}", "kind": kind, "summary": summary, "evidence_ids": ids}
                      for i, (kind, summary) in enumerate(facts, 1)],
            "potential_needs": []}


def build_preview(samples, *, upgraded=True):
    state = {"results": [], "failures": [], "source_observations": [],
             "submitted": len(samples), "phase_k": True}
    for row, response in samples:
        processed = process_batch_comment(response, row)
        if processed["status"] == "Invalid":
            state["failures"].append({"review_id": row["review_id"], "processing": processed})
            if observation := entity_source_observations(processed, row):
                state["source_observations"].append(observation)
        else:
            state["results"].append({**row, "processing": processed})
    # The preview can compare against the ordinary report layout. Production
    # Phase K always uses the upgraded reading model.
    state["phase_k"] = upgraded
    return build_business_view("Wireless Earbuds", state, [], [row for row, _ in samples])


def _source_records(value):
    if isinstance(value, dict):
        if value.get("comment_id") and value.get("review_text") and value.get("video_id"):
            yield value
        for child in value.values():
            yield from _source_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _source_records(child)


def historical_samples(runtime=None):
    runtime = runtime or Path(__file__).with_name(".runtime")
    manifest = runtime / "phase_k_preview_sources.json"
    try:
        requested = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(requested, dict):
        return []
    samples = []
    for name, keys in requested.items():
        if Path(name).name != name or not name.endswith(".json") or not isinstance(keys, dict):
            continue
        path = runtime / name
        if path.resolve().parent != runtime.resolve():
            continue
        try:
            archive = json.loads(path.read_text(encoding="utf-8"))
            if datetime.fromisoformat(archive["delete_by"]) <= datetime.now(timezone.utc):
                continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
        records = {row["comment_id"]: row for row in _source_records(archive)}
        for cid, labels in keys.items():
            if cid not in records or not isinstance(labels, list) or len(labels) != 3 or not all(
                isinstance(label, str) for label in labels
            ):
                continue
            record = records[cid]
            row = {**record, "review_id": f"youtube:{cid}", "published_at": record.get("published_at", "")}
            samples.append((row, _response(row["review_text"], *labels)))
    return samples


def synthetic_samples():
    # Entirely fabricated examples. The preview never exposes their IDs as
    # YouTube links or includes them in the historical source tab.
    rows = (
        ("I have my Atlas Buds 2 and I keep having them cutting the sound when I listen to music.", "Actual Usage Experience", "Atlas Buds 2"),
        ("I use my Atlas Buds 2 and I have them dropping the audio when I listen to music.", "Actual Usage Experience", "Atlas Buds 2"),
        ("I don't like how they sit in my ears when I use my Atlas Buds 2.", "Actual Usage Experience", "Atlas Buds 2"),
        ("Is it true you need a paid subscription to use the recording function?", "Purchase Inquiry", "unknown"),
        ("Do I need to accept third party agreements for the extra controls?", "Purchase Inquiry", "unknown"),
        ("Which earbuds should I choose? I don't want to spend more than $90.", "Purchase Inquiry", "unknown"),
        ("Price?", "Purchase Inquiry", "unknown"),
        ("You can get the Atlas Buds 2 in Canada as low as USD 70.", "Product Discussion", "Atlas Buds 2"),
        ("I bought the Atlas Buds 2. $60 of the best money I ever spent.", "Product Discussion", "Atlas Buds 2"),
        ("I bought the Atlas Buds 2 and returned them because I couldn't get a seal in ears and went back to Nova Mini.", "Product Discussion", "Atlas Buds 2"),
        ("What would you recommend between the Atlas Buds 2 ($89) and the Nova Mini ($69)? I just connect them to my phone and listen to music.", "Purchase Inquiry", "unknown"),
        ("Not having an app is a selling feature.", "Product Discussion", "unknown"),
    )
    samples = []
    for i, (text, label, model) in enumerate(rows, 1):
        row = {"review_id": f"preview:{i}", "comment_id": f"mock-{i}", "video_id": "demoVideo01",
               "published_at": "", "review_text": text}
        samples.append((row, _response(text, label, model=model)))
    return samples


def main():
    st.set_page_config(page_title="Phase K · 消费者商业研究报告", layout="wide")
    source = st.radio("离线预览样本", ("历史耳机原文 · 模拟分析", "全合成示例"), horizontal=True)
    synthetic = source == "全合成示例"
    if synthetic:
        report = build_preview(synthetic_samples())
    else:
        if "history_started" not in st.session_state:
            st.session_state.history_started = True
            samples = historical_samples()
            if samples:
                st.session_state.history_report = SessionResult({"view": build_preview(samples)})
        cached = st.session_state.get("history_report")
        report = cached.get("view") if cached is not None else None
        if report is None:
            st.info("历史样本不可用或本会话已到期。请选择全合成示例。")
            return
        @st.fragment(run_every="30s")
        def expiry_watch():
            if not cached.get("view"):
                st.rerun()
        expiry_watch()
    render_business_report(
        report, compact=True, source_links_enabled=not synthetic,
        data_mode="synthetic" if synthetic else "historical",
    )


if __name__ == "__main__":
    main()
