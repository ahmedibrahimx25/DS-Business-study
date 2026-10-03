# views/simulation.py - "what if the actions worked?" A test of the system using effects WE choose, on real 2011 orders.
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import sim
from views._shared import GREY, TEAL, current_package, kpi, money, page_header

P = current_package()
cur = P.meta.get("currency", "£")
page_header("Simulation lab", "A practice run: we pretend the actions work, then check whether the system notices")
st.warning("**This page uses made-up effects.** You choose how well each action works; the system has to find that out on its own. "
           "It tests the system - it does not show that the actions really work.")

with st.container(border=True):
    st.markdown("**Pretend that...**")
    acts = P.ui["actions"]
    defaults = {"confirm_quantities": 30, "quality_check": 20, "confirm_details": 10}
    cols = st.columns(len(acts))
    EFF = {}
    for c, (aid, a) in zip(cols, acts.items()):
        EFF[aid] = c.slider(a["label"], 0, 60, defaults.get(aid, 20), 5, format="%d%%", key=f"eff_{aid}",
                            help="Out of 100 orders that would have had a problem, how many does this action save?") / 100
    c1, c2, c3, c4 = st.columns(4)
    only_ret = c1.toggle("Only returning customers benefit", value=True,
                         help="If on, actions do nothing for a customer's first order. The system isn't told this.")
    approval = c2.slider("Team approves", 50, 100, 90, 5, format="%d%%", help="Share of suggestions the team actually acts on") / 100
    cap = c3.slider("Orders per week", 10, 100, 30, 5, help="How many orders the team can handle each week")
    seed = c4.number_input("Luck", 0, 9999, 1, help="Change it to replay with different luck.")

lr = P.last_resolved_date()
split, start = lr - pd.Timedelta(days=120), lr - pd.Timedelta(days=270)


@st.cache_data(show_spinner="Preparing orders...")
def _pool(_P, key, a, b):
    return _P.sim_pool(a, b)


@st.cache_data(show_spinner="Preparing the experiment...")
def _replay(_P, key, a, b, hp, n):
    rp = _P.replay(a, b, top_n=n, holdout_pct=hp).copy()
    rp["y0"] = rp[_P.meta["orders"]["outcome"]].astype(int)
    return rp


key = P.meta["order_model"]["version"]
pool = _pool(P, key, start, lr)
rp = _replay(P, key, split, lr, P.meta["experiment"]["holdout_pct"], cap)

# ---------------------------------------------------------------- compute everything first
eff_rp = sim.true_effects(rp, EFF, only_ret)
r, true_diff, base = sim.run_experiment(rp, eff_rp, approval, int(seed))
lo, hi = r["diff_ci"]
found = r["p_value"] < 0.05 and r["diff"] < 0
covers = lo <= true_diff <= hi
t_arm, c_arm = r["arms"]["treatment"], r["arms"]["holdout"]
sizes = [250, 500, 1000, 2000, 4000, 8000]
pc = sim.power_curve(rp["y0"].to_numpy(int), eff_rp, approval, sizes, sims=300, seed=int(seed))
enough = pc[pc.detected >= 0.8]
weekly = max(len(rp) / max(((lr - split).days / 7), 1), 1)
n80 = int(enough.orders.iloc[0]) if len(enough) else None
tr, ev = pool[pool.order_date < split], pool[pool.order_date >= split]


@st.cache_data(show_spinner="Training the uplift model...")
def _uplift(_P, key, eff_key, only, appr, sd):
    return sim.fit_uplift(tr, _P.features, _P.cat, sim.true_effects(tr, dict(eff_key), only), appr, sd)


m_t, m_c, nt, nc = _uplift(P, key, tuple(sorted(EFF.items())), only_ret, approval, int(seed))
eff_ev = sim.true_effects(ev, EFF, only_ret)
res, e = sim.compare_policies(ev, eff_ev, approval, cap, uplift=(m_t, m_c), features=P.features)
res = res.sort_values("value_protected", ascending=False)
TODAY = "Most money at risk first (Today's ranking)"
row = lambda name: res[res.policy == name].iloc[0]
weeks = ev.order_date.dt.to_period("W").nunique()
t_row, risk_row, up_row = row(TODAY), row("Riskiest orders first"), row("Learns who the action helps, x value")
max_row = res[res.policy.str.startswith("Perfect")].iloc[0]

