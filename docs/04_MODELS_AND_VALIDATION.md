# 04 · Models and validation

How the data was prepared, how the models work, and why their numbers can be trusted.
Experiment design and the simulation are in [05](05_EXPERIMENTATION_AND_SIMULATION.md).

## 1. Data preparation (notebook `retail_growth_v1.ipynb`)

- **Source:** Online Retail II (UCI), about 1M invoice lines, Dec 2009 - Dec 2011. CSV or the original Excel file both work.
- **Cleaning:** exact duplicate rows removed; rows without a customer id dropped (they can't be followed over time);
  non-product codes (postage, manual adjustments, fees) removed; prices must be positive.
- **Grain:** one row per purchase invoice (order); cancellations/returns are separate lines (invoice starting with "C"
  or negative quantity).
- **Same-day invoices** count as one purchase occasion when measuring time between purchases (otherwise gaps of 0 days
  break ratios such as "how overdue is this customer").

## 2. Retention model (R1)

- **Question:** will a customer buy again within 90 days?
- **Design:** monthly snapshots. At each snapshot date, every customer who bought in the previous 365 days is described
  **only with history before that date**; the outcome is any purchase in the next 90 days.
- **Features:** recency, frequency (90/180/365 days and all-time), spend and trend, average order value, gaps between
  purchases and how overdue the customer is, product variety, units per line (a wholesale signal), returns in the last
  year, country, month.
- **Models:** logistic regression and gradient boosting; the better one on the out-of-time test is kept.

## 3. Order-risk model (O1)

- **Question:** will (part of) an order be returned or cancelled within 30 days?
- **Matching:** each return line is matched to the customer's most recent earlier purchase of the same product.
- **Features known when the order is placed:** size and value of the order, the customer's history (earlier orders,
  days since the last one, first order or not), and **point-in-time return rates** of the customer and of the products -
  a return only counts if it was already known when the order was placed. Rates are shrunk toward the average so a
  customer with one order isn't scored as 0% or 100%.
- **Leakage check:** the customer return rate is recomputed from scratch for 200 random orders and must match.

## 4. Validation

- **Out-of-time with a gap:** train on earlier periods whose outcome windows closed before the test period begins;
  test on later months. Random cross-validation is only used for reference, because it mixes past and future.
- **Uncertainty:** 95% intervals for AUC from a bootstrap that resamples **customers** (one customer contributes many rows).
- **Baselines:** each model must beat the best single-number rule (e.g. "orders in the last year").
- **Pre-registered criteria:** pass/fail rules were written before running each notebook.
- **Live scoring:** the app recomputes every probability from the saved model; it never reads scores from a file.

## 5. The link (L1)

Customers with a return in the last year vs none, compared **within activity groups** (quartiles of orders in the last
year), summarised with a Mantel-Haenszel risk ratio and a bootstrap interval. The app reads this per dataset and says
whether problem orders go with fewer, more, or unchanged returning customers.

## 6. Models tried and not used

| Tried | Where | Why not used |
|---|---|---|
| Survival (time-to-return) model | Olist v2.2 | No gain over a simpler model, even with 4× more training events |
| Review-text sentiment | Olist v2.2 | Correlated 0.82 with the star rating: added little |
| Gradient boosting for order risk | Olist v3, retail O1 | Lost to logistic regression on the out-of-time test |
| Transformers | Considered | Small tabular data, few sequences per customer; tested heavier models already overfitted |
| Uplift model as ranking | Simulation lab | Needs far more experiment data before it beats money-at-risk ranking |
