# 08 · Running and deployment

## Run locally (Windows; macOS/Linux in brackets)

Needs **Python 3.12** (scikit-learn 1.6.1, the version the models were trained with on Kaggle, has no install for 3.14).

```
py -3.12 -m venv .venv312
.venv312\Scripts\activate            (source .venv312/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501. The repository already contains the data package (`packages/retail/`), so nothing else is needed.

## Rebuild the data package (only after re-running the notebook)

1. On Kaggle: import `notebooks/retail_growth_v1.ipynb`, **Add Input** → "Online Retail II UCI", **Save Version → Save & Run All**.
2. From that version's **Output**, download the five files into the project folder:
   `retail_order_risk_model.joblib`, `retail_retention_model.joblib`, `retail_orders_scored.csv`,
   `retail_link.json`, `retail_customers_scored.csv`.
3. Run `python make_package.py retail`. It rewrites `packages/retail/`.
   Files kept in another folder: `python make_package.py retail --src "C:\path\to\folder"` (a real path, in quotes).

The five downloaded files are not needed afterwards and are excluded from git.

## Test real sending locally

Terminal 1:
```
.venv312\Scripts\activate
python mock_receiver.py --port 8099 --secret test-secret
```
In the app sidebar → **Sending settings**: URL `http://127.0.0.1:8099/hook`, secret `test-secret` (must match).
Approved actions then appear in `received.jsonl`. Webhook contract: JSON body; headers `X-Idempotency-Key`,
`X-Timestamp`, `X-Signature: sha256=HMAC(secret, "<timestamp>.<body>")`.

## Deploy (free, Streamlit Community Cloud)

1. Push the repository to GitHub (see the file list in the README; `.gitignore` already excludes the rest).
2. share.streamlit.io → **Create app** → choose the repository, branch `main`, main file `app.py`.
3. **Advanced settings:** Python 3.12; under **Secrets** add:
   ```
   PUBLIC_DEMO = "true"
   ```
   This hides the sending settings so visitors can't send anything.
4. Deploy, then put the link at the top of the README.

## Troubleshooting

| Problem | Fix |
|---|---|
| `InconsistentVersionWarning` when loading a model | Use the `.venv312` environment with `scikit-learn==1.6.1` (from requirements.txt). |
| `module 'sklearn.compose._column_transformer' has no attribute ...` | Same: the installed scikit-learn is newer than the one used for training. |
| "No dataset package yet" in the app | Run `python make_package.py retail` (see above). |
| `Missing FOLDER\...` from make_package | `FOLDER` was a placeholder: leave `--src` out, or give a real path. |
| Results says "too recent to have outcomes" | In Today's sidebar settings, pick a "today" before about 9 Nov 2011. |
| A sent event shows "sending failed" (401) | The secret in the app and in mock_receiver differ. |
