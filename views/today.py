# views/today.py - the work queue: high-risk orders in one table, approve or untick, confirm once.
import json

import numpy as np
import pandas as pd
import streamlit as st
from dispatcher import build_care_event
from views._shared import OUTBOX, current_package, dispatcher, kpi, money, page_header, plain_status

P = current_package()
D = dispatcher()
exp = P.meta["experiment"]
cur = P.meta.get("currency", "£")

with st.sidebar.expander("Today settings"):
    lr = P.last_resolved_date()
    today = st.date_input("Treat this date as today", value=P.end.date(), min_value=P.orders.order_date.min().date(),
                          max_value=P.end.date(), help="Replay an earlier day. Orders up to "
                          f"{lr.date() if lr is not None else '-'} have known outcomes, which Results can compare.")
    days = st.slider("Orders from the last ... days", 1, 30, 7)
    top_n = st.slider("Show at most", 5, 100, 30)
    holdout = st.slider("Control group size (%)", 10, 50, exp["holdout_pct"], 5,
                        help="Keep this fixed for the whole experiment; changing it reshuffles some orders between groups.")
    if D.mode == "DRY-RUN" and st.button("Clear practice decisions", help="Removes practice decisions so you can practise again. Real ones are kept."):
        if OUTBOX.exists():
            keep = [l for l in OUTBOX.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not (json.loads(l).get("mode") == "DRY-RUN" and json.loads(l).get("experiment") == exp["name"])]
            OUTBOX.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        st.rerun()
st.session_state["holdout_share"] = holdout / 100

page_header("Today", f"Orders where the most money is at risk (chance of a problem x order value) · week to {pd.Timestamp(today):%d %b %Y} · "
            + ("🔴 live: approved actions are sent" if D.mode == "LIVE" else "🟢 practice mode: nothing is sent"))

q = P.queue(days=days, top_n=top_n, holdout_pct=holdout, today=today)
if q.empty:
    st.success(f"No high-risk orders in the {days} days to {pd.Timestamp(today):%d %b %Y}.")
    st.stop()
q["reason"] = [x if isinstance(x, str) and x else "several smaller factors" for x in q.reason]


def statuses():
    out = {}
    if OUTBOX.exists():
        for line in OUTBOX.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("mode", "LIVE") == D.mode or r.get("status") == "sent":
                out[r["event_id"]] = r["status"]
    return out


done = statuses()
version = P.meta["order_model"]["version"]
q["event"] = [build_care_event(r["order_id"], r["customer_id"], exp["name"], holdout, version, r["action"],
                               {"action": r["action"], "action_label": P.ui["actions"][r["action"]]["label"], "p_risk": round(float(r["p"]), 4),
                                "band": r["band"], "reason": r["reason"], "risk_of": P.meta["order_model"]["outcome_label"], "dataset": P.key})
              for r in q.to_dict("records")]
q["status"] = [done.get(e["event_id"]) for e in q.event]
open_t = q[q.status.isna() & (q.arm == "treatment")]
open_h = q[q.status.isna() & (q.arm == "holdout")]
handled = q[q.status.notna()]

c = st.columns(4)
kpi(c[0], "Orders to look at", f"{len(q)}", f"chance of a problem {q.p.min():.0%}-{q.p.max():.0%} (usual {P.base_rate:.0%})")
kpi(c[1], "Money at risk", money(q.value_at_risk.sum(), cur) if q.value.notna().any() else "-",
    f"of {money(q.value.sum(), cur)} total order value" if q.value.notna().any() else None,
    help="For each order: chance of a problem x order value, added up.")
kpi(c[2], "To decide", f"{len(open_t)}", "suggested actions")
kpi(c[3], "Control group", f"{len(q[q.arm == 'holdout'])}", "no action, picked at random",
    help="Like the placebo group in a medicine trial: these orders get no action, so Results can compare them with the ones that do.")

