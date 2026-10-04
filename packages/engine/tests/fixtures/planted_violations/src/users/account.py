"""Cycle 1 second half: users.account imports billing.invoice."""

from src.billing.invoice import Invoice


class Account:
    def latest_invoice(self) -> Invoice:
        return Invoice(self)
