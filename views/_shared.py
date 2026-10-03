# shared helpers for the simple screens
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from core import Package, available_packages
from dispatcher import WebhookDispatcher

OUTBOX = ROOT / "outbox.jsonl"


@st.cache_resource(show_spinner="Loading data and models...")
def _load(key, mtime):
    return Package(key)


def current_package():
    keys = available_packages()
    if not keys:
        st.info("No business data loaded yet. In a terminal in the app folder, run `python make_package.py retail` "
                "(see README), then refresh.")
        st.stop()
    key = st.session_state.get("dataset") or keys[0]
    pkg_file = ROOT / "packages" / key / "package.json"
    return _load(key, pkg_file.stat().st_mtime)


def dispatcher():
    try:
        return WebhookDispatcher(url=st.session_state.get("dispatch_url"), secret=st.session_state.get("dispatch_secret"), outbox=OUTBOX)
    except (ValueError, RuntimeError):
        return WebhookDispatcher(url=None, outbox=OUTBOX)


def historical_note(P):
    st.caption(f"Historical data: '{'today'}' is simulated as {P.end.date()}, the last day in the {P.meta['name']} data.")


STATUS_TEXT = {"sent": "action sent", "dry_run": "practice: action would be sent", "withheld_holdout": "control group (no action)",
               "skipped_by_user": "skipped by you", "failed": "sending failed"}


def plain_status(s):
    return STATUS_TEXT.get(s, s.replace("_", " "))

TEAL, GREY, RED = "#0F766E", "#94A3B8", "#B91C1C"


def money(x, cur="£"):
    if x >= 1e6:
        return f"{cur}{x/1e6:.1f}M"
    if x >= 1e3:
        return f"{cur}{x/1e3:.1f}k"
    return f"{cur}{x:,.0f}"


def kpi(col, label, value, sub=None, help=None):
    with col.container(border=True):
        st.metric(label, value, help=help)
        if sub:
            st.caption(sub)


def page_header(title, subtitle=None):
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
