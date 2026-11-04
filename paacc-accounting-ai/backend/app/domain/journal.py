"""Deterministic double-entry validation. Contains no tax logic."""
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator


class Line(BaseModel):
    account_code: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")

    @field_validator("debit", "credit")
    @classmethod
    def non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("amounts must be non-negative")
        return v

    @model_validator(mode="after")
    def one_side(self) -> "Line":
        if (self.debit == 0) == (self.credit == 0):
            raise ValueError("a line must have exactly one of debit or credit")
        return self


class JournalEntry(BaseModel):
    description: str = ""
    lines: list[Line]

    @model_validator(mode="after")
    def balanced(self) -> "JournalEntry":
        if len(self.lines) < 2:
            raise ValueError("an entry needs at least two lines")
        if sum(l.debit for l in self.lines) != sum(l.credit for l in self.lines):
            raise ValueError("entry is unbalanced: total debit != total credit")
        return self
