# Project process: how the system was built

This is the story of the project in the order it happened, including the dead ends. Each step lists what was done,
what was found, and what was decided because of it. Numbers come from the notebook runs; see [RESULTS.md](RESULTS.md).

---

## Phase 1 - Understanding the Olist data

**Goal:** turn transactions into customer-level behaviour, segments and growth insights.

**Done**
- Explored the Olist Brazilian marketplace data: 99,441 orders, 96,096 real customers.
- Chose `customer_unique_id` as the customer key (`customer_id` is one per order, so it can't track repeat buying).
- Defined a "value order" (not canceled or unavailable) and built customer features: orders, time between purchases,
  items, distinct products, money spent.
- Segmented customers in two stages, so time-between-purchases was never invented for one-time buyers:
  Stage A (all customers, k-means, k=3) and Stage B (repeat customers only, k=2), giving six descriptive segments.

**Found**
- Only about 3% of customers ever ordered twice.
- The raw repeat rate depends heavily on how long a customer was observed (customers near the end of the data had no time
  to come back), so all later work uses a fixed follow-up window with an eligibility cut-off.

---

## Phase 2 - First-order analysis and the split-cart discovery

**Done**
- Tested whether anything about a customer's *first* order is associated with buying again within 180 days:
  basket size, product diversity, spend.

**Found**
- Product diversity first looked like a strong signal (repeat rate 2.9% → 5.4% → 10.5%).
- It was largely an artifact: Olist splits one checkout with several sellers into separate orders placed at the same
  moment. About 38% of "repeat customers" had only bought again within the same checkout.
- After requiring at least one day between purchases, only basket size stayed associated with repeat buying;
  spend and diversity did not.

**Decided**
- A repeat purchase must be a separate occasion (at least one day later). This rule is used everywhere afterwards.

---

## Phase 3 - Cleaning up after a second AI, first app

**Done**
- Reviewed a notebook produced with another AI tool. Its core analysis agreed with ours, but it contained invented
  evidence (a "+32% voucher effect" with no experiment behind it), a comparison against a synthetic dataset presented as
  validation, a lost segmentation, and an out-of-time test that leaked future outcomes into training.
- Rebuilt a clean pipeline: one definition of each concept, the segmentation restored, a gapped out-of-time test.
- Built the first Streamlit app and a webhook dispatcher: signed (HMAC) events, idempotency keys, retries, a dry-run mode,
  and a deterministic control group so any action could be measured.

**Found**
- The retention model ranked customers only weakly (AUC about 0.54).
- A dispatcher bug: control-group decisions made in practice mode blocked the later live run, leaving the live experiment
  with no control group. Fixed, with a test reproducing it.

---

## Phase 4 - Olist v2: an honest scoring moment

**Done**
- Re-defined the retention model to score customers when the app would really use it (after delivery and review), and
  removed customers who had already come back.

**Found**
- On a gapped out-of-time test, AUC was 0.516 - no better than chance within its uncertainty.

---

## Phase 5 - Olist v3: predicting orders that go wrong

**Done**
- Changed the question to something more frequent and actionable: will an order be late, get a bad review (1-2 stars) or
  be canceled? Scored at the moment of purchase.
- Built point-in-time seller history (only outcomes known before the order was placed) and verified it by recomputing it
  from scratch for 300 random orders.

**Found**
- AUC 0.628 overall (late deliveries 0.673), with high-risk orders going wrong 2.7 times as often as low-risk ones.
- Customers whose first order went wrong came back less often (1.68% vs 2.01%).
- The late-delivery rate rose in 2018, so absolute probabilities drifted; rankings held.

---

## Phase 6 - Trying to make retention stronger on Olist (v2.1, v2.2)

**Done**
- v2.1: 43 features instead of 8, a 90-day variant, gradient boosting; pass/fail rule fixed before running.
- v2.2: a survival (time-to-return) model using all customers' partial follow-up (about 4x more training events),
  category and product return rates, and a review-text sentiment score.

**Found**
- v2.1 passed narrowly (AUC 0.557 vs 0.522). Product category was the most informative group.
- v2.2 did not improve anything. More data and more features did not help, so the limit was the data itself:
  most Olist customers never come back.

**Decided**
- Stop tuning retention on Olist and look for data where customers do return.

---

## Phase 7 - Switching to Online Retail II

**Done**
- Chose Online Retail II (UCI): about 1M real transactions of a UK retailer, 2009-2011, with many repeat customers and
  recorded returns/cancellations - so both models and the link between them can be built on the same customers.
- Built the same three pieces: R1 retention (buy again within 90 days), O1 order risk (returned or cancelled within
  30 days), and L1, the link between the two. Success criteria fixed in advance, including beating the best simple rule.

**Found**
- R1: AUC 0.793 vs 0.756 for the best simple rule. O1: AUC 0.737 vs 0.677.
- The link went the *opposite* way to Olist: customers with a return came back more often, even at the same activity
  level. Here a return is often a wholesale customer adjusting an order, not a service failure.

**Decided**
- The link between "problem order" and "customer leaves" must be learned per business, never assumed.

---

## Phase 8 - A dataset-agnostic decision app

**Done**
- `make_package.py` turns notebook outputs into a standard package; the app works on any package.
- Simple screens: Today (what to act on), Results (did it help), System health (can we trust it).
- Olist was removed from the app once the retail data covered both models.
- Portfolio polish: Overview page, compact Today table, a replayed example experiment, a How-it-works page,
  custom theme, a public-demo mode, and a case-study README.

**Found**
- An A/A replay over June-October 2011 showed the randomised groups come out alike (43.9% vs 41.1%, p = 0.45):
  the comparison is fair.

---

## Phase 9 - Simulation lab

**Done**
- Because the data is historical, no real action could be tested. A simulation keeps the real 2011 orders and outcomes,
  but lets you *assume* how well each action works, then checks whether the system notices.
- It compares ways of choosing orders, estimates how long an experiment must run, and trains an uplift model
  (a model that learns who the action helps) on a simulated experiment.

**Found** (eight scenarios, see [RESULTS.md](RESULTS.md))
- No false alarms: with zero effect, the test found nothing.
- Choosing orders by money at risk (chance of a problem x order value) saved 92-97% of what was possible in every
  scenario; Today was switched to this ranking.
- Small effects need very long experiments; approval rate matters as much as action strength.
- The uplift model never beat the simple ranking: it needs far more experiment data.

---

## What would come next

1. Run a real experiment on current orders (the system is ready for it).
2. Once enough experiment results exist, retrain the uplift model on real outcomes.
3. Add AI-written explanations and messages (planned as the next phase), grounded only in the models' numbers.
