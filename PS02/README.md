# PS02 — Invoice and Payment Reconciliation Dashboard

## Requirements

- Python 3.11 or newer
- pip

## Setup

```bash
cd PS02
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

## Run the dashboard

```bash
streamlit run app.py
```

## Run tests

```bash
pytest
```

## Structure

- `src/reconcile/` — reconciliation models, validation, matching, and storage logic
- `tests/` — unit and integration tests
- `data/samples/` — labeled demonstration CSV files
- `app.py` — Streamlit entry point
