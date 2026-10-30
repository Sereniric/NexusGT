from decimal import Decimal

import pytest

from reconcile import AllocationError, ReconciliationStore


def store_with_records():
    store = ReconciliationStore()
    store.add_invoice({"invoice_id": "INV-1", "amount": "100.00"})
    store.add_invoice({"invoice_id": "INV-2", "amount": "70.00"})
    store.add_payment({"payment_id": "PAY-1", "amount": "120.00"})
    return store


def test_suggestions_do_not_change_balances_and_records_round_trip():
    store = store_with_records()
    store.save_suggestion({
        "invoice_id": "INV-1", "payment_id": "PAY-1", "confidence": 95,
        "band": "High", "explanation": "Reference and amount match.",
        "evidence": ["reference", "amount"],
    })
    assert store.invoice_balances()[0].paid_amount == Decimal(0)
    assert store.payment_balances()[0].unallocated_amount == Decimal("120.00")
    assert store.list_suggestions()[0]["evidence"] == ["reference", "amount"]
    assert store.list_invoices()[0]["amount"] == Decimal("100.00")
    assert store.list_payments()[0]["amount"] == Decimal("120.00")


def test_confirm_and_manual_partial_allocations_use_decimal_balances():
    store = store_with_records()
    store.confirm_match("INV-1", "PAY-1", "45.10")
    store.manual_assign("INV-2", "PAY-1", "30.20", note="Reviewed")
    invoices = {row.invoice_id: row for row in store.invoice_balances()}
    assert invoices["INV-1"].outstanding_balance == Decimal("54.90")
    assert invoices["INV-2"].paid_amount == Decimal("30.20")
    assert store.payment_balances()[0].unallocated_amount == Decimal("44.70")


def test_allocation_cannot_exceed_payment_remaining_amount():
    store = store_with_records()
    store.confirm_match("INV-1", "PAY-1", "100")
    with pytest.raises(AllocationError, match="exceeds payment"):
        store.manual_assign("INV-2", "PAY-1", "20.01")
    assert store.payment_balances()[0].allocated_amount == Decimal("100")


def test_invoice_overallocation_is_reported():
    store = store_with_records()
    store.confirm_match("INV-1", "PAY-1", "120")
    balance = store.invoice_balances()[0]
    assert balance.outstanding_balance == Decimal(0)
    assert balance.overallocated_amount == Decimal("20.00")


def test_rejection_persists_without_affecting_balance():
    store = store_with_records()
    decision_id = store.reject_match("INV-1", "PAY-1", note="Wrong reference")
    decision = store.list_decisions()[0]
    assert decision["decision_id"] == decision_id
    assert decision["action"] == "reject"
    assert store.invoice_balances()[0].paid_amount == Decimal(0)


def test_undo_confirmation_releases_allocation_and_is_auditable():
    store = store_with_records()
    confirmation_id = store.confirm_match("INV-1", "PAY-1", "100")
    store.undo_decision(confirmation_id, note="Correction")
    assert store.invoice_balances()[0].paid_amount == Decimal(0)
    assert store.payment_balances()[0].unallocated_amount == Decimal("120.00")
    assert [row["action"] for row in store.list_decisions()] == ["confirm", "undo"]
    with pytest.raises(ValueError, match="already been undone"):
        store.undo_decision(confirmation_id)


def test_unmatched_and_unallocated_records():
    store = store_with_records()
    store.confirm_match("INV-1", "PAY-1", "120")
    assert [row.invoice_id for row in store.unmatched_invoices()] == ["INV-2"]
    assert store.unallocated_payments() == []


def test_database_records_and_decisions_survive_reopening(tmp_path):
    database = tmp_path / "ledger.sqlite"
    first = ReconciliationStore(database)
    first.add_invoice({"invoice_id": "INV-1", "amount": "100"})
    first.add_payment({"payment_id": "PAY-1", "amount": "75"})
    first.confirm_match("INV-1", "PAY-1")
    first.close()
    reopened = ReconciliationStore(database)
    assert reopened.invoice_balances()[0].paid_amount == Decimal("75")
    assert reopened.payment_balances()[0].unallocated_amount == Decimal(0)
    assert reopened.list_decisions()[0]["action"] == "confirm"
    reopened.close()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "bad"])
def test_invalid_amount_is_rejected(value):
    store = ReconciliationStore()
    with pytest.raises(ValueError):
        store.add_invoice({"invoice_id": "INV-1", "amount": value})


def test_duplicate_ids_and_unknown_records_are_rejected():
    store = store_with_records()
    with pytest.raises(ValueError, match="already exists"):
        store.add_invoice({"invoice_id": "INV-1", "amount": "10"})
    with pytest.raises(ValueError, match="does not exist"):
        store.confirm_match("INV-1", "missing", "1")
