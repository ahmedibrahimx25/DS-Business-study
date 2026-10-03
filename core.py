# core.py - everything the simple screens need, without any Streamlit code (so it can be tested on its own).
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from datasets_ui import ui_for
from dispatcher import assign_arm

ROOT = Path(__file__).resolve().parent
PKG_DIR = ROOT / "packages"
OPS = {">=": np.greater_equal, "<=": np.less_equal, "==": np.equal, ">": np.greater, "<": np.less}


def available_packages():
    if not PKG_DIR.exists():
        return []
    return sorted(p.name for p in PKG_DIR.iterdir() if (p / "package.json").exists())


def reliability(ci_low):
    """Plain-language label for an out-of-time AUC interval's lower end."""
    if ci_low is None:
        return "Unknown", "grey"
    if ci_low >= 0.75:
        return "Strong", "green"
    if ci_low >= 0.65:
        return "Good", "green"
    if ci_low >= 0.58:
        return "Fair", "orange"
    if ci_low > 0.5:
        return "Weak", "orange"
    return "Not useful", "red"


class Package:
    def __init__(self, key):
        self.key = key
        self.dir = PKG_DIR / key
        self.meta = json.loads((self.dir / "package.json").read_text())
        om = self.meta["order_model"]
        art = joblib.load(self.dir / om["file"])
        self.art = art
        if om["layout"] == "multi_target":
            self.pipes = {t: art["targets"][t]["pipeline"] for t in [om["target"]] + list(om.get("extra_targets", {}))}
        else:
            self.pipes = {om["target"]: art["pipeline"]}
        self.target, self.features, self.cat = om["target"], om["features"], om["cat"]
        self.ui = ui_for(key)
        self.orders = pd.read_csv(self.dir / self.meta["orders"]["file"], dtype={**{c: str for c in self.cat}, "order_id": str, "customer_id": str},
                                  keep_default_na=False, na_values=[""], parse_dates=["order_date"])
        self.orders["resolved"] = self.orders.resolved.astype(str).str.lower().isin(["true", "1"])
        self.end = self.orders.order_date.max()
        vf = self.meta["orders"].get("value_from")
        self.orders["value"] = np.expm1(self.orders[vf]) if vf and vf in self.orders else np.nan
        self._scored = None

    # ---------------------------------------------------------------- scoring (always live from the model)
    def score(self, df, target=None):
        return self.pipes[target or self.target].predict_proba(df[self.features])[:, 1]

    def band(self, p):
        q = self.meta["order_model"]["quantiles"]
        return np.where(p >= q["p90"], "High", np.where(p >= q["p50"], "Medium", "Low"))

    @property
    def base_rate(self):
        return self.meta["order_model"]["base_rate"]

    def band_history(self):
        rows = self.meta["order_model"]["band_outcomes"]
        return {r["band"]: r for r in rows}

    # ---------------------------------------------------------------- explanation and suggestion
    def explain(self, row):
        """First matching reason (text, action_id), or (None, default action)."""
        for feat, op, val, text, action in self.ui["reasons"]:
            v = row.get(feat)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            try:
                if OPS[op](float(v), val):
                    return text.format(v=float(v)), action
            except (TypeError, ValueError):
                continue
        return None, self.ui["default_action"]

    def message(self, action_id, row, p, reason):
        a = self.ui["actions"][action_id]
        reason = reason if isinstance(reason, str) and reason else "of several smaller factors"
        return a["template"].format(order_id=row["order_id"], p=p, base=self.base_rate, reason=reason)

    # ---------------------------------------------------------------- the learned link (order problem -> coming back)
    def link_status(self):
        lk = self.meta.get("link")
        if not lk or lk.get("rr") is None:
            return {"kind": "missing", "text": "Not measured for this dataset yet."}
        lo, hi = lk["rr_ci"]
        w, f = lk["rate_wrong"], lk["rate_fine"]
        if hi < 1:
            kind = "lower"
            text = (f"Customers who had a problem come back less often: {w:.1%} vs {f:.1%} ({lk['outcome']}). "
                    "Preventing problems may protect repeat business - the experiment will tell.")
        elif lo > 1:
            kind = "higher"
            text = (f"Here, customers who had a problem actually come back MORE often ({w:.1%} vs {f:.1%}), even at similar activity. "
                    "Acting on risky orders is about the order itself, not about keeping the customer.")
        else:
            kind = "unclear"
            text = f"No clear evidence that a problem changes whether customers come back ({w:.1%} vs {f:.1%})."
        return {"kind": kind, "text": text, "rr": lk["rr"], "ci": [lo, hi], **lk}

    def impact_per_100(self, p, p_return=None):
        """Expected customers lost per 100 orders like this one, only when the link shows a real drop."""
        st_ = self.link_status()
        if st_["kind"] != "lower":
            return None
        base = p_return if p_return is not None and not pd.isna(p_return) else st_["rate_fine"]
        return 100 * p * base * (1 - st_["rr"])

    # ---------------------------------------------------------------- today's queue
    def queue(self, days=7, top_n=20, holdout_pct=None, min_band=None, today=None, rank="value_at_risk"):
        """Orders to look at. rank='value_at_risk' (default): chance of a problem x order value - the Simulation lab showed it
        protects more value than ranking by risk alone. rank='risk': highest chance of a problem first (High band only)."""
        exp = self.meta["experiment"]
        hp = exp["holdout_pct"] if holdout_pct is None else holdout_pct
        today = self.end if today is None else pd.Timestamp(today) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        o = self.orders
        recent = o[(o.order_date > today - pd.Timedelta(days=days)) & (o.order_date <= today)].copy()
        if recent.empty:
            return recent
        recent["p"] = self.score(recent)
        recent["band"] = self.band(recent.p.values)
        recent["value_at_risk"] = recent.p * recent.value.fillna(0) if recent.value.notna().any() else recent.p
        min_band = min_band or ("High" if rank == "risk" else "Low")
        keep = {"High": ["High"], "Medium": ["High", "Medium"]}.get(min_band, ["High", "Medium", "Low"])
        key = "p" if rank == "risk" else "value_at_risk"
        q = recent[recent.band.isin(keep)].sort_values(key, ascending=False).head(top_n).copy()
        rs = [self.explain(r) for r in q.to_dict("records")]
        q["reason"], q["action"] = [r[0] for r in rs], [r[1] for r in rs]
        q["arm"] = [assign_arm(str(o), exp["name"], hp) for o in q.order_id]
        q["impact_per_100"] = [self.impact_per_100(p, r) for p, r in zip(q.p, q.get("p_return", pd.Series([None] * len(q), index=q.index)))]
        return q

    # ---------------------------------------------------------------- health checks
    def last_resolved_date(self):
        r = self.orders[self.orders.resolved]
        return r.order_date.max() if len(r) else None

    def calibration_recent(self, days=60):
        """Mean predicted vs actual on the most recent resolved orders."""
        res = self.orders[self.orders.resolved & self.orders[self.meta["orders"]["outcome"]].notna()]
        if res.empty:
            return None
        last = res[res.order_date >= res.order_date.max() - pd.Timedelta(days=days)]
        p = self.score(last)
        actual = last[self.meta["orders"]["outcome"]].astype(float).mean()
        return {"orders": len(last), "predicted": float(p.mean()), "actual": float(actual),
                "from": str(last.order_date.min().date()), "to": str(last.order_date.max().date())}


    # ---------------------------------------------------------------- portfolio views
    def scored_orders(self):
        """All orders scored once by the live model (cached on the object)."""
        if self._scored is None:
            o = self.orders.copy()
            o["p"] = self.score(o)
            o["band"] = self.band(o.p.values)
            self._scored = o
        return self._scored

    def week(self, today=None, days=7):
        today = self.end if today is None else pd.Timestamp(today) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        o = self.scored_orders()
        w = o[(o.order_date > today - pd.Timedelta(days=days)) & (o.order_date <= today)]
        hi = w[w.band == "High"]
        return {"orders": len(w), "high": len(hi), "high_share": len(hi) / max(len(w), 1),
                "value_high": float(hi.value.sum()), "expected_problems_high": float(hi.p.sum()),
                "expected_value_at_risk": float((hi.value * hi.p).sum()), "today": today}

    def timeline(self, freq="W"):
        """Predicted vs actual problem rate per period, on finished orders (a calibration check over time)."""
        o = self.scored_orders()
        y = self.meta["orders"]["outcome"]
        r = o[o.resolved & o[y].notna()]
        g = r.groupby(pd.Grouper(key="order_date", freq=freq)).agg(orders=(y, "size"), actual=(y, "mean"), predicted=("p", "mean")).reset_index()
        return g[g.orders >= 30]

    def replay(self, start, end, every_days=7, days=7, top_n=50, holdout_pct=None):
        """What the experiment would look like if Today had been used every week between start and end.
        Uses historical outcomes, so actions can't have changed them: both groups should look alike (an A/A check)."""
        key = (str(start), str(end), every_days, days, top_n, holdout_pct)
        if getattr(self, "_replays", None) is None:
            self._replays = {}
        if key in self._replays:
            return self._replays[key]
        rows = []
        for d in pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq=f"{every_days}D"):
            q = self.queue(days=days, top_n=top_n, holdout_pct=holdout_pct, today=d)
            if len(q):
                rows.append(q.assign(decided_on=d))
        if not rows:
            return pd.DataFrame()
        r = pd.concat(rows).drop_duplicates("order_id")
        y = self.meta["orders"]["outcome"]
        self._replays[key] = r[r.resolved & r[y].notna()]
        return self._replays[key]

    def sim_pool(self, start, end):
        """Finished orders in [start, end] with live score, band, reason, suggested action, real outcome (y0) and value."""
        o = self.scored_orders()
        y = self.meta["orders"]["outcome"]
        d = o[o.resolved & o[y].notna() & (o.order_date >= pd.Timestamp(start)) & (o.order_date <= pd.Timestamp(end))].copy()
        rs = [self.explain(r) for r in d.to_dict("records")]
        d["reason"], d["action"] = [r[0] for r in rs], [r[1] for r in rs]
        d["y0"] = d[y].astype(int)
        return d
