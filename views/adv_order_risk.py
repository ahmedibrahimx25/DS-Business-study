# pages/3_Order_risk.py - scores orders at purchase time with order_risk_model.joblib (v3).
# Streamlit shows any file in pages/ as an extra page next to app.py; app.py itself is unchanged.
import sys, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import joblib, numpy as np, pandas as pd, sklearn
import streamlit as st
from order_features import features_from_inputs, FEATURES
from dispatcher import DEFAULT_ORDER_POLICY, WebhookDispatcher, build_order_event

_pk = ROOT / "packages" / "olist"
MODEL_PATH = _pk / "order_model.joblib" if (_pk / "order_model.joblib").exists() else ROOT / "order_risk_model.joblib"
SCORED_PATH = ROOT / "orders_scored.csv"
LABELS = {"went_wrong": "Order goes wrong (any)", "late": "Late delivery", "bad_review": "Bad review (1-2)", "canceled": "Canceled / unavailable"}
WEAK_AUC = 0.60


@st.cache_resource
def load_artifact(path, mtime):
    art = joblib.load(path)
    zc = {int(k): tuple(v) for k, v in art["lookups"]["zip_centroids"].items()}
    sellers = pd.DataFrame(art["lookups"]["seller_stats"]).set_index("seller_id")
    return art, zc, sellers


@st.cache_data
def load_scored(path, mtime):
    return pd.read_csv(path, parse_dates=["order_purchase_timestamp"], dtype={c: str for c in ["customer_state", "seller_state", "category", "payment_type"]},
                       keep_default_na=True)


st.title("Olist order risk - details (v3)")
if not MODEL_PATH.exists():
    st.error(f"`{MODEL_PATH.name}` not found next to app.py. Run `olist_order_risk_v3.ipynb` on Kaggle and download it from the Output tab.")
    st.stop()
art, ZC, SELLERS = load_artifact(str(MODEL_PATH), MODEL_PATH.stat().st_mtime)
TARGETS = list(art["targets"])
st.caption(f"Model {art['model_version']} | scored at purchase time | data ends {art['data_end'][:10]} | "
           f"trained with scikit-learn {art['sklearn_version']} (you have {sklearn.__version__})")
if art["sklearn_version"] != sklearn.__version__:
    st.warning(f"scikit-learn version differs from training. If scores look wrong: `pip install scikit-learn=={art['sklearn_version']}`")


def predict(X):
    return {t: art["targets"][t]["pipeline"].predict_proba(X[FEATURES])[:, 1] for t in TARGETS}


def band_of(t, p):
    q = art["targets"][t]["score_quantiles"]
    return "High" if p >= q["p90"] else ("Medium" if p >= q["p50"] else "Low")


def show_scores(X):
    ps = predict(X)
    cols = st.columns(len(TARGETS))
    for col, t in zip(cols, TARGETS):
        a = art["targets"][t]; p = float(ps[t][0]); b = band_of(t, p)
        hist = {r["band"]: r for r in a["band_outcomes_oot"]}[b]
        m = a["metrics"]["oot_gapped"]
        with col:
            st.metric(LABELS.get(t, t), f"{p*100:.1f}%", f"{p/a['base_rate']:.1f}x baseline ({a['base_rate']*100:.1f}%)", delta_color="off")
            st.write(f"Band: **{b}**")
            st.caption(f"Out-of-time, {b}-band orders went this way {hist['rate_pct']}% of the time "
                       f"(95% CI {hist['ci_low']}-{hist['ci_high']}). Model AUC {m['roc_auc']:.2f}.")
            if m["roc_auc_ci"][0] < WEAK_AUC:
                st.warning("Weak ranking power for this target - treat as a rough signal.")
    return ps


tab_score, tab_queue, tab_card = st.tabs(["Score an order", "Risk queue", "Model card"])

