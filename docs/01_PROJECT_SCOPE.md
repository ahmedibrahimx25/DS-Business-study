# 01 · Project scope

## Business context

The client scenario is a UK online retailer of gifts and homeware. It sells to consumers and, to a large extent, to
wholesale buyers who order in bulk. Orders are regularly returned in part or cancelled. Each one costs handling,
shipping, restocking and staff time, and ties up stock that could have been sold.

The operations team can intervene before dispatch - confirm quantities, check an item with a known return problem,
confirm order details - but only for a few dozen orders a week. Today those orders are chosen by gut feeling, and nobody
knows whether the checks change anything.

## Problem statement

> Help the operations team spend its limited time on the orders where it protects the most money, and prove whether
> those interventions actually reduce returns and cancellations.

## Objectives

| # | Objective | Measured by |
|---|---|---|
| O1 | Predict which orders will be returned or cancelled within 30 days | Out-of-time AUC, beating the best simple rule |
| O2 | Predict which customers will buy again within 90 days | Out-of-time AUC ≥ 0.65 and beating the best simple rule |
| O3 | Learn, from the data, whether a problem order costs the customer | Risk ratio with an interval, compared at similar activity |
| O4 | Turn predictions into a weekly work queue with suggested actions | A usable app; ranking chosen by evidence |
| O5 | Measure the effect of every action | Randomised control group, fairness checks, sample-size guidance |

The success criteria were written down **before** each model was run, so results could not be reinterpreted afterwards.

## Stakeholders

| Who | Needs |
|---|---|
| Operations / customer service | A short, ranked list each week with a clear reason and action per order |
| Management | Money at risk, and evidence that the team's effort pays off |
| Data team | Models that stay accurate, honest validation, and a way to retrain |

## Scope

**In scope**
- Data cleaning and feature engineering on historical transactions
- Order-risk and retention models, validated on later months
- The link between problem orders and customers returning
- Experiment design: randomisation, analysis, sample size, fairness checks
- A simulation lab to test the system before real use
- A web app: overview, work queue, results, model health, documentation pages
- Signed delivery of approved actions to another system (CRM, email tool, workflow tool)

**Out of scope (for this phase)**
- Connecting to live order data (the data is historical, 2009-2011)
- Running a real experiment with real customers
- Automatic retraining and the uplift model in production (prepared, not deployed)
- AI-written messages (planned next phase)

## Constraints and assumptions

- Historical data only: "today" in the app is a replay of a past date.
- Customers without an id (anonymous checkouts) can't be followed and are excluded.
- A "return" in this business is often a wholesale customer adjusting an order, not a complaint.
- Free, local-first tools; the app runs on a laptop or free Streamlit hosting.

## Deliverables

| Deliverable | Where |
|---|---|
| Analysis and modelling notebooks | `notebooks/` |
| Order-risk and retention models, scored orders | `packages/retail/` |
| Decision app (6 pages) | `app.py`, `views/` |
| Experiment and simulation engines | `experiment.py`, `sim.py` |
| Signed action delivery and test receiver | `dispatcher.py`, `mock_receiver.py` |
| Documentation | `README.md`, `docs/` |
