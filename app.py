"""Customer Growth Intelligence - start here:  streamlit run app.py

Simple screens: Today (what to act on), Results (did it help), System health (can we trust it).
Details live under "Advanced". Datasets are loaded from packages/<name>/ (see make_package.py).
"""
import os

import streamlit as st

from core import available_packages
from dispatcher import WebhookDispatcher

st.set_page_config(page_title="Customer Growth Intelligence", page_icon="📦", layout="wide")


def _flag(name):
    """True if set as an environment variable or in Streamlit secrets (Streamlit Community Cloud)."""
    if os.environ.get(name, "").lower() in ("1", "true", "yes"):
        return True
    try:
        return str(st.secrets.get(name, "")).lower() in ("1", "true", "yes")
    except Exception:
        return False


PUBLIC_DEMO = _flag("PUBLIC_DEMO")      # public deployment: practice mode only, no webhook settings

NAMES = {"retail": "Online Retail II (UK)"}
keys = available_packages()
with st.sidebar:
    st.markdown("### Customer Growth Intelligence")
    if keys:
        st.selectbox("Business data", keys, format_func=lambda k: NAMES.get(k, k), key="dataset")
    else:
        st.warning("No dataset package yet. Run `python make_package.py retail` (see README).")
    if PUBLIC_DEMO:
        st.session_state["dispatch_url"], st.session_state["dispatch_secret"] = "", ""
    else:
        with st.expander("Sending settings"):
            st.text_input("Webhook URL (blank = practice mode)", value=os.environ.get("WEBHOOK_URL", ""), key="dispatch_url")
            st.text_input("Signing secret", value=os.environ.get("WEBHOOK_SECRET", ""), type="password", key="dispatch_secret")
    try:
        mode = WebhookDispatcher(url=st.session_state.get("dispatch_url"), secret=st.session_state.get("dispatch_secret")).mode
    except (ValueError, RuntimeError) as e:
        st.error(str(e)); mode = "DRY-RUN"
    st.caption("🔴 LIVE - actions are really sent" if mode == "LIVE" else
               ("🟢 Public demo - practice mode, nothing is sent" if PUBLIC_DEMO else "🟢 Practice mode - nothing is sent"))

pages = {
    "": [st.Page("views/overview.py", title="Overview", icon="🏠", default=True),
         st.Page("views/today.py", title="Today", icon="📋"),
         st.Page("views/results.py", title="Results", icon="📈"),
         st.Page("views/health.py", title="System health", icon="🩺"),
         st.Page("views/simulation.py", title="Simulation lab", icon="🧪"),
         st.Page("views/methodology.py", title="How it works", icon="🧭")],
    "Advanced": [st.Page("views/adv_readout.py", title="Experiment details", icon="🔬")],
}
st.navigation(pages).run()
