# views/results.py - did acting help? Your experiment, or a replay of 2011 so the loop can be seen without setup.
import altair as alt
import pandas as pd
import streamlit as st
import experiment as ex
from views._shared import OUTBOX, TEAL, GREY, current_package, kpi, page_header

P = current_package()
exp = P.meta["experiment"]
y = P.meta["orders"]["outcome"]
page_header("Results", f"Did the actions help? · a problem = the order {P.meta['order_model']['outcome_label']}")

st.markdown("##### How the experiment works")
_s = st.columns(3)
_s[0].markdown("**1. Split at random**  \nEvery risky order on Today goes to the treatment or the control group, decided by chance before anyone sees it.")
_s[1].markdown("**2. Act on one half**  \nThe **treatment group** gets the suggested action. The **control group** gets nothing - like the placebo group in a medicine trial.")
_s[2].markdown("**3. Compare**  \nIf treatment orders have fewer problems than control orders, the action works. If both are the same, it doesn't.")
st.divider()


def show(assign, outcomes, hold_share, kind):
    """kind: 'aa' (historical outcomes - groups should match) or 'real'."""
    r = ex.readout(assign, outcomes, y, "order_id", expected_holdout=hold_share)
    t, h = r["arms"]["treatment"], r["arms"]["holdout"]
    if min(t["with_outcome"], h["with_outcome"]) == 0:
        lr = P.last_resolved_date()
        st.warning("These orders are too recent to have outcomes yet."
                   + (f" Decisions on orders up to {lr.date()} can be compared." if lr is not None else ""))
        return
    c = st.columns(3)
    kpi(c[0], "Treatment group", f"{t['rate']:.1%}", f"problem rate · {t['with_outcome']:,} orders got the action")
    kpi(c[1], "Control group", f"{h['rate']:.1%}", f"problem rate · {h['with_outcome']:,} orders got no action")
    kpi(c[2], "Groups balanced?", "Yes" if r["srm_p"] >= 0.001 else "No", f"{h['assigned'] / max(h['assigned'] + t['assigned'], 1):.0%} in the control group")
    df = pd.DataFrame([{"group": "Treatment", "rate": t["rate"], "lo": t["ci_low"], "hi": t["ci_high"]},
                       {"group": "Control", "rate": h["rate"], "lo": h["ci_low"], "hi": h["ci_high"]}])
    base = alt.Chart(df).encode(y=alt.Y("group:N", title=None, sort=None))
    chart = (base.mark_bar(size=26).encode(x=alt.X("rate:Q", title="Problem rate (95% interval)", axis=alt.Axis(format="%")),
                                           color=alt.Color("group:N", scale=alt.Scale(range=[TEAL, GREY]), legend=None))
             + base.mark_rule(strokeWidth=2).encode(x="lo:Q", x2="hi:Q")).properties(height=120)
    st.altair_chart(chart, use_container_width=True)
    if r.get("p_value") is None or r["verdict"].startswith(("Too few", "STOP")):
        st.info(r["verdict"])
    elif kind == "aa":
        (st.success if r["p_value"] >= 0.05 else st.warning)(
            "The two groups look alike, as they should: the outcomes happened before any action, so this shows the comparison "
            f"is fair (p = {r['p_value']:.2f}). It can't show whether actions work - that needs real outcomes."
            if r["p_value"] >= 0.05 else "The groups differ more than chance usually allows - check how orders are assigned.")
    elif r["p_value"] < 0.05:
        better = r["diff"] < 0
        (st.success if better else st.error)(
            f"Acting {'reduced' if better else 'INCREASED'} the problem rate by {abs(r['diff'])*100:.1f} points "
            f"(95% interval {r['diff_ci'][0]*100:+.1f} to {r['diff_ci'][1]*100:+.1f}).")
    else:
        st.info(f"No clear difference yet. With this many orders, only a change of about {r['mde_rel']*100:.0f}% or more could be detected.")
    p0 = P.band_history().get("High", {}).get("rate_pct", P.base_rate * 100) / 100
    need_t, need_h = ex.n_per_arm_unequal(p0, -0.15, hold_share)
    if not pd.isna(need_t):
        prog = min(1.0, t["with_outcome"] / need_t, h["with_outcome"] / need_h)
        st.progress(prog, text=f"Sample size for detecting a 15% reduction: {prog:.0%} of the ~{need_t + need_h:,} orders needed")
    with st.expander("Statistical details"):
        st.write(r["verdict"])
        st.caption("Rates with Wilson 95% intervals; difference with a Newcombe interval and a two-proportion z-test; "
                   "sample-ratio check against the configured split; analysis is intention-to-treat (skipped orders stay in the action group).")


ob = ex.load_outbox(OUTBOX) if OUTBOX.exists() else pd.DataFrame()
if len(ob):
    ob["experiment_label"] = ex.experiment_labels(ob)
    ob = ob[ob.experiment_label == exp["name"]]
live = ob[ob["mode"].astype(str).str.upper() != "DRY-RUN"] if "mode" in ob else ob
tabs = st.tabs(["Your decisions", "Example: a simulated 5-month run"])

with tabs[0]:
    if live.empty:
        st.info("No real decisions yet (practice decisions don't count). Turn on sending in the sidebar and confirm decisions on "
                "Today - or open the **Example** tab to see what Results looks like after a few months.")
    else:
        a = ex.assignments(live, "order_id", "arm")
        if len(a) < 200:
            st.caption(f"You have made {len(a)} real decisions so far. A reliable answer needs a few thousand orders, so expect "
                       "'too few to read' for now - the Example tab shows what a fuller experiment looks like.")
        hold = st.session_state.get("holdout_share", exp["holdout_pct"] / 100)
        src = st.radio("Outcomes", ["Historical outcomes (fairness check)", "Real outcomes (upload)"], horizontal=True)
        if src.startswith("Historical"):
            show(a, P.orders[P.orders.resolved][["order_id", y]], hold, "aa")
        else:
            up = st.file_uploader(f"CSV with order_id and {y} (0/1), measured after the decisions", type=["csv"])
            if up is not None:
                show(a, pd.read_csv(up, dtype={"order_id": str}), hold, "real")

with tabs[1]:
    st.info("**What this is:** Today used every week from June to October 2011 (simulated), with the top orders each week split "
            "at random into treatment and control. **Why the groups match:** these outcomes happened back in 2011, before any "
            "action - so no action could have changed them. Matching groups prove the split is fair; that is the check every real "
            "experiment depends on. Whether actions *work* can only be measured on real, current orders.")
    rp = P.replay(P.end - pd.Timedelta(days=190), P.end - pd.Timedelta(days=40), top_n=50, holdout_pct=exp["holdout_pct"])
    if rp.empty:
        st.info("Not enough finished orders for a replay.")
    else:
        a = pd.DataFrame({"subject_id": rp.order_id.astype(str), "arm": rp.arm, "delivered": rp.arm == "treatment", "n_events": 1, "arms_seen": 1})
        show(a, rp[["order_id", y]], exp["holdout_pct"] / 100, "aa")
