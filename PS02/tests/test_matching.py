from decimal import Decimal

from reconcile.matching import parse_decimal, parse_date, suggest_matches


INVOICE = {
    "invoice_id": "INV-1042",
    "customer_id": "CUST-01",
    "customer_name": "North Star Supplies",
    "reference": "INV-1042",
    "amount": Decimal("1200.00"),
    "due_date": "2026-03-31",
}


def test_exact_reference_customer_amount_and_date_match():
    payment = {
        "payment_id": "PAY-1",
        "customer_id": "CUST-01",
        "customer_name": "North Star Supplies",
        "reference": "INV-1042",
        "amount": Decimal("1200.00"),
        "payment_date": "2026-04-01",
    }
    suggestion = suggest_matches([INVOICE], [payment])[0]
    assert suggestion.band == "High"
    assert suggestion.confidence == 100
    assert not suggestion.amount_mismatch
    assert "Customer ID matches" in suggestion.evidence
    assert "reference" in suggestion.explanation.lower()


def test_fuzzy_customer_name_adds_evidence():
    invoice = {**INVOICE, "customer_id": "", "reference": "", "amount": "1.00"}
    payment = {
        "payment_id": "PAY-2",
        "customer_name": "North Star Supply Co",
        "description": "North Star Supply Co",
        "amount": "1.00",
        "payment_date": "2026-03-31",
    }
    suggestion = suggest_matches([invoice], [payment])[0]
    assert any("Customer name is similar" in evidence for evidence in suggestion.evidence)


def test_amount_mismatch_remains_visible():
    payment = {**INVOICE, "payment_id": "PAY-3", "invoice_id": "PAY-INVOICE-NAME", "amount": Decimal("900.00")}
    suggestion = suggest_matches([INVOICE], [payment])[0]
    assert suggestion.amount_mismatch
    assert "Amount mismatch" in suggestion.explanation


def test_ambiguous_when_two_plausible_candidates_exist():
    second = {**INVOICE, "invoice_id": "INV-1043", "reference": "INV-1042"}
    payment = {
        "payment_id": "PAY-4",
        "customer_id": "CUST-01",
        "customer_name": "North Star Supplies",
        "reference": "INV-1042",
        "amount": Decimal("1200.00"),
        "payment_date": "2026-04-01",
    }
    suggestions = suggest_matches([INVOICE, second], [payment])
    assert len(suggestions) == 2
    assert all(item.ambiguous for item in suggestions)


def test_low_confidence_and_no_evidence_filter():
    invoice = {"invoice_id": "INV-X", "amount": "500"}
    payment = {"payment_id": "PAY-X", "amount": "499", "description": "miscellaneous"}
    suggestions = suggest_matches([invoice], [payment], minimum_confidence=20)
    assert suggestions == []


def test_decimal_and_date_parsers():
    assert parse_decimal("$1,234.56") == Decimal("1234.56")
    assert parse_decimal("not-a-number") is None
    assert parse_date("2026-03-31") is not None