with tab_score:
    modes = ["Enter an order"] + (["Look up a scored order"] if SCORED_PATH.exists() else [])
    mode = st.radio("Input", modes, horizontal=True)
    if mode == "Enter an order":
        top = SELLERS.sort_values("seller_prior_orders", ascending=False)
        seller_opts = ["(new seller)"] + top.index.tolist()[:2000]
        c1, c2, c3 = st.columns(3)
        with c1:
            seller = st.selectbox("Seller (sorted by order count)", seller_opts, index=1 if len(seller_opts) > 1 else 0)
            if seller == "(new seller)":
                s_zip = st.number_input("Seller zip prefix (5 digits)", 1000, 99999, 14940)
                s_state = st.selectbox("Seller state", art["lookups"]["states"], index=art["lookups"]["states"].index("SP") if "SP" in art["lookups"]["states"] else 0)
                srow = {}
            else:
                srow = SELLERS.loc[seller].to_dict(); s_zip, s_state = srow.get("seller_zip"), srow.get("seller_state")
                st.caption(f"Track record at data end: {int(srow['seller_prior_orders'])} orders, "
                           f"late {srow['seller_late_k']:.0f}/{srow['seller_late_n']:.0f}, bad reviews {srow['seller_bad_k']:.0f}/{srow['seller_bad_n']:.0f}")
            c_zip = st.number_input("Customer zip prefix (5 digits)", 1000, 99999, 1310)
            c_state = st.selectbox("Customer state", art["lookups"]["states"], index=art["lookups"]["states"].index("SP") if "SP" in art["lookups"]["states"] else 0)
        with c2:
            d = st.date_input("Purchase date", dt.date.today())
            tm = st.time_input("Purchase time", dt.time(14, 0))
            promised = st.number_input("Promised delivery (days from purchase)", 1, 90, 20)
            pay_t = st.selectbox("Payment type", art["lookups"]["payment_types"])
            inst = st.number_input("Installments", 1, 24, 1)
            prior_c = st.number_input("Customer's earlier orders", 0, 50, 0)
        with c3:
            n_items = st.number_input("Items", 1, 20, 1); n_prod = st.number_input("Distinct products", 1, 20, 1)
            n_sel = st.number_input("Sellers in order", 1, 5, 1)
            price = st.number_input("Items price (R$)", 0.0, 50000.0, 120.0); freight = st.number_input("Freight (R$)", 0.0, 2000.0, 20.0)
            weight = st.number_input("Total weight (g)", 0, 100000, 800); vol = st.number_input("Total volume (litres)", 0.0, 2000.0, 10.0)
            cat = st.selectbox("Main category", art["lookups"]["categories"] + ["missing"])
        ts = pd.Timestamp(dt.datetime.combine(d, tm))
        o = dict(customer_zip=c_zip, customer_state=c_state, seller_zip=s_zip, seller_state=s_state, purchase_ts=ts,
                 estimated_delivery_date=(ts + pd.Timedelta(days=int(promised))).normalize(), n_items=n_items, n_products=n_prod,
                 n_sellers=n_sel, total_price=price, total_freight=freight, total_weight_g=weight, max_weight_g=weight,
                 total_volume_cm3=vol * 1000, category=cat, payment_type=pay_t, installments=inst, customer_prior_orders=prior_c,
                 seller_prior_orders=srow.get("seller_prior_orders", 0), seller_late_k=srow.get("seller_late_k", 0), seller_late_n=srow.get("seller_late_n", 0),
                 seller_bad_k=srow.get("seller_bad_k", 0), seller_bad_n=srow.get("seller_bad_n", 0),
                 seller_cancel_k=srow.get("seller_cancel_k", 0), seller_cancel_n=srow.get("seller_cancel_n", 0))
        X = pd.DataFrame([features_from_inputs(o, ZC, art["global_rates"])])[FEATURES]
        if np.isnan(X.distance_km.iloc[0]):
            st.info("One of the zip prefixes isn't in the geolocation table, so distance is unknown (the model imputes it).")
        st.divider()
        show_scores(X)
        with st.expander("Features sent to the model"):
            st.dataframe(X.T.rename(columns={0: "value"}))
    else:
        sc = load_scored(str(SCORED_PATH), SCORED_PATH.stat().st_mtime)
        oid = st.text_input("order_id", sc.order_id.iloc[0])
        row = sc[sc.order_id == oid]
        if row.empty:
            st.warning("order_id not found in orders_scored.csv")
        elif row[FEATURES].isna().all(axis=1).iloc[0] or row.n_items.isna().iloc[0]:
            st.warning("This order has no item rows in the data, so it can't be scored.")
        else:
            st.caption(f"Purchased {row.order_purchase_timestamp.iloc[0]} | status {row.order_status.iloc[0]} | split: {row.split.iloc[0]}")
            show_scores(row)                       # scored live by the model, never read from the CSV
            if bool(row.in_population.iloc[0]):
                st.write("What actually happened:", {LABELS[t]: ("n/a" if pd.isna(row[t].iloc[0]) else int(row[t].iloc[0])) for t in TARGETS})

