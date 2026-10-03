"""Olist retention intelligence - loads the trained sklearn artifact and runs real inference.

  streamlit run app.py

Needs (same folder, or set env vars): retention_model.joblib  and optionally customers_scored.csv
Webhook: set WEBHOOK_URL + WEBHOOK_SECRET (or use the sidebar). With no URL the app is in DRY-RUN mode.
"""
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dispatcher import DEFAULT_POLICY, WebhookDispatcher, build_event, decide_frame

ART_PATH = Path(os.environ.get("RETENTION_MODEL", ROOT / "retention_model.joblib"))
CSV_PATH = Path(os.environ.get("SCORED_CSV", ROOT / "customers_scored.csv"))
OUTBOX = Path(os.environ.get("OUTBOX", ROOT / "outbox.jsonl"))
st.title("Olist retention scoring (v1/v2 model)")
st.caption("Advanced view of the original Olist retention model. For daily use, see Today.")

if not ART_PATH.exists():
    st.error(f"Model artifact not found: {ART_PATH.resolve()}. Run the notebook on Kaggle and download retention_model.joblib.")
    st.stop()


@st.cache_resource
def load_artifact(path: str, mtime: float):
    return joblib.load(path)


@st.cache_data
def load_scored(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["order_purchase_timestamp"])


art = load_artifact(str(ART_PATH), ART_PATH.stat().st_mtime)
scored_raw = load_scored(str(CSV_PATH), CSV_PATH.stat().st_mtime) if CSV_PATH.exists() else None
FEATURES = art["features"]


# ------------------------------------------------------------------ inference (real model, no heuristics)
def prepare(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURES].astype(float).copy()
    for col, (lo, hi) in art["clips"].items():
        X[col] = X[col].clip(lo, hi)
    return X


def predict(df: pd.DataFrame) -> np.ndarray:
    return art["pipeline"].predict_proba(prepare(df))[:, 1]


def to_band(p) -> np.ndarray:
    q = art["score_quantiles"]
    return np.where(p >= q["p90"], "High", np.where(p >= q["p50"], "Medium", "Low"))


def contributions(X1: pd.DataFrame) -> pd.Series:
    sc, clf = art["pipeline"].named_steps["scale"], art["pipeline"].named_steps["clf"]
    z = (prepare(X1).values[0] - sc.mean_) / sc.scale_
    return pd.Series(z * clf.coef_[0], index=FEATURES).sort_values(key=abs, ascending=False)


# ------------------------------------------------------------------ sidebar: dispatch + policy settings
url = st.session_state.get("dispatch_url", "")
secret = st.session_state.get("dispatch_secret", "")
_side = st.expander("Retention policy settings")
holdout = _side.slider("Holdout (control) %", 0, 50, DEFAULT_POLICY["holdout_pct"],
                            help="Withheld customers get no outreach, so the effect can be measured later.")
max_csat = _side.number_input("Service recovery: review score <=", 1.0, 5.0, DEFAULT_POLICY["service_recovery"]["max_csat"], 0.5)
min_transit = _side.number_input("Service recovery: transit days >", 1.0, 60.0, DEFAULT_POLICY["service_recovery"]["min_transit_days"], 1.0)
voucher = _side.number_input("Voucher amount R$ (0 = no offer)", 0.0, 500.0, 0.0, 5.0)
nurture_on = _side.checkbox("Enable nurture queue", value=False,
                                 help="Off by default: the High band showed no out-of-time support in v2 "
                                      "(High and Low bands repeated at about the same rate).")
policy = {
    "experiment": DEFAULT_POLICY["experiment"],
    "holdout_pct": holdout,
    "service_recovery": {"max_csat": max_csat, "min_transit_days": min_transit, "voucher_amount_brl": voucher or None},
    "nurture": {**DEFAULT_POLICY["nurture"], "enabled": nurture_on},
}
try:
    dispatcher = WebhookDispatcher(url=url, secret=secret, outbox=OUTBOX)
except (ValueError, RuntimeError) as e:
    _side.error(str(e))
    dispatcher = WebhookDispatcher(url=None, outbox=OUTBOX)
_side.markdown(f"**Mode: {'🔴 LIVE' if dispatcher.mode == 'LIVE' else '🟢 DRY-RUN (nothing is sent)'}**")
_side.caption(f"Model: {art['model_version']}  \nsklearn {art['sklearn_version']}")
if "-v2-" not in art["model_version"]:
    _side.warning("This is the v1 model. Replace retention_model.joblib and customers_scored.csv with the files from your v2 Kaggle run.")

st.subheader("Olist retention intelligence")
st.caption(f"Scored {art['scoring_time']}. Probabilities are 180-day repeat propensities; "
           f"the population baseline is {art['base_rate'] * 100:.2f}%.")
