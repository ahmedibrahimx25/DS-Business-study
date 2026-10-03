"""Turn the files downloaded from Kaggle into a standard dataset package the app can read.

  python make_package.py retail [--src FOLDER]     needs: retail_order_risk_model.joblib, retail_orders_scored.csv, retail_link.json
                                                    optional: retail_retention_model.joblib, retail_customers_scored.csv

FOLDER is the folder holding those files; it defaults to the current folder. The package is written to packages/<name>/.
"""
import argparse, json, math, shutil, sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def rr_with_ci(k1, n1, k0, n0):
    """Risk ratio (rate if the order went wrong / rate if it went fine) with a 95% log-normal interval."""
    if min(k1, k0) == 0 or min(n1, n0) == 0:
        return None, [None, None]
    rr = (k1 / n1) / (k0 / n0)
    se = math.sqrt(1 / k1 - 1 / n1 + 1 / k0 - 1 / n0)
    return rr, [rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se)]


def need(src, name):
    p = src / name
    if not p.exists():
        sys.exit(f"Missing {p}. Download it from the Kaggle notebook's Output tab and put it in {src}.")
    return p


def build_retail(src, out):
    art = joblib.load(need(src, "retail_order_risk_model.joblib"))
    if "score_quantiles" not in art:
        sys.exit("retail_order_risk_model.joblib is from the first run. Re-run the updated retail_growth_v1 notebook on Kaggle.")
    orders = pd.read_csv(need(src, "retail_orders_scored.csv"), dtype={"customer_id": str, "invoice": str, "country_group": str}, parse_dates=["date"])
    link = json.loads(need(src, "retail_link.json").read_text())
    q = orders.rename(columns={"invoice": "order_id", "date": "order_date"})
    retention = None
    if (src / "retail_customers_scored.csv").exists():
        cs = pd.read_csv(src / "retail_customers_scored.csv", dtype={"customer_id": str}, usecols=["customer_id", "p_buy_next_90d"])
        q = q.merge(cs.rename(columns={"p_buy_next_90d": "p_return"}), on="customer_id", how="left", validate="many_to_one")
    if (src / "retail_retention_model.joblib").exists():
        r = joblib.load(src / "retail_retention_model.joblib")
        retention = {"version": r["model_version"], "auc": r["metrics"]["oot_auc"], "auc_ci": r["metrics"]["oot_auc_ci"],
                     "base_rate": r.get("base_rate"), "outcome": "buys again within 90 days", "at_order_time": True,
                     "model_type": r["metrics"].get("model"), "best_rule": r["metrics"].get("best_rule"),
                     "best_rule_auc": r["metrics"].get("best_rule_auc"), "band_outcomes": r["metrics"].get("bands_oot"),
                     "n_features": len(r["features"]),
                     "note": "scores a customer from their purchase history at any moment"}
    shutil.copy(src / "retail_order_risk_model.joblib", out / "order_model.joblib")
    q.to_csv(out / "orders.csv", index=False)
    mt = art["metrics"]
    return {
        "key": "retail", "name": "Online Retail II (UK gift & homeware)", "currency": "£",
        "data_end": str(q.order_date.max().date()),
        "order_model": {"file": "order_model.joblib", "layout": "single", "target": "returned_30d", "version": art["model_version"],
                        "features": art["features"], "cat": art["cat"], "outcome_label": "is (partly) returned or cancelled within 30 days",
                        "auc": mt["oot_auc"], "auc_ci": mt["oot_auc_ci"], "base_rate": art["base_rate"],
                        "quantiles": art["score_quantiles"], "band_outcomes": art["band_outcomes_oot"], "extra_targets": {},
                        "model_type": mt.get("model"), "rules": mt.get("rules"),
                        "sklearn_version": art["sklearn_version"]},
        "orders": {"file": "orders.csv", "outcome": "returned_30d", "value_from": "log_value",
                   "n_orders": int(len(q)), "n_customers": int(q.customer_id.nunique()),
                   "first_date": str(q.order_date.min().date())},
        "retention": retention, "link": link,
        "experiment": {"name": "retail-order-care-v1", "holdout_pct": 50},
    }


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("dataset", choices=["retail"])
    a.add_argument("--src", default=".")
    x = a.parse_args()
    src = Path(x.src)
    out = Path(__file__).resolve().parent / "packages" / x.dataset
    out.mkdir(parents=True, exist_ok=True)
    pkg = build_retail(src, out)
    (out / "package.json").write_text(json.dumps(pkg, indent=1, default=str))
    print(f"Package written to {out}  ({pkg['name']}, data until {pkg['data_end']})")
