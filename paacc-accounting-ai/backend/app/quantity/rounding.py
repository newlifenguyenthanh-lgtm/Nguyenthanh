"""Explicit, configurable rounding. Applied ONCE to the final quantity, never to intermediate values."""
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal

RULES = {"ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_HALF_EVEN": ROUND_HALF_EVEN, "ROUND_DOWN": ROUND_DOWN, "ROUND_UP": ROUND_UP,
         "ROUND_CEILING": ROUND_CEILING, "ROUND_FLOOR": ROUND_FLOOR}


def apply(raw: Decimal, precision: int, rule: str) -> Decimal:
    if rule not in RULES:
        raise ValueError(f"Quy tắc làm tròn không hợp lệ: {rule}")
    if not 0 <= precision <= 6:
        raise ValueError("Số chữ số thập phân phải trong 0..6")
    return raw.quantize(Decimal(1).scaleb(-precision), rounding=RULES[rule])