# ---------------------------------------------------------------- summary on top
st.markdown("### Results")
if max_row.value_protected <= 0:
    st.info("With every effect at 0%, there is nothing to find or save - the experiment should say **No**. "
            + ("It does: no false alarm." if not found else "This time it said Yes by chance - a false alarm, expected about 1 time in 40."))
c = st.columns(4)
weeks_needed = (n80 / weekly) if n80 else None
kpi(c[0], "Problem rate with actions", f"{base + true_diff:.0%}", f"was {base:.0%} · {-true_diff*100:.1f} fewer per 100")
kpi(c[1], "Effect found?", "Yes" if found and covers else ("No" if not found else "Wrong"), f"measured {-r['diff']*100:.1f} fewer per 100")
kpi(c[2], "Weeks to be sure", f"{weeks_needed:.0f}" if weeks_needed else "Too long",
    f"{n80:,} orders needed" if n80 else "over 8,000 orders")
kpi(c[3], "Money saved", money(t_row.value_protected, cur), f"{t_row.share_of_best_possible:.0%} of {money(max_row.value_protected, cur)} possible")

verdict_exp = ("The test **found the effect** (clearly more than luck), and its range includes the real answer." if found and covers else
               "The test **did not find the effect** yet - with this many orders, the difference could still be luck." if not found else
               "The test found an effect, but its range **misses the real answer** - this happens about 1 time in 20.")
time_txt = (f"To find it 8 times out of 10, it needs about **{n80:,} orders, roughly {n80 / weekly:.0f} weeks** of picking {cap} orders a week."
            if n80 else "Even 8,000 orders wouldn't be enough to be sure about an effect this small.")
st.markdown(
    f"If the actions worked as you set them, the share of orders with a problem would drop from **{base:.0%}** to "
    f"**{base + true_diff:.0%}** - about **{-true_diff*100:.1f} fewer problems per 100 orders**. "
    f"That's smaller than the sliders suggest, because an action only helps orders that would have had a problem, "
    f"only {approval:.0%} of suggestions get approved"
    + (", and returning customers only." if only_ret else ".")
    + f" {verdict_exp} {time_txt}\n\n"
    f"Picking {cap} orders a week by **money at risk** (Today's ranking) would have saved **{money(t_row.value_protected, cur)}** over "
    f"{weeks} weeks - **{t_row.share_of_best_possible:.0%} of the most that could be saved**. Picking the riskiest orders first saves "
    f"{money(risk_row.value_protected, cur)}"
    + (f" (it prevents more problems - {risk_row.problems_prevented:.0f} vs {t_row.problems_prevented:.0f} - but on cheaper orders)"
       if risk_row.problems_prevented > t_row.problems_prevented else "")
    + f"; the model that learns who the action helps saves {money(up_row.value_protected, cur)}.")
st.divider()

# ---------------------------------------------------------------- 1
st.markdown("### 1. Does the test find the effect?")
st.write(f"We ran the experiment on **{len(rp):,} orders** ({split:%b}-{lr:%b %Y}, the top {cap} each week): half got the action, half didn't.")
c = st.columns(3)
kpi(c[0], "Real answer (you chose)", f"{base:.1%} → {base + true_diff:.1%}", f"{-true_diff*100:.1f} fewer per 100")
kpi(c[1], "Experiment measured", f"{c_arm['rate']:.1%} → {t_arm['rate']:.1%}", f"{-r['diff']*100:.1f} fewer · range {-hi*100:.1f} to {-lo*100:.1f}")
kpi(c[2], "Effect found?", "Yes" if found and covers else ("No" if not found else "Wrong"),
    "range includes the real answer" if found and covers else ("too few orders to be sure" if not found else "range misses the real answer"))
pts = pd.DataFrame([{"row": "Real answer", "x": -true_diff, "lo": -true_diff, "hi": -true_diff},
                    {"row": "Experiment's measurement", "x": -r["diff"], "lo": -hi, "hi": -lo}])
b = alt.Chart(pts).encode(y=alt.Y("row:N", title=None, sort=["Real answer", "Experiment's measurement"], axis=alt.Axis(labelLimit=250)))
chart = (b.mark_rule(strokeWidth=4, color=GREY).encode(x=alt.X("lo:Q", title="Fewer problems per 100 orders", axis=alt.Axis(format=".0%"),
                                                                scale=alt.Scale(domainMin=min(0, -hi) - 0.01)), x2="hi:Q")
         + b.mark_point(size=180, filled=True).encode(x="x:Q", color=alt.Color("row:N", scale=alt.Scale(range=[TEAL, "#1F2933"]), legend=None)))
