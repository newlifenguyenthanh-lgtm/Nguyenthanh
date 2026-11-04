"""Deterministic contract value logic (no LLM). Only APPROVED appendices change contract value."""
from decimal import Decimal


def adjusted_value(original: Decimal, appendices: list[tuple[Decimal, str]]) -> Decimal:
    """appendices: (delta_value, status). Draft/rejected are excluded."""
    return original + sum((d for d, s in appendices if s == "approved"), Decimal("0"))
