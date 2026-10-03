# experiment.py - treated-vs-holdout readout for the dispatcher's outbox.jsonl.
# Pure pandas + stdlib (statistics.NormalDist); no scipy/statsmodels needed.
import json, math
from statistics import NormalDist
import numpy as np
import pandas as pd

ND = NormalDist()
ID_CANDIDATES = ["customer_unique_id", "order_id", "subject_id", "entity_id", "customer_id"]
TS_CANDIDATES = ["ts", "timestamp", "created_at", "logged_at", "time"]


# ---------- statistics ----------
def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe_diff(k1, n1, k0, n0):
    """95% CI for p1 - p0 (Newcombe hybrid score method; good for small rates)."""
    p1, p0 = k1 / n1, k0 / n0
    l1, u1 = wilson(k1, n1); l0, u0 = wilson(k0, n0)
    d = p1 - p0
    return d, d - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)


def two_prop_p(k1, n1, k0, n0):
    p = (k1 + k0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    if se == 0:
        return 1.0
    z = (k1 / n1 - k0 / n0) / se
    return 2 * (1 - ND.cdf(abs(z)))


def n_per_arm(p0, rel_change, alpha=0.05, power=0.80):
    """Customers per arm to detect p0 -> p0*(1+rel_change), two-sided, normal approximation."""
    p1 = p0 * (1 + rel_change)
    if not (0 < p0 < 1 and 0 < p1 < 1) or p1 == p0:
        return float("nan")
    za, zb = ND.inv_cdf(1 - alpha / 2), ND.inv_cdf(power); pb = (p0 + p1) / 2
    return math.ceil((za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / (p1 - p0) ** 2)


def n_per_arm_unequal(p0, rel_change, holdout_share, alpha=0.05, power=0.80):
    """(n_treatment, n_holdout) when the holdout is a share of all assigned (e.g. 20%)."""
    n = n_per_arm(p0, rel_change, alpha, power)
    if math.isnan(n):
        return (float("nan"), float("nan"))
    k = (1 - holdout_share) / holdout_share          # treatment : holdout ratio
    n_hold = math.ceil(n * (1 + 1 / k) / 2)
    return (math.ceil(n_hold * k), n_hold)


def mde(p0, n_treat, n_hold, alpha=0.05, power=0.80):
    """Smallest relative change detectable with the current sample sizes (bisection)."""
    if min(n_treat, n_hold) < 2 or not 0 < p0 < 1:
        return float("nan")
    za, zb = ND.inv_cdf(1 - alpha / 2), ND.inv_cdf(power)
    def detectable(rc):
        p1 = p0 * (1 + rc)
        if not 0 < p1 < 1:
            return True
        se = math.sqrt(p0 * (1 - p0) / n_hold + p1 * (1 - p1) / n_treat)
        return abs(p1 - p0) >= (za + zb) * se
    lo, hi = 0.0, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if detectable(mid) else (mid, hi)
    return hi


def srm_p(n_hold, n_total, expected_share):
    """Sample-ratio-mismatch check: p-value that the holdout share differs from what was configured."""
    if n_total == 0:
        return float("nan")
    e = n_total * expected_share
    chi = (n_hold - e) ** 2 / e + ((n_total - n_hold) - (n_total - e)) ** 2 / (n_total - e)
    return math.erfc(math.sqrt(chi / 2))      # chi-square, 1 df


# ---------- outbox handling ----------
def load_outbox(src):
    """src: path or file-like of JSON lines. Nested payloads are flattened ('payload.customer_unique_id' etc.)."""
    if hasattr(src, "read"):
        text = src.read(); text = text.decode() if isinstance(text, bytes) else text
    else:
        with open(src, encoding="utf-8") as f:
            text = f.read()
    rows, bad = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    df = pd.json_normalize(rows) if rows else pd.DataFrame()
    df.attrs["bad_lines"] = bad
    return df


def detect_column(df, candidates):
    for c in candidates:
        if c in df.columns:                       # exact top-level column first
            return c
        hits = [col for col in df.columns if col.endswith("." + c)]
        if hits:
            return min(hits, key=len)             # least nested, e.g. payload.order_id before payload.data.order_id
    return None


def assignments(outbox, id_col, arm_col=None, status_col="status"):
    """One row per subject: arm and whether a message actually went out.
    - dry_run rows are ignored (nobody was contacted, nothing was randomised for real)
    - duplicate_skipped rows are ignored (they repeat an earlier decision)
    - treatment = assigned to treatment (sent or failed): intention-to-treat
    - first assignment per subject wins if a subject appears in several batches"""
    d = outbox.copy()
    if "mode" in d:                       # dry-run decisions are rehearsals, never part of the experiment
        d = d[d["mode"].fillna("LIVE").astype(str).str.upper() != "DRY-RUN"]
    st = d[status_col].astype(str) if status_col in d else pd.Series("", index=d.index)
    d = d[~st.isin(["dry_run", "duplicate_skipped"])].copy()
    st = d[status_col].astype(str) if status_col in d else pd.Series("", index=d.index)
    if arm_col and arm_col in d:
        arm = d[arm_col].astype(str).str.lower()
    else:
        arm = pd.Series(np.nan, index=d.index, dtype=object)
    arm = arm.where(arm.isin(["treatment", "holdout"]))
    arm = arm.fillna(st.map({"withheld_holdout": "holdout", "sent": "treatment", "failed": "treatment"}))
    d["arm"] = arm
    d["delivered"] = st.eq("sent")
    d = d[d.arm.notna() & d[id_col].notna()]
    ts = detect_column(d, TS_CANDIDATES)
    if ts:
        d = d.sort_values(ts, kind="stable")
    a = d.groupby(id_col, sort=False).agg(arm=("arm", "first"), delivered=("delivered", "max"),
                                         n_events=("arm", "size"), arms_seen=("arm", "nunique")).reset_index()
    return a.rename(columns={id_col: "subject_id"})


def readout(assign, outcomes, outcome_col, outcome_id_col, expected_holdout=0.20, alpha=0.05):
    """Compare treatment vs holdout on one binary outcome. Subjects with no outcome yet are reported, not dropped silently."""
    o = outcomes[[outcome_id_col, outcome_col]].drop_duplicates(outcome_id_col).rename(columns={outcome_id_col: "subject_id", outcome_col: "y"})
    o["subject_id"] = o.subject_id.astype(str)
    a = assign.copy(); a["subject_id"] = a.subject_id.astype(str)
    m = a.merge(o, on="subject_id", how="left", validate="one_to_one")
    m["y"] = pd.to_numeric(m.y, errors="coerce")
    bad_vals = m.y.notna() & ~m.y.isin([0, 1])
    if bad_vals.any():
        raise ValueError(f"outcome '{outcome_col}' must be 0/1; found {sorted(m.loc[bad_vals, 'y'].unique()[:5])}")
    arms = {}
    for arm in ["treatment", "holdout"]:
        s = m[m.arm == arm]; obs = s[s.y.notna()]; k, n = int(obs.y.sum()), len(obs)
        lo, hi = wilson(k, n)
        arms[arm] = dict(assigned=len(s), with_outcome=n, events=k, rate=k / n if n else float("nan"), ci_low=lo, ci_high=hi,
                         delivered_share=float(s.delivered.mean()) if len(s) else float("nan"))
    t, h = arms["treatment"], arms["holdout"]
    res = dict(arms=arms, outcome=outcome_col, n_assigned=len(m), conflicting_arms=int((m.arms_seen > 1).sum()),
               srm_p=srm_p(h["assigned"], h["assigned"] + t["assigned"], expected_holdout))
    if t["with_outcome"] and h["with_outcome"]:
        d, dl, du = newcombe_diff(t["events"], t["with_outcome"], h["events"], h["with_outcome"])
        res.update(diff=d, diff_ci=(dl, du), rel_change=(d / h["rate"]) if h["rate"] > 0 else float("nan"),
                   p_value=two_prop_p(t["events"], t["with_outcome"], h["events"], h["with_outcome"]),
                   mde_rel=mde(h["rate"], t["with_outcome"], h["with_outcome"], alpha))
    res["verdict"] = verdict(res, alpha)
    return res


def verdict(res, alpha=0.05):
    t, h = res["arms"]["treatment"], res["arms"]["holdout"]
    if min(t["with_outcome"], h["with_outcome"]) == 0:
        return "No outcomes observed yet in one of the arms - nothing to read."
    if res.get("srm_p", 1) < 0.001:
        return "STOP: the holdout share differs from the configured share (sample-ratio mismatch). Fix assignment before reading results."
    if min(t["events"], h["events"]) < 10:
        return "Too few events to read (fewer than 10 in an arm). Keep collecting."
    lo, hi = res["diff_ci"]
    mde_txt = f"the smallest change this sample can reliably detect is about {res['mde_rel']*100:.0f}% relative"
    if res["p_value"] < alpha:
        direction = "higher" if res["diff"] > 0 else "lower"
        return (f"Treatment rate is {direction} than holdout ({res['diff']*100:+.2f} pts, 95% CI {lo*100:+.2f} to {hi*100:+.2f}; p={res['p_value']:.3f}). "
                "Check the direction is the one you wanted before acting; one significant outcome out of many can be chance.")
    return (f"No detectable difference ({res['diff']*100:+.2f} pts, 95% CI {lo*100:+.2f} to {hi*100:+.2f}; p={res['p_value']:.2f}). "
            f"This is not proof of no effect: {mde_txt}.")


def experiment_labels(outbox):
    """Experiment name per row: the logged 'experiment' field, or one derived from the event type for older rows."""
    exp = outbox["experiment"] if "experiment" in outbox else pd.Series(np.nan, index=outbox.index, dtype=object)
    if "event_type" in outbox:
        fallback = outbox["event_type"].astype(str).str.split(".").str[0].map(
            {"retention": "retention-v1", "order_risk": "order-risk-v1"}).fillna("unknown")
    else:
        fallback = pd.Series("unknown", index=outbox.index)
    return exp.where(exp.notna(), fallback).astype(str)


# ---------- demo data (clearly synthetic) ----------
def simulate(n=6000, holdout_share=0.2, p0=0.14, rel_effect=-0.2, seed=1):
    """Synthetic outbox + outcomes to explore the page before a real campaign exists. Numbers are made up."""
    r = np.random.default_rng(seed)
    ids = [f"demo{i:06d}" for i in range(n)]
    hold = r.random(n) < holdout_share
    status = np.where(hold, "withheld_holdout", np.where(r.random(n) < 0.97, "sent", "failed"))
    ob = pd.DataFrame({"ts": pd.Timestamp("2026-01-01") + pd.to_timedelta(np.arange(n), unit="min"), "status": status,
                       "arm": np.where(hold, "holdout", "treatment"), "queue": "service_recovery", "customer_unique_id": ids})
    dup = ob.sample(frac=0.05, random_state=seed).assign(status="duplicate_skipped")
    p = np.where(hold, p0, p0 * (1 + rel_effect))
    y = (r.random(n) < p).astype(int)
    seen = r.random(n) < 0.95
    oc = pd.DataFrame({"customer_unique_id": ids, "bad_review_next_order": np.where(seen, y, np.nan)})
    return pd.concat([ob, dup], ignore_index=True), oc
