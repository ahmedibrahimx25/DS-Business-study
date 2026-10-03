# pages/4_Experiment_readout.py - did the action work? Treatment vs holdout, from the dispatcher's outbox.jsonl.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
import experiment as ex

# Outcome columns already present in the scored files (historical, so only usable as an A/A check)
HISTORICAL = {
    "packages/retail/orders.csv": ("order_id", ["returned_30d"]),
}

st.title("Experiment readout - details")
st.caption("Compares contacted customers (treatment) with the holdout who deliberately weren't. "
           "This is the only part of the system that can show whether an action changes behaviour.")
tab_read, tab_power = st.tabs(["Readout", "Power calculator"])


@st.cache_data
def read_csv(path, mtime):
    return pd.read_csv(path)


with tab_read:
    source = st.radio("Data", ["My outbox", "Demo data (synthetic - numbers are made up)"], horizontal=True)
    demo = source.startswith("Demo")
    outbox, outcomes, oid_default, aa, exp = None, None, None, False, ""
    if demo:
        expected = st.number_input("Holdout share", 0.01, 0.99, 0.20, 0.01)
        eff = st.slider("Simulated true effect on the outcome (relative)", -0.5, 0.5, -0.2, 0.05)
        n = st.slider("Simulated customers", 500, 20000, 6000, 500)
        outbox, outcomes = ex.simulate(n=n, holdout_share=expected, rel_effect=eff)
        st.info("Demo: outcome = bad review on the customer's next order, baseline 14%.")
    else:
        up = st.file_uploader("outbox.jsonl (leave empty to use the one next to app.py)", type=["jsonl", "json", "txt"])
        if up is not None:
            outbox = ex.load_outbox(up)
        elif (ROOT / "outbox.jsonl").exists():
            outbox = ex.load_outbox(ROOT / "outbox.jsonl")
        else:
            st.warning("No outbox.jsonl yet. Dispatch something in LIVE mode first, or try the demo data.")

    if outbox is not None and len(outbox):
        if outbox.attrs.get("bad_lines"):
            st.warning(f"{outbox.attrs['bad_lines']} unreadable outbox line(s) skipped.")
        if not demo:
            outbox["experiment_label"] = ex.experiment_labels(outbox)
            exp = st.selectbox("Experiment", sorted(outbox.experiment_label.unique()))
            outbox = outbox[outbox.experiment_label == exp]
            expected = st.number_input("Holdout share configured for this experiment", 0.01, 0.99,
                                       0.50 if "order" in exp else 0.20, 0.01)
            if "mode" in outbox:
                n_dry = int((outbox["mode"].astype(str).str.upper() == "DRY-RUN").sum())
                if n_dry:
                    st.caption(f"{n_dry} DRY-RUN rows ignored: rehearsals aren't part of the experiment.")
        st.write("Rows by status:", outbox["status"].value_counts().to_dict() if "status" in outbox else "no 'status' column")

        cols = [c for c in outbox.columns if c != "experiment_label"]
        prefer = ["order_id"] + ex.ID_CANDIDATES if "order" in exp else ex.ID_CANDIDATES
        id_guess = ex.detect_column(outbox, prefer)
        id_col = st.selectbox("Randomisation unit (id column)", cols, index=cols.index(id_guess) if id_guess in cols else 0)
        a = ex.assignments(outbox, id_col, ex.detect_column(outbox, ["arm"]))
        if a.empty:
            st.warning("No LIVE assignments for this experiment yet. Dry-run rows don't count.")
        else:
            n_h, n_t = int((a.arm == "holdout").sum()), int((a.arm == "treatment").sum())
            srm = ex.srm_p(n_h, n_h + n_t, expected)
            c1, c2, c3 = st.columns(3)
            c1.metric("Treatment", f"{n_t:,}", f"{a.loc[a.arm == 'treatment', 'delivered'].mean()*100:.0f}% delivered" if n_t else None, delta_color="off")
            c2.metric("Holdout", f"{n_h:,}", f"{n_h/max(n_h+n_t,1)*100:.1f}% of assigned", delta_color="off")
            c3.metric("Sample-ratio check", "OK" if srm >= 0.001 else "MISMATCH", f"p = {srm:.3g}", delta_color="off")
            if n_h == 0:
                st.error("No LIVE holdout records, so there is nothing to compare against. "
                         "Holdout decisions logged in DRY-RUN mode don't count; dispatch the batch again in LIVE mode.")

            if n_h == 0 or n_t == 0:
                outcomes = None
            elif not demo:
                kinds = ["Upload an outcomes CSV (real follow-up data)"] + [f"A/A check with {f}" for f in HISTORICAL if (ROOT / f).exists()]
                kind = st.radio("Outcomes", kinds)
                if kind.startswith("Upload"):
                    oc = st.file_uploader("Outcomes CSV: an id column plus 0/1 outcome columns measured AFTER the dispatch", type=["csv"])
                    outcomes = pd.read_csv(oc) if oc is not None else None
                else:
                    f = kind.replace("A/A check with ", ""); aa = True
                    key, ycols = HISTORICAL[f]
                    hist = read_csv(str(ROOT / f), (ROOT / f).stat().st_mtime)
                    hist[key] = hist[key].astype(str)
                    outcomes = hist[[key] + [y for y in ycols if y in hist.columns]].dropna()
                    oid_default = key
                    st.info("A/A check: these outcomes happened BEFORE anything was sent (2016-2018 data), so the action "
                            "can't have caused them. Both arms should look alike; a clear gap means assignment is broken. "
                            "It says nothing about whether the action works.")

            if outcomes is not None:
                oc_cols = list(outcomes.columns)
                guess = oid_default or ex.detect_column(outcomes, [id_col.split(".")[-1]] + ex.ID_CANDIDATES)
                oid = st.selectbox("Id column in the outcomes", oc_cols, index=oc_cols.index(guess) if guess in oc_cols else 0)
                cands = [c for c in oc_cols if c != oid]
                ys = st.multiselect("Outcomes (first = primary, others = secondary)", cands, default=cands[:1])
                for i, y in enumerate(ys):
                    try:
                        r = ex.readout(a, outcomes, y, oid, expected_holdout=expected)
                    except ValueError as e:
                        st.error(str(e)); continue
                    st.subheader(("Primary: " if i == 0 else "Secondary: ") + y + (" (A/A check)" if aa else ""))
                    tbl = pd.DataFrame(r["arms"]).T
                    for c in ["rate", "ci_low", "ci_high", "delivered_share"]:
                        tbl[c] = (tbl[c].astype(float) * 100).round(2)
                    st.dataframe(tbl.rename(columns={"rate": "rate %", "ci_low": "CI low %", "ci_high": "CI high %", "delivered_share": "delivered %"}),
                                 use_container_width=True)
                    missing = sum(v["assigned"] - v["with_outcome"] for v in r["arms"].values())
                    if missing:
                        st.caption(f"{missing:,} assigned subjects have no outcome and are left out of this comparison.")
                    if "p_value" not in r or r["verdict"].startswith(("Too few", "STOP")):
                        st.info(r["verdict"])
                    elif aa:
                        ok = r["p_value"] >= 0.05
                        (st.success if ok else st.warning)(
                            ("Arms look alike, as they should. " if ok else "Arms differ more than chance usually allows - check assignment. ")
                            + r["verdict"])
                    else:
                        (st.success if r.get("p_value", 1) < 0.05 and "STOP" not in r["verdict"] else st.info)(r["verdict"])
                if len(ys) > 1:
                    st.caption("Judge the experiment on the primary outcome you chose before launch; secondary outcomes are context.")
            elif not demo and n_h and n_t:
                st.info("Choose an outcomes source to compare the arms.")

