# 09 · Limitations and roadmap

## Limitations

| Limitation | Effect | How it is handled |
|---|---|---|
| Historical data (2009-2011) | "Today" is a replay; no real action can be tested | A/A replay proves fairness; the simulation lab proves the test can find effects; both are labelled clearly |
| Simulated effects are assumptions | Simulated money saved is illustrative, not a result | Shown with a warning on every simulation screen |
| Meaning of a "return" | Many are wholesale adjustments, not complaints | The link is learned per business; actions are framed around margin, not loyalty |
| Observational link | "Returners come back more" is an association | Only the experiment can establish cause and effect |
| Test window | Out-of-time tests cover mid-2011 | The pre-Christmas peak, the hardest period, is only partly covered |
| Retention model at order time | Uses the customer's score as of the end of the data | Live use would refresh scores daily |
| Customers without an id | Excluded | Can't be followed over time in any case |

## Roadmap

| Phase | What | Why |
|---|---|---|
| **Next: AI explanations** | AI-written reasons and messages per order, using only the models' numbers; the team still approves | Clearer communication without invented facts |
| **Live data** | Daily feed of new orders, outcomes collected after 30 days | Turns the system from a demo into an operation |
| **Real experiment** | Run until the "weeks to be sure" from the simulation lab | First measured effect of each action |
| **Learning loop** | Retrain monthly; replace a model only if it beats the current one on later data; track drift | Keeps the models accurate as the business changes |
| **Uplift model in production** | Once real experiment data is large enough | Target the orders the action actually helps, not just risky ones |
| **Automated tests and CI** | Unit tests for leakage checks, statistics and delivery | Safer changes as the system grows |
