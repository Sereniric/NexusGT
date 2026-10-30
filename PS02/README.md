# PS02 — Invoice and Payment Reconciliation Dashboard

## Requirements

- Python 3.11 or newer
- pip

## Setup

```bash
cd PS02
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
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

## Financial storage API

`reconcile.ReconciliationStore` stores invoices, payments, match suggestions,
review decisions, and confirmed allocations in SQLite. Use `add_invoice` and
`add_payment` to import records, `save_suggestion` to persist matcher output,
and `confirm_match`, `reject_match`, or `manual_assign` to record review actions.
Only confirmed/manual allocations affect balances. Allocation amounts and
balances use `Decimal`; `AllocationError` prevents allocating beyond the
payment's remaining amount. `invoice_balances` and `payment_balances` report
balances, while `unmatched_invoices` and `unallocated_payments` expose records
needing attention. Invoice over-allocation is reported explicitly.
`undo_decision` records an auditable reversal and releases any allocation from
the target decision. The store accepts a SQLite path or `:memory:`.
