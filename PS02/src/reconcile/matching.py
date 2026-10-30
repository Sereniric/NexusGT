from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from rapidfuzz import fuzz


@dataclass(frozen=True)
class MatchSuggestion:
    invoice_id: str
    payment_id: str
    confidence: int
    band: str
    explanation: str
    evidence: list[str] = field(default_factory=list)
    amount_mismatch: bool = False
    ambiguous: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def parse_decimal(value: object) -> Decimal | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def normalize(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _first(record: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _score_pair(invoice: Mapping[str, object], payment: Mapping[str, object]) -> tuple[int, list[str], bool]:
    score = 0
    evidence: list[str] = []

    invoice_reference = normalize(_first(invoice, "reference", "invoice_reference", "invoice_number"))
    payment_reference = normalize(_first(payment, "reference", "payment_reference", "description", "memo"))
    if invoice_reference and payment_reference:
        if invoice_reference == payment_reference:
            score += 35
            evidence.append("Payment reference matches the invoice reference exactly")
        elif invoice_reference in payment_reference or payment_reference in invoice_reference:
            score += 25
            evidence.append("Invoice reference appears in the payment description")

    invoice_customer_id = normalize(_first(invoice, "customer_id"))
    payment_customer_id = normalize(_first(payment, "customer_id"))
    if invoice_customer_id and payment_customer_id and invoice_customer_id == payment_customer_id:
        score += 20
        evidence.append("Customer ID matches")

    invoice_amount = parse_decimal(_first(invoice, "amount", "invoice_amount", "total"))
    payment_amount = parse_decimal(_first(payment, "amount", "payment_amount"))
    amount_mismatch = not (invoice_amount is not None and payment_amount is not None and invoice_amount == payment_amount)
    if not amount_mismatch:
        score += 30
        evidence.append("Amount matches exactly")
    else:
        evidence.append("Amount mismatch requires review")

    invoice_name = normalize(_first(invoice, "customer_name", "name"))
    payment_name = normalize(_first(payment, "customer_name", "name", "description"))
    if invoice_name and payment_name:
        name_score = fuzz.WRatio(invoice_name, payment_name)
        if name_score >= 80:
            score += round(name_score * 0.15)
            evidence.append(f"Customer name is similar ({name_score}% match)")

    invoice_date = parse_date(_first(invoice, "due_date", "date"))
    payment_date = parse_date(_first(payment, "payment_date", "date", "transaction_date"))
    if invoice_date and payment_date:
        days = abs((payment_date - invoice_date).days)
        if days <= 3:
            score += 10
            evidence.append("Payment date is within 3 days of the invoice date")
        elif days <= 30:
            score += 5
            evidence.append("Payment date is within 30 days of the invoice date")

    if not evidence:
        evidence = ["No matching evidence was found"]
    return min(score, 100), evidence, amount_mismatch


def suggest_matches(
    invoices: Iterable[Mapping[str, object]],
    payments: Iterable[Mapping[str, object]],
    minimum_confidence: int = 20,
) -> list[MatchSuggestion]:
    invoice_list = list(invoices)
    payment_list = list(payments)
    suggestions: list[MatchSuggestion] = []

    for payment in payment_list:
        payment_id = str(_first(payment, "payment_id", "id") or "")
        candidates: list[MatchSuggestion] = []
        for invoice in invoice_list:
            invoice_id = str(_first(invoice, "invoice_id", "id") or "")
            score, evidence, mismatch = _score_pair(invoice, payment)
            if score < minimum_confidence:
                continue
            band = "High" if score >= 80 else "Medium" if score >= 50 else "Low"
            candidates.append(MatchSuggestion(
                invoice_id=invoice_id,
                payment_id=payment_id,
                confidence=score,
                band=band,
                explanation="; ".join(evidence) + ".",
                evidence=evidence,
                amount_mismatch=mismatch,
            ))

        candidates.sort(key=lambda item: (-item.confidence, item.invoice_id))
        plausible = [item for item in candidates if item.confidence >= 50]
        ambiguous = len(plausible) > 1 and plausible[0].confidence - plausible[1].confidence <= 15
        if ambiguous:
            candidates = [MatchSuggestion(
                invoice_id=item.invoice_id,
                payment_id=item.payment_id,
                confidence=item.confidence,
                band=item.band,
                explanation=item.explanation,
                evidence=item.evidence,
                amount_mismatch=item.amount_mismatch,
                ambiguous=(item in plausible),
            ) for item in candidates]
        suggestions.extend(candidates)

    return suggestions


def rank_suggestions(suggestions: Sequence[MatchSuggestion]) -> list[dict]:
    return [suggestion.to_dict() for suggestion in sorted(
        suggestions,
        key=lambda item: (item.payment_id, -item.confidence, item.invoice_id),
    )]
