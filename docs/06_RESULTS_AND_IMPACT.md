# 06 · Results and business impact

All model results are on later months the model never saw, with 95% intervals. AUC measures ranking: 0.5 is guessing,
1.0 is perfect. Re-running the notebook can move numbers slightly; the app's **How it works** page shows the current ones.

## Model results

| Model | Question | AUC (95% CI) | Best simple rule | Criterion | Result |
|---|---|---|---|---|---|
| R1 retention | Buys again within 90 days? | **0.793** (0.785-0.803) | orders in the last year: 0.756 | CI ≥ 0.65 and above the rule | Pass |
| O1 order risk | Returned or cancelled within 30 days? | **0.737** (0.716-0.756) | customer's past return rate: 0.677 | CI above the rule | Pass |

| Band | R1: bought again within 90 days | O1: returned or cancelled |
|---|---|---|
| High | 92% | 41% |
| Medium | 46% | 19% |
| Low | 16% | 7% |

- R1 still reaches AUC 0.68 for customers with a single earlier purchase.
- **Calibration:** on the latest 3,849 finished orders (Sep-Nov 2011) the order-risk model expected 14.5% problems; 14.8% happened.

## The learned link

| | Bought again within 90 days |
|---|---|
| Had a return in the last year | 57.7% |
| No return | 33.1% |

Returners came back more often at every activity level. Observational: an association, not proof of cause.

## Business impact

| Lever | Evidence | Impact |
|---|---|---|
| **Focus** | High-risk orders: 41% have a problem vs 15% on average | Each check is 2.7× more likely to land on an order that would go wrong - the same team time catches far more problems than random or gut-feel checks |
| **Value-based priority** | Money-at-risk ranking: 92-97% of the maximum value protected in all simulation tests | Big orders at moderate risk are no longer missed in favour of small, very risky ones |
| **Retention targeting** | High retention band 92% vs Low 16% | Win-back and loyalty spend can skip customers who will come back anyway and focus on those who won't |
| **Right goal for this business** | Returns don't drive customers away here | Interventions are judged on margin protected, not on loyalty - avoiding a wrong business case |
| **Evidence before scaling** | Built-in control group, A/A-verified, sample-size guidance | Money is only scaled into actions proven to work; tests stop at a clear point instead of a lucky week |
| **Planning** | Model expected 14.5%, actual 14.8% | Expected returns can feed stock and staffing plans |

### Illustrative value (simulation, not a measured result)

If confirming quantities prevented 30% of problems, a quality check 20% and confirming details 10% (returning customers
only, 90% of suggestions approved), checking 30 orders a week would protect about **£54k of order value over 18 weeks**
(about £3k a week) - 92% of the most that could be protected with that effort. With stronger actions (50% each) the figure
is about £146k. Whether real actions reach these levels is exactly what the built-in experiment measures.

## Discovery phase (Olist)

| Question | Result | Learning |
|---|---|---|
| Are repeat orders real? | About 38% of "repeaters" only re-ordered within the same checkout | Always check how the data is generated before modelling |
| Will a customer buy again (180 days)? | Best AUC 0.557, even with 43 features, 4× more data, a survival model and text | 97% one-time buyers: the data can't support it |
| Will an order go wrong? | AUC 0.628; late deliveries 0.673 | Order risk was predictable even where retention wasn't |
| Does a bad first order cost the customer? | 1.68% vs 2.01% came back | Here it did - unlike the UK retailer, which is why the link is learned per business |
