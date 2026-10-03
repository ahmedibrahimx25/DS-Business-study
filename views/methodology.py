# views/methodology.py - for the technical reader: how the system is built and why its numbers can be trusted.
import altair as alt
import pandas as pd
import streamlit as st
import experiment as ex
from views._shared import GREY, TEAL, current_package, kpi, page_header

P = current_package()
om, ret, lk, od = P.meta["order_model"], P.meta.get("retention"), P.meta.get("link"), P.meta["orders"]
page_header("How it works", "Design, validation and evidence behind the numbers in this app")

st.markdown(
    f"A decision-support system for an online retailer: it **flags orders likely to be returned or cancelled**, suggests an action, "
    f"and **measures with a randomised control group** whether acting helps. Built on "
    f"{od.get('n_orders', len(P.orders)):,} real orders from {od.get('n_customers', P.orders.customer_id.nunique()):,} customers "
    f"({od.get('first_date', '')[:7]} to {P.meta['data_end'][:7]}, Online Retail II, UCI).")

st.graphviz_chart("""
digraph {
  rankdir=LR; bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#F3F6F8", color="#CBD5E1", fontname="Helvetica", fontsize=11];
  edge [color="#94A3B8"];
  raw [label="1M transaction lines"]; clean [label="Cleaning & grain\\n1 row per order /\\ncustomer-snapshot"];
  feat [label="Point-in-time\\nfeatures"]; o1 [label="Order-risk model\\n(return/cancel in 30d)", fillcolor="#CCFBF1"];
  r1 [label="Retention model\\n(buys again in 90d)", fillcolor="#CCFBF1"]; link [label="Learned link\\nproblem → retention?"];
  today [label="Today: prioritise\\n& suggest action"]; rand [label="Random split\\ntreatment / control 50:50"];
  send [label="Signed webhook\\n(idempotent)"]; res [label="Results:\\nA/B readout"]; loop [label="Learning loop\\n(next phase)", style="rounded,dashed"];
  raw -> clean -> feat; feat -> o1; feat -> r1; o1 -> link; r1 -> link; o1 -> today; link -> today;
  today -> rand -> send -> res; res -> loop [style=dashed]; loop -> o1 [style=dashed];
}""")

st.markdown("### Models")
st.caption("Both are tested on later months they never saw, and must beat the best simple rule - otherwise the rule would be the better tool.")
rows = [{"Model": "Order risk", "Question": f"Will the order be {om['outcome_label'].replace('is ', '')}?", "Type": om.get("model_type", "-"),
         "Features": len(om["features"]), "AUC on unseen months": f"{om['auc']:.3f} ({om['auc_ci'][0]:.3f}-{om['auc_ci'][1]:.3f})",
         "Best simple rule": (lambda r: f"{max(r, key=r.get)}: {max(r.values()):.3f}")(om["rules"]) if om.get("rules") else "-"}]
if ret:
    rows.append({"Model": "Returning customers", "Question": f"Will the customer {ret['outcome'].replace('buys', 'buy')}?",
                 "Type": ret.get("model_type", "-"), "Features": ret.get("n_features", "-"),
                 "AUC on unseen months": f"{ret['auc']:.3f} ({ret['auc_ci'][0]:.3f}-{ret['auc_ci'][1]:.3f})",
                 "Best simple rule": f"{ret.get('best_rule')}: {ret['best_rule_auc']:.3f}" if ret.get("best_rule_auc") else "-"})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def band_chart(rows_, title):
    d = pd.DataFrame([{"band": r["band"], "rate": r["rate_pct"] / 100, "lo": r["ci_low"] / 100, "hi": r["ci_high"] / 100} for r in rows_])
    b = alt.Chart(d).encode(x=alt.X("band:N", sort=["High", "Medium", "Low"], title=None, axis=alt.Axis(labelAngle=0)))
    return (b.mark_bar(size=40, color=TEAL).encode(y=alt.Y("rate:Q", title=title, axis=alt.Axis(format="%")))
            + b.mark_rule(strokeWidth=2).encode(y="lo:Q", y2="hi:Q")).properties(height=200)


c = st.columns(2)
with c[0]:
    st.markdown("**Order risk: what happened to each risk band** (unseen months, 95% intervals)")
    st.altair_chart(band_chart(om["band_outcomes"], "Returned/cancelled"), use_container_width=True)
if ret and ret.get("band_outcomes"):
    with c[1]:
        st.markdown("**Returning customers: what happened to each band**")
        st.altair_chart(band_chart(ret["band_outcomes"], "Bought again in 90 days"), use_container_width=True)

