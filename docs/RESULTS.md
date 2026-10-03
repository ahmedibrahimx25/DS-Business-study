# Results

All AUCs are out-of-time (trained on earlier months, tested on later months the model never saw) with 95% intervals.
AUC: 0.5 = guessing, 1.0 = perfect ranking. Re-running the notebooks can move numbers slightly; the app's
**How it works** page always shows the current ones.

## Online Retail II (the data the app runs on)

### Models

| Model | Question | AUC (95% CI) | Best simple rule | Passed? |
|---|---|---|---|---|
| R1 retention | Will the customer buy again within 90 days? | **0.793** (0.785-0.803) | orders in the last year: 0.756 | Yes |
| O1 order risk | Will the order be returned or cancelled within 30 days? | **0.737** (0.716-0.756) | customer's past return rate: 0.677 | Yes |

Success criteria were fixed before running: R1 needed an interval starting at 0.65 or more *and* above the best simple rule;
O1 needed an interval above the best simple rule.

**What happened in each band (later months):**

| Band | R1: bought again within 90 days | O1: returned or cancelled |
|---|---|---|
| High | 92% | 41% |
| Medium | 46% | 19% |
| Low | 16% | 7% |

R1 still reaches AUC 0.68 for customers with only one earlier purchase.

### The link: does a problem order cost the customer?

| | Bought again within 90 days |
|---|---|
| Had a return in the last year | 57.7% |
| No return | 33.1% |

Returners came back **more** often at every activity level (e.g. 78% vs 72% among the most active).
Observational: an association, not an effect.

### Health and fairness checks

- **Calibration:** on the latest 3,849 finished orders (Sep-Nov 2011) the model expected 14.5% problems; 14.8% happened.
- **A/A replay** (Jun-Oct 2011, outcomes that happened before any action): treatment 43.9% vs control 41.1%,
  p = 0.45 - the groups come out alike, as they should.

## Simulation lab tests

Effects are assumptions, so these results describe the system, not whether real actions work.
Settings for test A: action effects 30% / 20% / 10%, only returning customers benefit, 90% approved, 30 orders a week, luck 1.
Every other test changes one thing.

| Test | What changed | Problem rate | Effect found? | Weeks to be sure | Money saved (money-at-risk ranking) | Riskiest first | Uplift model |
|---|---|---|---|---|---|---|---|
| A | start | 35% → 28% | Yes | 63 | £54.4k (92%) | £55.0k | £43.0k |
| B | effects 50/50/50 | 35% → 20% | Yes | 16 | £146.0k (97%) | £121.5k | £138.8k |
| C | effects 10/10/10 | 35% → 32% | No | too long | £29.2k (97%) | £24.3k | £20.9k |
| D | everyone benefits | 35% → 28% | Yes | 63 | £56.0k (94%) | £55.5k | £43.5k |
| E | 50% approved | 35% → 31% | No | 254 | £30.2k (92%) | £30.6k | £22.7k |
| F | 80 orders a week | 30% → 24% | Yes | 48 | £75.6k (94%) | £74.8k | £58.7k |
| G | no effect at all | 35% → 35% | **No** (correct) | too long | £0 | £0 | £0 |
| H | luck 2, 3, 4 | 35% → 28% | No, No, No | 63 | £54.4k | £55.0k | £39-43k |

**Takeaways**
1. No false alarm (G), and when an effect exists the measurement lands close to it.
2. Strong actions are found in months; weak ones may never be.
3. Approval rate matters as much as action strength (E).
4. More orders per week shortens the test (F).
5. One quick "Yes" can be luck (A vs H): run tests for the full time needed.
6. Ranking by money at risk saved 92-97% of the maximum in every test - it became Today's ranking.
7. The uplift model needs far more data before it is worth using.

## Olist phase (earlier dataset)

| Step | Question | Result |
|---|---|---|
| Base facts | | 99,441 orders, 96,096 customers, about 3% ever ordered twice |
| Split-cart check | Are repeats real? | About 38% of 180-day "repeaters" only re-ordered within the same checkout |
| v1 | Buy again within 180 days (from first order) | AUC about 0.54 |
| v2 | Same, scored after delivery and review | AUC 0.516 (0.490-0.544): no reliable ranking |
| v3 | Order goes wrong (late, bad review, canceled) | AUC 0.628 (0.620-0.636); late deliveries 0.673 |
| v3 link | First order went wrong → bought again? | 1.68% vs 2.01% |
| v2.1 | 43 features, gradient boosting | AUC 0.557 (0.530-0.585) vs 0.522 baseline - passed narrowly |
| v2.2 | Survival model (4x more data), category rates, review text | 0.500-0.550: no improvement |

Conclusion: order risk was predictable on Olist; retention was not, because almost all customers buy once.
