# sim.py - "what if actions worked?" Simulated outcomes on real 2011 orders, with effects WE assume.
# Purpose: test the system (does the experiment recover a known effect? how many orders does it need? which targeting
# policy prevents most problems? can an uplift model learn who benefits?) - never to claim that actions work.
import math
from statistics import NormalDist

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OrdinalEncoder

import experiment as ex
from dispatcher import assign_arm

ND = NormalDist()


def true_effects(df, action_effects, only_returning):
    """Per-order probability that the action prevents a problem that would otherwise happen (the assumption)."""
    eff = df["action"].map(action_effects).fillna(0.0).to_numpy(float)
    if only_returning and "is_first_order" in df:
        eff = eff * (df["is_first_order"].to_numpy(float) == 0)
    return eff


def simulate_outcomes(y0, eff, treated, approval, rng):
    """Treated orders that are actually acted on lose their problem with probability eff; everyone else keeps the real outcome."""
    acted = treated & (rng.random(len(y0)) < approval)
    prevented = acted & (rng.random(len(y0)) < eff)
    return np.where(prevented, 0, y0).astype(int), acted


# ---------------------------------------------------------------- 1. does the experiment recover the effect?
def run_experiment(pool, eff, approval, seed):
    rng = np.random.default_rng(seed)
    treated = (pool["arm"] == "treatment").to_numpy()
    y0 = pool["y0"].to_numpy(int)
    y, acted = simulate_outcomes(y0, eff, treated, approval, rng)
    assign = pd.DataFrame({"subject_id": pool["order_id"].astype(str).to_numpy(), "arm": pool["arm"].to_numpy(),
                           "delivered": acted, "n_events": 1, "arms_seen": 1})
    outcomes = pd.DataFrame({"order_id": pool["order_id"].astype(str).to_numpy(), "y": y})
    r = ex.readout(assign, outcomes, "y", "order_id", expected_holdout=float((~treated).mean()))
    true_diff = -float(np.mean(y0 * eff * approval))           # expected treatment-minus-control difference (intention-to-treat)
    return r, true_diff, float(y0.mean())


# ---------------------------------------------------------------- 2. how many orders does it take?
def power_curve(y0, eff, approval, sizes, sims=300, seed=0):
    """Share of simulated experiments (50/50 split) that detect a reduction at p < 0.05, for each total sample size."""
    rng = np.random.default_rng(seed)
    out = []
    for n in sizes:
        idx = rng.integers(0, len(y0), (sims, n))
        arm = rng.random((sims, n)) < 0.5
        acted = arm & (rng.random((sims, n)) < approval)
        y = np.where(acted & (rng.random((sims, n)) < eff[idx]), 0, y0[idx])
        nt, nc = arm.sum(1), (~arm).sum(1)
        pt, pc = (y * arm).sum(1) / np.maximum(nt, 1), (y * ~arm).sum(1) / np.maximum(nc, 1)
        pp = (y.sum(1)) / n
        se = np.sqrt(np.maximum(pp * (1 - pp), 1e-12) * (1 / np.maximum(nt, 1) + 1 / np.maximum(nc, 1)))
        z = (pt - pc) / se
        detected = (z < -ND.inv_cdf(0.975))
        out.append({"orders": n, "detected": float(detected.mean())})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 3. which orders should we act on?
def fit_uplift(train, features, cat, eff, approval, seed):
    """T-learner: one model for treated orders, one for control; predicted benefit = P(problem | control) - P(problem | treated)."""
    rng = np.random.default_rng(seed)
    treated = np.array([assign_arm(str(o), "sim-uplift", 50) == "treatment" for o in train["order_id"]])
    y, _ = simulate_outcomes(train["y0"].to_numpy(int), eff, treated, approval, rng)
    num = [f for f in features if f not in cat]

    def model():
        pre = ColumnTransformer([("num", "passthrough", num)] + ([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cat)] if cat else []))
        from sklearn.pipeline import Pipeline
        return Pipeline([("pre", pre), ("clf", HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                                              min_samples_leaf=100, l2_regularization=1.0,
                                                                              categorical_features=list(range(len(num), len(num) + len(cat))) or None,
                                                                              random_state=seed))])
    m_t = model().fit(train.loc[treated, features], y[treated])
    m_c = model().fit(train.loc[~treated, features], y[~treated])
    return m_t, m_c, int(treated.sum()), int((~treated).sum())


def compare_policies(evalset, eff, approval, capacity, uplift=None, features=None):
    """Each week, act on `capacity` orders chosen by a policy. Expected problems / value prevented, using the real
    2011 outcome of each order and the assumed effect (no randomness: expectations)."""
    e = evalset.copy()
    e["benefit"] = e["y0"].to_numpy(float) * eff * approval              # expected problems prevented if acted on
    e["benefit_value"] = e["benefit"] * e["value"].fillna(0).to_numpy(float)
    scores = {"Most money at risk first (Today's ranking)": e["p"] * e["value"].fillna(0), "Riskiest orders first": e["p"],
              "Biggest orders first": e["value"].fillna(0)}
    if uplift is not None:
        m_t, m_c = uplift
        pred = m_c.predict_proba(e[features])[:, 1] - m_t.predict_proba(e[features])[:, 1]
        e["pred_uplift"] = pred
        scores["Learns who the action helps (uplift model)"] = pd.Series(pred, index=e.index)
        scores["Learns who the action helps, x value"] = pd.Series(pred, index=e.index) * e["value"].fillna(0)
    # ceiling: a policy that knows the TRUE assumed effect per order (but not the future outcome) - risk x effect x value
    scores["Perfect knowledge (best possible)"] = e["p"] * pd.Series(eff, index=e.index) * e["value"].fillna(0)
    e["week"] = e["order_date"].dt.to_period("W")
    rows = []
    for name, s in scores.items():
        e["_s"] = s.to_numpy()
        top = e.sort_values("_s", ascending=False).groupby("week", sort=False).head(capacity)
        rows.append({"policy": name, "actions": len(top), "problems_prevented": float(top.benefit.sum()),
                     "value_protected": float(top.benefit_value.sum())})
    # random targeting: exact expectation per week
    wk = e.groupby("week").agg(n=("benefit", "size"), b=("benefit", "mean"), bv=("benefit_value", "mean"))
    k = np.minimum(wk.n, capacity)
    rows.append({"policy": "Random orders", "actions": int(k.sum()), "problems_prevented": float((k * wk.b).sum()),
                 "value_protected": float((k * wk.bv).sum())})
    res = pd.DataFrame(rows)
    res["per_100_actions"] = 100 * res.problems_prevented / res.actions.clip(lower=1)
    oracle = res.loc[res.policy.str.startswith("Perfect knowledge"), "value_protected"].iloc[0]
    res["share_of_best_possible"] = res.value_protected / max(oracle, 1e-9)
    return res, e
