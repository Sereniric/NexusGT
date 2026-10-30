"""SQLite persistence and Decimal-based financial allocation ledger."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Iterator, Mapping


class AllocationError(ValueError):
    """Raised when an allocation exceeds a payment's remaining amount."""


@dataclass(frozen=True)
class InvoiceBalance:
    invoice_id: str
    invoice_amount: Decimal
    paid_amount: Decimal
    outstanding_balance: Decimal
    overallocated_amount: Decimal


@dataclass(frozen=True)
class PaymentBalance:
    payment_id: str
    payment_amount: Decimal
    allocated_amount: Decimal
    unallocated_amount: Decimal


class ReconciliationStore:
    """Store imported records, suggestions, decisions, and confirmed allocations."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(database), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._lock = RLock()
        self._closed = False
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL DEFAULT '',
                customer_name TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                amount TEXT NOT NULL,
                due_date TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL DEFAULT '',
                customer_name TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                amount TEXT NOT NULL,
                payment_date TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS suggestions (
                invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
                payment_id TEXT NOT NULL REFERENCES payments(payment_id),
                confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
                band TEXT NOT NULL,
                explanation TEXT NOT NULL,
                evidence TEXT NOT NULL,
                amount_mismatch INTEGER NOT NULL CHECK (amount_mismatch IN (0, 1)),
                ambiguous INTEGER NOT NULL CHECK (ambiguous IN (0, 1)),
                PRIMARY KEY (invoice_id, payment_id)
            );
            CREATE TABLE IF NOT EXISTS review_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL CHECK (action IN ('confirm', 'reject', 'manual_assign', 'undo')),
                invoice_id TEXT REFERENCES invoices(invoice_id),
                payment_id TEXT REFERENCES payments(payment_id),
                amount TEXT,
                note TEXT NOT NULL DEFAULT '',
                target_decision_id INTEGER REFERENCES review_decisions(decision_id),
                created_at TEXT NOT NULL,
                CHECK ((action = 'undo' AND target_decision_id IS NOT NULL)
                    OR (action != 'undo' AND target_decision_id IS NULL))
            );
            CREATE TABLE IF NOT EXISTS allocations (
                allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL UNIQUE REFERENCES review_decisions(decision_id),
                invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
                payment_id TEXT NOT NULL REFERENCES payments(payment_id),
                amount TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS allocations_by_invoice ON allocations(invoice_id);
            CREATE INDEX IF NOT EXISTS allocations_by_payment ON allocations(payment_id);
            """
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The reconciliation store is closed")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    @staticmethod
    def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, AttributeError):
            raise ValueError(f"{field} must be a valid decimal amount") from None
        if not result.is_finite() or (positive and result <= 0):
            constraint = "greater than zero" if positive else "finite"
            raise ValueError(f"{field} must be {constraint}")
        return result

    @staticmethod
    def _text(record: Mapping[str, object], *keys: str, required: bool = False) -> str:
        for key in keys:
            value = record.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        if required:
            raise ValueError(f"{keys[0]} is required")
        return ""

    @staticmethod
    def _money(value: Decimal) -> str:
        return format(value, "f")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_invoice(self, record: Mapping[str, object]) -> None:
        invoice_id = self._text(record, "invoice_id", "id", required=True)
        amount = self._decimal(
            record.get("amount", record.get("invoice_amount", record.get("total"))),
            "invoice amount",
            positive=True,
        )
        try:
            with self._transaction():
                self._db.execute(
                    """INSERT INTO invoices
                    (invoice_id, customer_id, customer_name, reference, amount, due_date)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        invoice_id,
                        self._text(record, "customer_id"),
                        self._text(record, "customer_name", "name"),
                        self._text(record, "reference", "invoice_reference", "invoice_number"),
                        self._money(amount),
                        self._text(record, "due_date", "date"),
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "invoices.invoice_id" in str(error):
                raise ValueError(f"Invoice {invoice_id!r} already exists") from error
            raise

    def add_payment(self, record: Mapping[str, object]) -> None:
        payment_id = self._text(record, "payment_id", "id", required=True)
        amount = self._decimal(
            record.get("amount", record.get("payment_amount")),
            "payment amount",
            positive=True,
        )
        try:
            with self._transaction():
                self._db.execute(
                    """INSERT INTO payments
                    (payment_id, customer_id, customer_name, reference, amount, payment_date)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        payment_id,
                        self._text(record, "customer_id"),
                        self._text(record, "customer_name", "name"),
                        self._text(record, "reference", "payment_reference", "description", "memo"),
                        self._money(amount),
                        self._text(record, "payment_date", "date", "transaction_date"),
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "payments.payment_id" in str(error):
                raise ValueError(f"Payment {payment_id!r} already exists") from error
            raise

    def list_invoices(self) -> list[dict[str, object]]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute("SELECT * FROM invoices ORDER BY invoice_id").fetchall()
        return [{**dict(row), "amount": Decimal(row["amount"])} for row in rows]

    def list_payments(self) -> list[dict[str, object]]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute("SELECT * FROM payments ORDER BY payment_id").fetchall()
        return [{**dict(row), "amount": Decimal(row["amount"])} for row in rows]

    def save_suggestion(self, suggestion: Mapping[str, object]) -> None:
        invoice_id = self._text(suggestion, "invoice_id", required=True)
        payment_id = self._text(suggestion, "payment_id", required=True)
        confidence = int(suggestion.get("confidence", 0))
        if not 0 <= confidence <= 100:
            raise ValueError("confidence must be between 0 and 100")
        evidence = suggestion.get("evidence", [])
        if not isinstance(evidence, (list, tuple)):
            raise ValueError("evidence must be a list or tuple of strings")
        with self._transaction():
            self._db.execute(
                """INSERT INTO suggestions
                (invoice_id, payment_id, confidence, band, explanation, evidence,
                 amount_mismatch, ambiguous)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(invoice_id, payment_id) DO UPDATE SET
                    confidence=excluded.confidence, band=excluded.band,
                    explanation=excluded.explanation, evidence=excluded.evidence,
                    amount_mismatch=excluded.amount_mismatch, ambiguous=excluded.ambiguous""",
                (
                    invoice_id,
                    payment_id,
                    confidence,
                    str(suggestion.get("band", "Low")),
                    str(suggestion.get("explanation", "")),
                    json.dumps(list(evidence)),
                    int(bool(suggestion.get("amount_mismatch", False))),
                    int(bool(suggestion.get("ambiguous", False))),
                ),
            )

    def list_suggestions(self) -> list[dict[str, object]]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                """SELECT * FROM suggestions
                ORDER BY payment_id, confidence DESC, invoice_id"""
            ).fetchall()
        return [
            {
                **dict(row),
                "evidence": json.loads(row["evidence"]),
                "amount_mismatch": bool(row["amount_mismatch"]),
                "ambiguous": bool(row["ambiguous"]),
            }
            for row in rows
        ]

    def _require_invoice(self, invoice_id: str) -> None:
        row = self._db.execute(
            "SELECT 1 FROM invoices WHERE invoice_id=?", (invoice_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Invoice {invoice_id!r} does not exist")

    def _payment_amount(self, payment_id: str) -> Decimal:
        row = self._db.execute(
            "SELECT amount FROM payments WHERE payment_id=?", (payment_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Payment {payment_id!r} does not exist")
        return Decimal(row["amount"])

    def _active_allocations(self, field: str, record_id: str) -> Decimal:
        rows = self._db.execute(
            f"""SELECT a.amount FROM allocations AS a
            WHERE a.{field}=?
              AND NOT EXISTS (
                  SELECT 1 FROM review_decisions AS u
                  WHERE u.action='undo' AND u.target_decision_id=a.decision_id
              )""",
            (record_id,),
        ).fetchall()
        return sum((Decimal(row["amount"]) for row in rows), Decimal("0"))

    def _decision(
        self,
        action: str,
        invoice_id: str,
        payment_id: str,
        amount: Decimal | None,
        note: str,
    ) -> int:
        cursor = self._db.execute(
            """INSERT INTO review_decisions
            (action, invoice_id, payment_id, amount, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (action, invoice_id, payment_id, self._money(amount) if amount is not None else None,
             note.strip(), self._now()),
        )
        return int(cursor.lastrowid)

    def _allocate(
        self,
        action: str,
        invoice_id: str,
        payment_id: str,
        amount: object | None,
        note: str,
    ) -> int:
        with self._transaction():
            self._require_invoice(invoice_id)
            payment_amount = self._payment_amount(payment_id)
            remaining = payment_amount - self._active_allocations("payment_id", payment_id)
            if remaining <= 0:
                raise AllocationError(f"Payment {payment_id!r} has no amount remaining")
            allocated = remaining if amount is None else self._decimal(
                amount, "allocation amount", positive=True
            )
            if allocated > remaining:
                raise AllocationError(
                    f"Allocation {allocated} exceeds payment {payment_id!r} "
                    f"remaining amount {remaining}"
                )
            decision_id = self._decision(action, invoice_id, payment_id, allocated, note)
            self._db.execute(
                """INSERT INTO allocations (decision_id, invoice_id, payment_id, amount)
                VALUES (?, ?, ?, ?)""",
                (decision_id, invoice_id, payment_id, self._money(allocated)),
            )
            return decision_id

    def confirm_match(
        self,
        invoice_id: str,
        payment_id: str,
        amount: object | None = None,
        note: str = "",
    ) -> int:
        return self._allocate("confirm", invoice_id, payment_id, amount, note)

    def manual_assign(
        self,
        invoice_id: str,
        payment_id: str,
        amount: object | None = None,
        note: str = "",
    ) -> int:
        return self._allocate("manual_assign", invoice_id, payment_id, amount, note)

    def reject_match(self, invoice_id: str, payment_id: str, note: str = "") -> int:
        with self._transaction():
            self._require_invoice(invoice_id)
            self._payment_amount(payment_id)
            return self._decision("reject", invoice_id, payment_id, None, note)

    def undo_decision(self, decision_id: int, note: str = "") -> int:
        with self._transaction():
            target = self._db.execute(
                """SELECT action, invoice_id, payment_id FROM review_decisions
                WHERE decision_id=?""",
                (decision_id,),
            ).fetchone()
            if target is None or target["action"] == "undo":
                raise ValueError(f"Decision {decision_id} cannot be undone")
            prior_undo = self._db.execute(
                """SELECT 1 FROM review_decisions
                WHERE action='undo' AND target_decision_id=?""",
                (decision_id,),
            ).fetchone()
            if prior_undo is not None:
                raise ValueError(f"Decision {decision_id} has already been undone")
            cursor = self._db.execute(
                """INSERT INTO review_decisions
                (action, invoice_id, payment_id, note, target_decision_id, created_at)
                VALUES ('undo', ?, ?, ?, ?, ?)""",
                (target["invoice_id"], target["payment_id"], note.strip(),
                 decision_id, self._now()),
            )
            return int(cursor.lastrowid)

    def list_decisions(self) -> list[dict[str, object]]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT * FROM review_decisions ORDER BY decision_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def invoice_balances(self) -> list[InvoiceBalance]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT invoice_id, amount FROM invoices ORDER BY invoice_id"
            ).fetchall()
            balances = []
            for row in rows:
                total = Decimal(row["amount"])
                paid = self._active_allocations("invoice_id", row["invoice_id"])
                balances.append(
                    InvoiceBalance(
                        row["invoice_id"], total, paid, max(Decimal(0), total - paid),
                        max(Decimal(0), paid - total),
                    )
                )
            return balances

    def payment_balances(self) -> list[PaymentBalance]:
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT payment_id, amount FROM payments ORDER BY payment_id"
            ).fetchall()
            balances = []
            for row in rows:
                total = Decimal(row["amount"])
                allocated = self._active_allocations("payment_id", row["payment_id"])
                balances.append(PaymentBalance(row["payment_id"], total, allocated, total - allocated))
            return balances

    def unmatched_invoices(self) -> list[InvoiceBalance]:
        return [balance for balance in self.invoice_balances() if balance.paid_amount == 0]

    def unallocated_payments(self) -> list[PaymentBalance]:
        return [
            balance for balance in self.payment_balances()
            if balance.unallocated_amount > 0
        ]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self) -> ReconciliationStore:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
