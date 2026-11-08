"""Independent offline Streamlit preview. No live API or production entry point."""

import argparse

import streamlit as st

from business_report_demo import build_air_purifier_demo, load_demo_sources
from business_report_ui import render_business_report


def main():
    st.set_page_config(page_title="Business Insight Report", page_icon="◈", layout="wide")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", help="Path to the existing private frozen Air Purifier input")
    args = parser.parse_args()
    if not args.sources:
        st.info("请通过 --sources 指定已有的本地 Air Purifier 冻结原文。")
        return
    try:
        report = build_air_purifier_demo(load_demo_sources(args.sources))
    except (OSError, SyntaxError, TypeError, ValueError, IndexError):
        st.error("无法读取预览所需的 Air Purifier 冻结原文。请检查本地来源文件。")
        return
    render_business_report(report)


if __name__ == "__main__":
    main()
