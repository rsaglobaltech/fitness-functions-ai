"""Cycle 1 anchor: billing.invoice imports users.account."""

from src.users.account import Account


class Invoice:
    def __init__(self, account: Account) -> None:
        self.account = account