st.altair_chart(chart.properties(height=110), use_container_width=True)
st.caption("The grey bar is the experiment's range: it is fairly sure the real answer lies inside it. A wide bar means: not enough orders yet.")

# ---------------------------------------------------------------- 2
st.markdown("### 2. How many orders until we can be sure?")
line = alt.Chart(pc).mark_line(point=True, color=TEAL).encode(
    x=alt.X("orders:Q", title="Orders in the experiment", scale=alt.Scale(type="log"), axis=alt.Axis(values=sizes, format=",")),
    y=alt.Y("detected:Q", title="Chance the test finds the effect", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
    tooltip=["orders", alt.Tooltip("detected:Q", format=".0%")])
rule = alt.Chart(pd.DataFrame({"y": [0.8]})).mark_rule(color=GREY, strokeDash=[4, 4]).encode(y="y:Q")
st.altair_chart((line + rule).properties(height=240), use_container_width=True)
st.write(time_txt + " Stop earlier, and whether it finds the effect is close to a coin toss.")
st.caption("We repeated the test 300 times at each size and counted how often it found the effect.")

# ---------------------------------------------------------------- 3
st.markdown("### 3. Which orders should the team pick?")
st.write(f"Each way of picking chooses {cap} orders a week over {weeks} weeks; the bars show how much money it saves.")
bar = alt.Chart(res).mark_bar().encode(
    y=alt.Y("policy:N", sort=list(res.policy), title=None, axis=alt.Axis(labelLimit=300)),
    x=alt.X("value_protected:Q", title=f"Money saved from returns and cancellations ({cur})", axis=alt.Axis(format=",.0f")),
    color=alt.condition(alt.datum.policy == TODAY, alt.value(TEAL), alt.value(GREY)),
    tooltip=["policy", alt.Tooltip("value_protected:Q", title="money saved", format=",.0f"),
             alt.Tooltip("problems_prevented:Q", title="problems prevented", format=".0f")])
st.altair_chart(bar.properties(height=270), use_container_width=True)
st.markdown(f"- **Most money at risk first** (Today's ranking) saves **{money(t_row.value_protected, cur)}** - "
            f"{t_row.share_of_best_possible:.0%} of the most that's possible.\n"
            f"- **Riskiest orders first** saves {money(risk_row.value_protected, cur)}: it ignores that a £2,000 order matters more than a £50 one.\n"
            f"- **Learns who the action helps** (the uplift model) saves {money(up_row.value_protected, cur)}. "
            + ("" if max_row.value_protected <= 0 else
               "It isn't better yet: learning who benefits needs a much bigger experiment than predicting risk."
               if up_row.value_protected < t_row.value_protected else "It beats the simple ranking with these assumptions."))
st.caption("'Perfect knowledge' knows exactly how well the action works for every order - the best anyone could do. "
           "'Random orders' is what you get without any model.")
with st.expander("Numbers"):
    st.dataframe(res.rename(columns={"policy": "way of picking", "actions": "orders picked", "problems_prevented": "problems prevented",
                                     "value_protected": f"money saved ({cur})", "per_100_actions": "problems prevented per 100 orders",
                                     "share_of_best_possible": "share of the most possible"})
                 .assign(**{"share of the most possible": lambda d: (d["share of the most possible"] * 100).round(0)}).round(1),
                 hide_index=True, use_container_width=True)

with st.expander("How the simulation works (technical)"):
    st.markdown(f"""
- Orders and their real 2011 outcomes are used as they are. Treatment orders the team acts on lose their problem with the probability
  you set (only for returning customers, if that option is on). Control orders keep their real outcome.
- **1** is the same analysis as Results (Wilson / Newcombe intervals, z-test), on the weekly top orders.
- **2** resamples orders 300 times per size with a random 50/50 split and counts significant reductions (one-sided view of a two-sided 5% test).
- **3** compares picking rules on the later months. Money saved = real outcome x assumed effect x approval rate x order value.
  The uplift model is a T-learner (two gradient-boosting models, treated vs control) trained on a simulated broad experiment in
  earlier months ({nt:,} treated / {nc:,} control orders); it never sees your assumptions. Risk scores come from the deployed model,
  which saw these months in training, so risk-based rules are slightly flattered.
""")