with tab_power:
    st.write("How many subjects do you need before a result is readable?")
    c1, c2 = st.columns(2)
    with c1:
        p0 = st.number_input("Baseline rate of the outcome in the targeted group (%)", 0.1, 90.0, 34.7, 0.1) / 100
        rc = st.slider("Smallest relative change worth detecting", -0.6, 0.6, -0.15, 0.05)
    with c2:
        hs = st.number_input("Holdout share", 0.05, 0.5, 0.50, 0.05)
        vol = st.number_input("Eligible subjects per month", 50, 1_000_000, 590, 10)
    nt, nh = ex.n_per_arm_unequal(p0, rc, hs)
    if pd.isna(nt):
        st.warning("That change takes the rate outside 0-100%.")
    else:
        st.metric("Needed", f"{nt + nh:,}", f"{nt:,} treatment + {nh:,} holdout", delta_color="off")
        st.write(f"At {vol:,} eligible a month that is about **{(nt + nh) / vol:.1f} months** of enrolment, "
                 "plus the time the outcome takes to happen.")
    st.caption("Defaults: High-band orders from your v3 run (about 590 a month, 34.7% went wrong), 50/50 split, "
               "15% relative reduction. For comparison, 180-day repeat (~1.7%) needs tens of thousands of customers.")