if len(open_t):
    st.markdown("#### Suggested actions")
    table = pd.DataFrame({
        "Approve": True,
        "Order": open_t.order_id.values,
        "Placed": pd.to_datetime(open_t.order_date).dt.strftime("%d %b").values,
        "Risk": (open_t.p * 100).round(0).values,
        "Value": open_t.value.round(0).values,
        "At risk": open_t.value_at_risk.round(0).values,
        "Main reason": open_t.reason.values,
        "Suggested action": [P.ui["actions"][a]["label"] for a in open_t.action],
    })
    edited = st.data_editor(
        table, hide_index=True, use_container_width=True, key=f"editor_{today}_{days}_{top_n}_{holdout}",
        disabled=[c for c in table.columns if c != "Approve"],
        column_config={
            "Approve": st.column_config.CheckboxColumn("Approve", help="Untick to skip this one"),
            "Risk": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d%%"),
            "Value": st.column_config.NumberColumn(f"Value ({cur})", format="%d"),
            "At risk": st.column_config.NumberColumn(f"At risk ({cur})", format="%d", help="Chance of a problem x order value. The list is sorted by this."),
            "Main reason": st.column_config.TextColumn("Main reason", width="large"),
        })
    approved_ids = set(edited.loc[edited.Approve, "Order"])
    n_skip = len(edited) - len(approved_ids)
    why = st.selectbox("Reason for the ones you unticked", ["Not needed", "Already handled elsewhere", "Suggestion doesn't fit", "Other"]) if n_skip else ""

    with st.expander("Preview the messages"):
        for r in open_t[open_t.order_id.isin(approved_ids)].head(10).to_dict("records"):
            a = P.ui["actions"][r["action"]]
            st.markdown(f"**Order {r['order_id']}** → {a['audience']}")
            st.caption(P.message(r["action"], r, r["p"], r["reason"]))
        if len(approved_ids) > 10:
            st.caption(f"... and {len(approved_ids) - 10} more.")

if len(open_h):
    with st.expander(f"{len(open_h)} orders in the control group (no action)"):
        st.caption("Picked at random before you see them. Comparing them with the orders that get an action is the only way "
                   "to know whether actions help - like the placebo group in a medicine trial.")
        st.dataframe(pd.DataFrame({"Order": open_h.order_id, "Risk": (open_h.p * 100).round(0), "Main reason": open_h.reason}),
                     hide_index=True, use_container_width=True,
                     column_config={"Risk": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d%%")})
if len(handled):
    with st.expander(f"{len(handled)} already handled"):
        st.dataframe(pd.DataFrame({"Order": handled.order_id, "Risk": (handled.p * 100).round(0),
                                   "Outcome of decision": [plain_status(s) for s in handled.status]}),
                     hide_index=True, use_container_width=True,
                     column_config={"Risk": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d%%")})

if len(open_t) + len(open_h) == 0:
    st.success("Everything here has been handled.")
    st.stop()

st.divider()
n_app = len(approved_ids) if len(open_t) else 0
n_sk = (len(open_t) - n_app) if len(open_t) else 0
ok_live = D.mode == "DRY-RUN" or st.checkbox("I confirm these actions will really be sent")
if st.button(f"Confirm: {n_app} actions · {n_sk} skipped · {len(open_h)} in the control group", type="primary", disabled=not ok_live):
    res = []
    for r in open_t.to_dict("records"):
        ev = r["event"]
        if r["order_id"] in approved_ids:
            ev["data"]["message"] = P.message(r["action"], r, r["p"], r["reason"])
            res.append(D.dispatch(ev))
        else:
            res.append(D.record_skip(ev, why))
    res += [D.dispatch(e) for e in open_h.event]
    counts = pd.Series([x["status"] for x in res]).value_counts().to_dict()
    st.success("Done: " + ", ".join(f"{v} {plain_status(k)}" for k, v in counts.items())
               + (" (practice mode - nothing was sent)" if D.mode == "DRY-RUN" else ""))