with tab_queue:
    if not SCORED_PATH.exists():
        st.info("Put `orders_scored.csv` next to app.py to build queues.")
    else:
        sc = load_scored(str(SCORED_PATH), SCORED_PATH.stat().st_mtime)
        sc = sc[sc.n_items.notna()].copy()
        t = st.selectbox("Risk of", TARGETS, format_func=lambda x: LABELS.get(x, x))
        bands = st.multiselect("Bands", ["High", "Medium", "Low"], default=["High"])
        lo_d, hi_d = sc.order_purchase_timestamp.min().date(), sc.order_purchase_timestamp.max().date()
        start = st.date_input("Orders placed on/after", max(lo_d, hi_d - dt.timedelta(days=60)), min_value=lo_d, max_value=hi_d)
        q = sc[sc.order_purchase_timestamp.dt.date >= start].copy()
        q["p"] = predict(q)[t]
        q["band"] = [band_of(t, p) for p in q.p]
        q = q[q.band.isin(bands)].sort_values("p", ascending=False)
        st.write(f"{len(q):,} orders in the queue (re-scored by the model just now).")
        show = ["order_id", "customer_unique_id", "seller_id", "order_purchase_timestamp", "p", "band", "distance_km", "promised_days",
                "seller_prior_late_rate", "category"]
        st.dataframe(q[show].head(500), use_container_width=True)
        st.download_button("Download queue (CSV)", q[show].to_csv(index=False).encode(), f"order_risk_queue_{t}.csv", "text/csv")

        st.subheader("Dispatch as an experiment")
        st.caption("Each order in the queue is randomised (by order id) into treatment or holdout. Treatment orders get a "
                   "`order_risk.proactive_care.requested` event; what that triggers (delay notice, expedite, seller check) is "
                   "decided by the receiving system. Holdout orders get nothing, so the effect can be measured.")
        url = st.session_state.get("dispatch_url") or os.environ.get("WEBHOOK_URL", "")
        secret = st.session_state.get("dispatch_secret") or os.environ.get("WEBHOOK_SECRET", "")
        try:
            disp = WebhookDispatcher(url=url, secret=secret, outbox=ROOT / "outbox.jsonl")
        except (ValueError, RuntimeError) as e:
            st.error(str(e)); disp = WebhookDispatcher(url=None, outbox=ROOT / "outbox.jsonl")
        st.write(f"Mode: **{'🔴 LIVE' if disp.mode == 'LIVE' else '🟢 DRY-RUN (nothing is sent)'}** "
                 "(set the webhook URL and secret in the sidebar of the main page)")
        hold = st.slider("Holdout %", 10, 50, DEFAULT_ORDER_POLICY["holdout_pct"], 5,
                         help="50% gives the fastest readable result while testing. Changing it mid-experiment re-shuffles arms, so pick once.")
        n_max = st.slider("Max events this run", 1, 500, 25, key="order_nmax")
        pol = {**DEFAULT_ORDER_POLICY, "holdout_pct": hold, "target": t, "bands": bands}
        events = [build_order_event(r, pol, art["model_version"]) for _, r in q.head(n_max).iterrows()]
        if events:
            st.write(f"{len(events)} events prepared · arms: {pd.Series([e['arm'] for e in events]).value_counts().to_dict()}")
            ok = disp.mode == "DRY-RUN" or st.checkbox("I confirm sending these events to the live webhook", key="order_confirm")
            if st.button("Dispatch order events", disabled=not ok):
                res = disp.dispatch_many(events)
                st.success(str(res.status.value_counts().to_dict()))
                st.dataframe(res, use_container_width=True)

with tab_card:
    st.subheader("Definitions")
    st.table(pd.DataFrame({"target": list(art["definitions"]), "definition": list(art["definitions"].values())}))
    perf = []
    for t in TARGETS:
        a = art["targets"][t]; m = a["metrics"]["oot_gapped"]
        perf.append({"target": t, "deployed model": a["model_type"], "train orders": a["n_train"], "events": a["n_events"],
                     "OOT AUC": round(m["roc_auc"], 3), "AUC 95% CI": f"{m['roc_auc_ci'][0]:.3f}-{m['roc_auc_ci'][1]:.3f}",
                     "test base %": m["base_rate_test_pct"], "mean predicted %": m["mean_pred_test_pct"],
                     "top-decile lift": m["deciles"][0]["lift"], "best single feature AUC": round(max(m["single_feature_auc"].values()), 3)})
    st.subheader("Out-of-time performance (gapped)")
    st.dataframe(pd.DataFrame(perf), use_container_width=True)
    weak = [p["target"] for p in perf if float(p["AUC 95% CI"].split("-")[0]) < WEAK_AUC]
    if weak:
        st.warning(f"Weak ranking power for: {', '.join(weak)}. Use those scores as rough signals only.")
    tsel = st.selectbox("Details for", TARGETS, format_func=lambda x: LABELS.get(x, x), key="card_t")
    a = art["targets"][tsel]
    st.write("Deciles on the test period (1 = highest predicted risk):")
    st.dataframe(pd.DataFrame(a["metrics"]["oot_gapped"]["deciles"]), use_container_width=True)
    st.write("Outcome rate by band, out-of-time:")
    st.dataframe(pd.DataFrame(a["band_outcomes_oot"]), use_container_width=True)
    st.write("Logistic vs gradient boosting:")
    st.dataframe(pd.DataFrame(a["metrics"]["comparison"]), use_container_width=True)
    st.subheader("Caveats")
    for c in art["caveats"]:
        st.write("- " + c)