tab_score, tab_batch, tab_card, tab_out = st.tabs(["Score a customer", "Batch queue", "Model card", "Outbox"])

# ------------------------------------------------------------------ tab 1: single customer
with tab_score:
    modes = ["Enter values manually"] + (["Look up a scored customer"] if scored_raw is not None else [])
    mode = st.radio("Input", modes, horizontal=True)
    cust_id, order_id = "manual-entry", ""
    if mode == "Look up a scored customer":
        query = st.text_input("Customer ID (partial match)", "")
        pool = scored_raw[scored_raw.customer_unique_id.str.contains(query, regex=False)] if query else scored_raw
        pick = st.selectbox("Matches (first 50)", pool.customer_unique_id.head(50).tolist())
        row = scored_raw[scored_raw.customer_unique_id == pick].iloc[[0]]
        X1 = row.copy()
        cust_id, order_id = pick, str(row.order_id.iloc[0])
        st.caption(f"Segment: {row.final_segment.iloc[0]} · repeat type: {row.repeat_type.iloc[0]}")
    else:
        c1, c2, c3, c4 = st.columns(4)
        n_items = c1.number_input("Items in first order", 1, 10, 1)
        n_prod = c2.number_input("Distinct products", 1, 10, 1)
        items_value = c3.number_input("Items value R$", 1.0, 20000.0, 100.0)
        freight = c4.number_input("Freight R$", 0.0, 2000.0, 20.0)
        c5, c6, c7, c8 = st.columns(4)
        csat = c5.slider("Review score", 1.0, 5.0, 5.0, 1.0)
        transit = c6.number_input("Transit days", 0.0, 60.0, 12.0)
        late = c7.checkbox("Delivered after estimate")
        sp = c8.checkbox("Customer in SP")
        spend = items_value + freight
        X1 = pd.DataFrame([{
            "first_order_items": n_items, "multi_product": float(n_prod >= 2), "log_spend": np.log1p(spend),
            "freight_share": freight / spend, "first_order_csat": csat, "transit_days": transit,
            "is_delivery_late": float(late), "is_sp": float(sp),
        }])

    p = float(predict(X1)[0])
    b = str(to_band(np.array([p]))[0])
    base = art["base_rate"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Predicted 180-day repeat probability", f"{p * 100:.2f}%")
    m2.metric("Population baseline", f"{base * 100:.2f}%")
    m3.metric("Relative to baseline", f"{p / base:.2f}×")
    m4.metric("Propensity band", b, help="High = top 10% of scored customers, Medium = 50th-90th percentile, Low = bottom half.")
    band_hist = {r["band"]: r for r in art.get("metrics", {}).get("band_outcomes_oot_b", [])}
    if b in band_hist:
        h = band_hist[b]
        st.caption(f"Out-of-time, customers in the {b} band repeated at {h['repeat_rate_pct']}% "
                   f"(95% CI {h['ci_low']}-{h['ci_high']}). Compare the bands on the Model card before acting on them.")
    st.markdown("**What moves this score** (log-odds contribution vs. an average customer, from the saved model's coefficients)")
    st.bar_chart(contributions(X1))

    dec_in = X1.reset_index(drop=True).assign(customer_unique_id=cust_id, p_repeat=p, risk_band=b, order_id=order_id)
    dec = decide_frame(dec_in, policy).iloc[0]
    st.markdown("**Policy decision**")
    if dec.queue is None:
        st.info("No action: no trigger is met, or required inputs are missing. Nothing is sent by default.")
    else:
        ev = build_event(dec, policy, art["model_version"])
        st.write(f"Queue **{dec.queue}** · reasons: {', '.join(dec.reasons)} · experiment arm: **{ev['arm']}**")
        st.json(ev, expanded=False)
        if cust_id == "manual-entry":
            st.caption("Manual entries are a preview only and can't be dispatched: they aren't real customers, "
                       "and they would end up in the experiment log.")
        elif st.button("Dispatch this event"):
            st.json(dispatcher.dispatch(ev))

# ------------------------------------------------------------------ tab 2: batch queues
with tab_batch:
    if scored_raw is None:
        st.info("Place customers_scored.csv next to app.py to enable batch queues.")
    else:
        @st.cache_data
        def score_all(df: pd.DataFrame, version: str) -> pd.DataFrame:
            out = df.copy()
            out["p_repeat"] = predict(out)  # recomputed by the artifact here, not read from the CSV
            out["risk_band"] = to_band(out["p_repeat"].values)
            return out

        pool = scored_raw.dropna(subset=FEATURES)
        if "at_risk" in pool.columns:          # v2 file: customers who already came back are not at risk
            pool = pool[pool.at_risk.astype(str).str.lower().isin(["true", "1"])]
        sc = score_all(pool, art["model_version"])
        since = st.date_input("Only first orders on/after", value=sc.order_purchase_timestamp.min().date())
        sc = sc[sc.order_purchase_timestamp >= pd.Timestamp(since)]
        dd = decide_frame(sc, policy)
        summary = dd.groupby(dd.queue.fillna("no_action")).size().rename("customers").to_frame()
        summary["share_%"] = (summary.customers / max(len(dd), 1) * 100).round(2)
        st.dataframe(summary)

        queue = st.selectbox("Queue", ["service_recovery"] + (["nurture"] if nurture_on else []))
        n_max = st.slider("Max events this run", 1, 500, 25)
        sel = dd[dd.queue == queue].sort_values("p_repeat", ascending=(queue == "service_recovery")).head(n_max)
        events = [build_event(r, policy, art["model_version"]) for _, r in sel.iterrows()]
        st.write(f"{len(events)} events prepared · arms: {pd.Series([e['arm'] for e in events]).value_counts().to_dict()}")
        if events:
            st.dataframe(pd.DataFrame([{
                "customer": e["customer_unique_id"], "arm": e["arm"], "p_repeat_180d": e["data"]["p_repeat_180d"],
                "band": e["data"]["risk_band"], "reasons": "; ".join(e["data"]["reasons"]),
            } for e in events]))
            confirmed = dispatcher.mode == "DRY-RUN" or st.checkbox("I confirm sending these events to the live webhook")
            if st.button("Dispatch batch", disabled=not confirmed):
                res = dispatcher.dispatch_many(events)
                st.success(str(res.status.value_counts().to_dict()))
                st.dataframe(res)

# ------------------------------------------------------------------ tab 3: model card
with tab_card:
    mt = art["metrics"]
    st.subheader("Evidence for how far to trust this model")
    cols = st.columns(4)
    cols[0].metric("Training customers / events", f"{art['n_train']:,} / {art['n_events']:,}")
    cols[1].metric("5-fold CV ROC-AUC", f"{mt['cv_auc']:.3f}",
                   help=f"95% bootstrap CI {mt['cv_auc_ci'][0]:.3f}-{mt['cv_auc_ci'][1]:.3f}")
    cols[2].metric("Out-of-time AUC (gapped)", f"{mt['oot_b']['roc_auc']:.3f}",
                   help=f"95% CI {mt['oot_b']['roc_auc_ci'][0]:.3f}-{mt['oot_b']['roc_auc_ci'][1]:.3f}")
    cols[3].metric("Out-of-time AUC (ungapped)", f"{mt['oot_a']['roc_auc']:.3f}")
    if mt["oot_b"]["roc_auc_ci"][1] < 0.60:
        st.warning("Ranking power is weak (AUC upper bound < 0.60). Treat output as a coarse risk band, "
                   "not a precise probability, and test any action with the holdout arm.")
    for key, name in (("oot_b", "Gapped out-of-time deciles (decile 1 = highest predicted)"), ("oot_a", "Ungapped out-of-time deciles")):
        st.markdown(f"**{name}**")
        st.dataframe(pd.DataFrame(mt[key]["deciles"]))
        st.caption("Single-feature AUC baselines: " + ", ".join(f"{k} {v:.3f}" for k, v in mt[key]["baselines"].items()))
    if "band_outcomes_oot_b" in mt:
        st.markdown("**Out-of-time repeat rate by band** (if the intervals overlap, the bands don't separate customers)")
        st.dataframe(pd.DataFrame(mt["band_outcomes_oot_b"]))
    if "benchmarks" in mt:
        st.markdown("**Did anything beat this model?**")
        st.dataframe(pd.DataFrame(mt["benchmarks"]))
    if "population" in art:
        st.caption("Population: " + art["population"])
    st.markdown("**Standardised coefficients** (per 1 SD, log-odds)")
    st.bar_chart(pd.Series(art["coefficients_standardized"]))
    st.markdown("**Caveats**")
    st.markdown("\n".join(f"- {c}" for c in art["caveats"]))

# ------------------------------------------------------------------ tab 4: outbox
with tab_out:
    if OUTBOX.exists() and OUTBOX.stat().st_size:
        ob = pd.DataFrame([json.loads(line) for line in OUTBOX.read_text().splitlines() if line.strip()])
        st.write(ob.status.value_counts().to_dict())
        st.dataframe(ob.drop(columns=[c for c in ("payload",) if c in ob.columns]).tail(200))
        st.download_button("Download outbox.jsonl", OUTBOX.read_bytes(), "outbox.jsonl")
    else:
        st.info("No events logged yet.")
