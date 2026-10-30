# InvoiceMatch — Transparent Invoice & Payment Reconciliation

*Project description and working roles for a four-developer, 24-hour prototype.*

## Description

InvoiceMatch is a reconciliation dashboard for small businesses that keep invoices and payments in separate spreadsheets. It imports both as CSV files, validates them, and suggests which payments belong to which invoices. Each suggestion comes with a confidence indicator and a plain-language explanation (e.g., "Invoice reference INV-1042 found in payment description; amount matches exactly; paid 3 days after due date").

Nothing is auto-finalized. Users confirm, reject, or manually reassign matches, and ambiguous cases and amount mismatches stay visible until resolved. Outstanding balances are computed only from confirmed allocations, using `Decimal` arithmetic. A payment cannot be allocated beyond its remaining amount, so it is never counted twice. The app ends with an exportable reconciliation report covering decisions, explanations, and unresolved records.

**Stack:** Python, pandas, Decimal, RapidFuzz, SQLite, Streamlit, pytest.

**Core workflow:** Import → Validate → Suggest matches → Review (confirm / reject / assign) → Balances → Export report.

**Extensions (if time permits):** partial-payment aggregation, duplicate detection, fuzzy matching of unclear descriptions.

## Team Roles

### Dev 1: Data Pipeline & Validation Lead

**Owns:** CSV ingestion, cleaning, and the labeled dataset.

- Build CSV importers for invoices and payments (pandas), with schema checks.
- Normalize fields: dates, customer names, reference formats, amounts (parse to `Decimal`).
- Flag invalid or incomplete records (missing amounts, bad dates, absent references) with reasons.
- **Create the labeled sample dataset** with ground-truth matches covering: clean matches, ambiguous cases, amount mismatches, unmatched records, repeated amounts, and double-count traps.
- Write tests for validation and normalization.

**Hands off to:** a clean, validated set of records for Dev 2, and the ground-truth file used by Dev 4 for precision metrics.

### Dev 2: Matching Engine Lead

**Owns:** Match suggestions, scoring, and explanations.

- Implement rule-based evidence scoring: invoice reference, customer ID, amount, date proximity.
- Add RapidFuzz name/description matching for inconsistent customer names.
- Generate a confidence score and band (High / Medium / Low) per suggestion.
- Produce a human-readable explanation for every suggestion, listing each piece of evidence.
- Flag ambiguity (multiple plausible candidates) and amount mismatches rather than picking silently.
- Extensions: partial-payment aggregation and duplicate detection.
- Write pytest tests for each matching rule.

**Hands off to:** a ranked suggestion list with explanations for Dev 3 and Dev 4.

### Dev 3: Financial Logic & Database Lead

**Owns:** Storage, allocations, and balance integrity.

- Design the SQLite schema: invoices, payments, suggestions, allocations, review decisions (with timestamps).
- Implement the allocation ledger: confirmed allocations only drive balances.
- Enforce the safeguard that total allocations per payment cannot exceed the payment amount (no double counting), and surface over-allocation to an invoice.
- Calculate paid amount, outstanding balance, unallocated payments, and unmatched invoices with `Decimal`.
- Persist user decisions (confirm, reject, manual assignment) so corrections survive reloads; support undo.
- Write pytest tests for balance calculations and duplicate prevention.

**Hands off to:** a clean data-access and balance API for Dev 4.

### Dev 4: Dashboard, Reporting & Evaluation Lead

**Owns:** Streamlit UI, export, metrics, and the demo.

- Build the Streamlit app: upload page, validation results, suggestions view with confidence and explanation, confirm/reject/manual-assign controls.
- Build views for unmatched invoices, unallocated payments, review-needed cases, and balances.
- Implement the reconciliation report export (CSV/Excel): decisions, explanations, unresolved records.
- Compute and display evaluation metrics against the labeled dataset: matching precision, share of records with correct suggestions, number of unresolved cases.
- Own integration, README, and the final demo script showing correct matches, ambiguity, unmatched records, and the double-count safeguard.

## Suggested 24-Hour Timeline

| Hours | Focus |
| --- | --- |
| 0–2 | Agree on data schemas and function interfaces; Dev 1 drafts the dataset; Dev 3 drafts the DB schema |
| 2–8 | Parallel build: importer, matching engine, DB and ledger, UI skeleton (using mock data) |
| 8–14 | Integrate end to end; first full run from import to report |
| 14–19 | Review flow, edge cases, extensions (partial payments, duplicates, fuzzy) |
| 19–22 | Metrics on the labeled set, bug fixes, test pass |
| 22–24 | README, demo rehearsal, final report export |

## Shared Responsibilities

- **Interface contract first:** agree on record fields (`invoice_id`, `customer_id`, `customer_name`, `amount`, `date`, `reference`, etc.) in hour 1 so everyone can work in parallel.
- **Everyone** writes pytest tests for their own module.
- **Everyone** helps on demo day; Dev 4 leads the walkthrough.