st.markdown("### Why the numbers can be trusted")
st.markdown("""
- **Time-based validation with a gap.** Models are trained on earlier months and tested on later ones; training outcomes must be fully known before the test period starts, so nothing from the future leaks in.
- **Point-in-time features.** A customer's or product's return history only counts returns that were known when the order was placed. A built-in check recomputes this from scratch for 200 random orders.
- **Honest uncertainty.** Every AUC comes with a 95% interval from a bootstrap that resamples *customers*, because one customer contributes many rows.
- **Success criteria fixed before running**, and every model is compared with the simplest rule that could replace it.
- **Live scoring.** The app recomputes every probability from the saved model; it never reads scores from a file.
""")

if lk and lk.get("strata"):
    st.markdown("### Does a problem order cost us the customer?")
    s = pd.DataFrame(lk["strata"])
    s["activity"] = ["Least active", "Less active", "More active", "Most active"][:len(s)]
    long = pd.concat([s.assign(group="Had a return", rate=s.rate_wrong), s.assign(group="No return", rate=s.rate_fine)])
    chart = alt.Chart(long).mark_bar().encode(
        x=alt.X("activity:N", sort=list(s.activity), title="Customers grouped by orders in the last year", axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("group:N", sort=["Had a return", "No return"]),
        y=alt.Y("rate:Q", title="Bought again within 90 days", axis=alt.Axis(format="%")),
        color=alt.Color("group:N", scale=alt.Scale(domain=["Had a return", "No return"], range=[TEAL, GREY]), legend=alt.Legend(title=None, orient="top")),
    ).properties(height=240)
    st.altair_chart(chart, use_container_width=True)
    st.caption(f"Compared within activity groups (Mantel-Haenszel risk ratio {lk['rr']:.2f}, 95% interval {lk['rr_ci'][0]:.2f}-{lk['rr_ci'][1]:.2f}). "
               + P.link_status()["text"] + " Observational: this is an association, not an effect.")

st.markdown("### Experiment design")
p0 = P.band_history().get("High", {}).get("rate_pct", 40) / 100
nt, nh = ex.n_per_arm_unequal(p0, -0.15, P.meta["experiment"]["holdout_pct"] / 100)
st.markdown(f"""
- **Randomised by order:** a hash of the order id assigns each flagged order to *treatment* (action) or *control* (no action) ({P.meta['experiment']['holdout_pct']}%), before anyone sees it - so reviewers can't bias the groups, and reruns agree.
- **Intention-to-treat:** orders a reviewer skips stay in the action group, so the result reflects what happens when the team *tries* to act.
- **Checks:** sample-ratio mismatch test on the split; Wilson intervals per group; Newcombe interval and two-proportion z-test for the difference.
- **Sample size:** detecting a 15% reduction from the High-band rate ({p0:.0%}) needs about **{nt + nh:,} orders** at 80% power.
- **Safe delivery:** events are HMAC-signed, carry an idempotency key, retry on server errors, and are never sent twice; practice mode logs without sending.
""")

with st.expander("What came before: the Olist phase (why the project switched datasets)"):
    st.markdown("""
The project started on the Olist Brazilian marketplace dataset (99k orders). The same methods produced these honest results:

| Question | Best result on unseen data | Verdict |
|---|---|---|
| Will a customer buy again (180 days)? | AUC 0.557 (v2.1, 43 features) | Weak - about 97% of customers buy once |
| ... with 4x more training data (survival model) and text features | No improvement (0.533-0.550) | The limit was the data, not the model |
| Will an order go wrong (late, bad review, canceled)? | AUC 0.628; late delivery alone 0.673 | Useful |

Along the way: about 38% of apparent repeat purchases were one checkout split into several orders (a marketplace artifact), and a
first order that went wrong was associated with fewer returning customers (1.68% vs 2.01%). Because retention could not be predicted
on Olist, the system moved to Online Retail II, where customers do come back - and the dataset-agnostic design made that a data swap, not a rewrite.
""")

with st.expander("Limitations"):
    st.markdown("""
- **Historical data (2009-2011).** "Today" is a replay; no real action was taken, so the demo can show the experiment is fair, not that actions work.
- **What a "return" means here.** Many returns are wholesale customers adjusting orders, not service failures - which is why returners come back *more*.
- **Observational link.** The problem-to-retention relationship is an association; only the experiment can show cause and effect.
- **Test window.** The out-of-time tests cover mid-2011; the pre-Christmas peak is the hardest period and is only partly covered.
""")

st.caption("Stack: Python · pandas · scikit-learn (logistic regression, gradient boosting) · Streamlit · Altair · HMAC-signed webhooks · notebooks run on Kaggle.")
