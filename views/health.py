# views/health.py - can we trust the system? Plain labels first, numbers in the details.
import altair as alt
import pandas as pd
import streamlit as st
from core import reliability
from views._shared import OUTBOX, current_package, historical_note
import experiment as ex

P = current_package()
om = P.meta["order_model"]
st.markdown("## System health")
historical_note(P)

st.subheader("Spotting risky orders")
lab, color = reliability(om["auc_ci"][0])
bh = P.band_history()
c1, c2 = st.columns([1, 2])
c1.metric("How well it ranks orders", lab, help=f"Tested on later orders it never saw: AUC {om['auc']:.2f} "
                                                f"(95% range {om['auc_ci'][0]:.2f}-{om['auc_ci'][1]:.2f}). 0.5 = guessing, 1.0 = perfect.")
if {"High", "Low"} <= bh.keys():
    c2.write(f"Of 100 orders it marked **High**, about **{bh['High']['rate_pct']:.0f}** had the problem; "
             f"of 100 marked **Low**, about **{bh['Low']['rate_pct']:.0f}**. (Problem = the order {om['outcome_label']}.)")
    bd = pd.DataFrame([{"band": b, "rate": bh[b]["rate_pct"] / 100, "lo": bh[b]["ci_low"] / 100, "hi": bh[b]["ci_high"] / 100}
                       for b in ("High", "Medium", "Low") if b in bh])
    base = alt.Chart(bd).encode(x=alt.X("band:N", sort=["High", "Medium", "Low"], title=None, axis=alt.Axis(labelAngle=0)))
    c2.altair_chart((base.mark_bar(size=48, color="#0F766E").encode(y=alt.Y("rate:Q", title="Actual problem rate", axis=alt.Axis(format="%")))
                     + base.mark_rule(strokeWidth=2).encode(y="lo:Q", y2="hi:Q")).properties(height=220), use_container_width=True)

cal = P.calibration_recent()
if cal:
    gap = abs(cal["predicted"] - cal["actual"]) / max(cal["actual"], 1e-9)
    msg = (f"On the latest {cal['orders']:,} finished orders ({cal['from']} to {cal['to']}) the model expected {cal['predicted']:.1%} "
           f"and the actual rate was {cal['actual']:.1%}.")
    (st.success if gap < 0.2 else st.warning)(("Still accurate. " if gap < 0.2 else "Drifting - the risk level has changed; retrain soon. ") + msg)

st.subheader("Predicting returning customers")
ret = P.meta.get("retention")
if ret:
    rl, _ = reliability(ret["auc_ci"][0])
    st.metric("How well it ranks customers", rl, help=f"AUC {ret['auc']:.2f} ({ret['auc_ci'][0]:.2f}-{ret['auc_ci'][1]:.2f})")
    st.caption(f"Predicts whether a customer {ret['outcome']}; {ret['note']}.")
else:
    st.caption("No retention model in this dataset package.")

st.subheader("Does a problem order cost us the customer?")
st.write(P.link_status()["text"])

st.subheader("Learning loop")
n_live = 0
if OUTBOX.exists():
    ob = ex.load_outbox(OUTBOX)
    if len(ob):
        ob["experiment_label"] = ex.experiment_labels(ob)
        is_live = ob["mode"].astype(str).str.upper() == "LIVE" if "mode" in ob else pd.Series(True, index=ob.index)
        n_live = int(((ob.experiment_label == P.meta["experiment"]["name"]) & is_live).sum())
st.write(f"Real decisions recorded for this dataset: **{n_live:,}**. These, plus the outcomes that follow, are what the "
         "system will learn from: which actions help, and for which orders.")

with st.expander("Details"):
    st.json({"order model": om["version"], "trained with scikit-learn": om["sklearn_version"], "features": len(om["features"]),
             "data until": P.meta["data_end"], "experiment": P.meta["experiment"], "retention model": ret})
