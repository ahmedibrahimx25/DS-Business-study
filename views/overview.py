# views/overview.py - the 30-second view: what is at risk this week, can we trust the models, is the experiment running.
import altair as alt
import pandas as pd
import streamlit as st
import experiment as ex
from core import reliability
from views._shared import OUTBOX, TEAL, GREY, current_package, kpi, money, page_header

P = current_package()
om, ret = P.meta["order_model"], P.meta.get("retention")
cur = P.meta.get("currency", "£")
w = P.week()
page_header("Overview", f"{P.meta['name']} · demo replay of historical data · week to {w['today']:%d %b %Y}")

st.markdown(f"This week **{w['high']} of {w['orders']} orders** ({w['high_share']:.0%}) are at high risk of a return or cancellation. "
            f"They are worth **{money(w['value_high'], cur)}**, and without action about **{w['expected_problems_high']:.0f}** "
            f"of them are expected to have a problem.")

c = st.columns(4)
kpi(c[0], "High-risk orders this week", f"{w['high']}", f"of {w['orders']} orders placed")
kpi(c[1], "Value of high-risk orders", money(w["value_high"], cur), f"{money(w['expected_value_at_risk'], cur)} expected to be affected")
lab, _ = reliability(om["auc_ci"][0])
kpi(c[2], "Order-risk model", lab, f"AUC {om['auc']:.2f} on unseen months", help="Out-of-time test: trained on earlier months, scored on later ones.")
if ret:
    rl, _ = reliability(ret["auc_ci"][0])
    kpi(c[3], "Returning-customer model", rl, f"AUC {ret['auc']:.2f} on unseen months")

st.markdown("#### Does the model's risk match what actually happened?")
tl = P.timeline()
if len(tl):
    long = tl.melt(id_vars=["order_date", "orders"], value_vars=["predicted", "actual"], var_name="series", value_name="rate")
    long["series"] = long.series.map({"predicted": "Model expected", "actual": "Actually happened"})
    chart = alt.Chart(long).mark_line(point=True).encode(
        x=alt.X("order_date:T", title=None),
        y=alt.Y("rate:Q", title="Problem rate", axis=alt.Axis(format="%")),
        color=alt.Color("series:N", scale=alt.Scale(domain=["Model expected", "Actually happened"], range=[TEAL, GREY]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("order_date:T", title="Week"), "series", alt.Tooltip("rate:Q", format=".1%"), "orders"],
    ).properties(height=260)
    st.altair_chart(chart, use_container_width=True)
    st.caption("Weekly rate of returned or cancelled orders, on orders whose 30-day outcome is known. "
               "Includes the months the model was trained on; the honest test uses only later months (see How it works).")

st.markdown("#### Experiment")
n_live = 0
if OUTBOX.exists():
    ob = ex.load_outbox(OUTBOX)
    if len(ob):
        ob["experiment_label"] = ex.experiment_labels(ob)
        live = (ob.experiment_label == P.meta["experiment"]["name"])
        if "mode" in ob:
            live &= ob["mode"].astype(str).str.upper() == "LIVE"
        n_live = int(live.sum())
st.write(f"Real decisions recorded: **{n_live:,}**. Every decision on Today is part of a randomised experiment: half the flagged "
         "orders go to a control group that gets no action, so Results can measure whether acting actually helps.")

c = st.columns(3)
c[0].page_link("views/today.py", label="Review today's orders", icon="📋")
c[1].page_link("views/results.py", label="See results", icon="📈")
c[2].page_link("views/methodology.py", label="How it works", icon="🧭")
