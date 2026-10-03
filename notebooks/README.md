# Notebooks

All notebooks run on Kaggle (free). Reviewers can read the ones **with outputs** without running anything.

## Online Retail II (current system)

| Notebook | Outputs | What it does |
|---|---|---|
| `retail_growth_v1.ipynb` | no | **Current version.** Cleans the data, builds the retention model (R1), the order-risk model (O1) and the link (L1), validates them on later months against simple rules, and exports the files `make_package.py` needs. Input: "Online Retail II UCI". |
| `retail_growth_v1_first_run_with_outputs.ipynb` | yes | The first full run, with all model results visible. Same analysis; it predates the export cells added for the app. |

## Olist discovery phase (`olist/`)

Input: "Brazilian E-Commerce Public Dataset by Olist". See [../docs/03_DELIVERY_PROCESS.md](../docs/03_DELIVERY_PROCESS.md).

| Notebook | Outputs | What it showed |
|---|---|---|
| `03_growth_pipeline_v2.ipynb` | yes | Retention scored after delivery and review: AUC 0.516, no reliable ranking |
| `04_order_risk_v3.ipynb` | yes | Order risk at purchase time: AUC 0.628 (late deliveries 0.673); bad first order → fewer returning customers |
| `05_retention_v2_1.ipynb` | no | 43 features, 180/90-day windows: AUC 0.557, a narrow pass |
| `06_retention_v2_2.ipynb` | yes | Survival model, category rates, review text: no improvement - the data's limit |

Earlier steps (`01` exploration and segmentation, `02` pipeline v1) were done in an earlier working session; add them here if you have copies.
