"""Phase 5E-1 – deterministic quantity engine (pure; Decimal only; no DB, no LLM).

CONFIRMED component + 5B measurement(s) + calculation method (+ engineer-stated parameters) -> quantity calculation.
Values are READ from 5B measurements (never re-measured). Inputs that are not authoritative make the result
REQUIRES_REVIEW or BLOCKED with value None – a final quantity is never produced from them.
Methods are a registry: adding one = one entry, no change to callers.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from app.quantity import rounding, units

QUANTITY_TYPES = ("COUNT", "LENGTH", "AREA", "VOLUME", "WEIGHT", "SPACING", "PERIMETER")


@dataclass(frozen=True)
class MeasIn:
    id: str
    kind: str  # 5B kind
    value_real: Decimal | None
    real_unit: str | None
    status: str  # 5B: computed | confirmed | rejected
    details: dict = field(default_factory=dict)


@dataclass
class Calc:
    status: str  # CALCULATED | REQUIRES_REVIEW | BLOCKED
    quantity_type: str
    method: str
    unit: str
    raw: Decimal | None = None
    value: Decimal | None = None
    precision: int = 3
    rounding_rule: str = "ROUND_HALF_UP"
    formula: str = ""
    input_measurement_ids: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


class QuantityError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Method:
    code: str
    quantity_type: str
    unit: str  # canonical result unit
    inputs: tuple[str, ...]  # required 5B measurement kinds, in order
    params: tuple[str, ...]  # required engineer-stated parameters
    fn: Callable[[list[Decimal], dict[str, Decimal]], Decimal]
    formula: str


def _ref(v, p):
    return v[0]


METHODS: dict[str, Method] = {m.code: m for m in (
    Method("COUNT_REFERENCE", "COUNT", "ea", ("count",), (), _ref, "số lượng = phép đo count"),
    Method("MEASUREMENT_REFERENCE", "LENGTH", "m", ("length",), (), _ref, "chiều dài = phép đo length"),
    Method("SPACING_REFERENCE", "SPACING", "m", ("spacing",), (), _ref, "bước = phép đo spacing"),
    Method("AREA_REFERENCE", "AREA", "m2", ("area",), (), _ref, "diện tích = phép đo area"),
    Method("PERIMETER_REFERENCE", "PERIMETER", "m", ("perimeter",), (), _ref, "chu vi = phép đo perimeter"),
    Method("COUNT_X_LENGTH", "LENGTH", "m", ("count",), ("unit_length",), lambda v, p: v[0] * p["unit_length"],
           "chiều dài = count × chiều dài đơn vị"),
    Method("LENGTH_X_UNIT_WEIGHT", "WEIGHT", "kg", ("length",), ("unit_weight",), lambda v, p: v[0] * p["unit_weight"],
           "khối lượng = length × trọng lượng đơn vị"),
)}
PARAM_DIMENSION = {"unit_length": "length", "unit_weight": "linear_mass"}
DEFAULT_METHOD = {"count": "COUNT_REFERENCE", "length": "MEASUREMENT_REFERENCE", "area": "AREA_REFERENCE",
                  "perimeter": "PERIMETER_REFERENCE", "spacing": "SPACING_REFERENCE"}


def _param(name: str, spec) -> tuple[Decimal | None, str | None]:
    """Engineer-stated parameter {"value": "2.5", "unit": "m", "source": "..."} -> value in the base unit, or None."""
    if not isinstance(spec, dict) or spec.get("value") in (None, ""):
        return None, None
    if not str(spec.get("source", "")).strip():
        return None, f"Tham số {name} thiếu nguồn (bảng tra / bản vẽ / kỹ sư) – không dùng"
    try:
        v = Decimal(str(spec["value"]))
    except Exception:  # noqa: BLE001
        return None, f"Tham số {name} không phải số"
    if not v.is_finite() or v <= 0:
        return None, f"Tham số {name} phải > 0"
    unit = units.normalize(spec.get("unit", ""))
    if units.dimension(unit) != PARAM_DIMENSION[name]:
        raise QuantityError(422, f"Đơn vị của {name} không hợp lệ: {spec.get('unit')}")
    return units.to_base(v, unit)[0], None


def calculate(method_code: str, measurements: list[MeasIn], parameters: dict | None = None, *, precision: int = 3,
              rounding_rule: str = "ROUND_HALF_UP", group_status: str | None = None) -> Calc:
    m = METHODS.get(method_code)
    if not m:
        raise QuantityError(422, f"Phương pháp tính không hợp lệ: {method_code}")
    parameters = parameters or {}
    c = Calc("CALCULATED", m.quantity_type, m.code, m.unit, precision=precision, rounding_rule=rounding_rule, formula=m.formula)
    rounding.apply(Decimal(0), precision, rounding_rule)  # validates the rule/precision up-front (raises ValueError)
    vals: list[Decimal] = []
    for kind in m.inputs:
        ms = [x for x in measurements if x.kind == kind]
        if not ms:
            c.status = "BLOCKED"
            c.reasons.append(f"Thiếu phép đo 5B loại '{kind}'")
            continue
        x = next((y for y in ms if y.status == "confirmed"), ms[0])
        c.input_measurement_ids.append(x.id)
        if x.status == "rejected":
            c.status = "BLOCKED"
            c.reasons.append(f"Phép đo {kind} đã bị loại bỏ")
        elif x.value_real is None:
            c.status = "BLOCKED"
            c.reasons.append(f"Phép đo {kind} chưa có giá trị thật (tỷ lệ chưa được xác nhận)")
        elif x.status != "confirmed":
            c.status = _worst(c.status, "REQUIRES_REVIEW")
            c.reasons.append(f"Phép đo {kind} chưa được kỹ sư xác nhận (5B: {x.status})")
        else:
            base, _ = units.to_base(x.value_real, x.real_unit or ("ea" if kind == "count" else "m"))
            vals.append(base)
        if kind == "spacing" and x.details.get("uniform") is False:
            c.status = _worst(c.status, "REQUIRES_REVIEW")
            c.reasons.append("Bước lặp không đều – cần kỹ sư xem lại")
    if group_status in ("OCCLUDED", "IRREGULAR_PATTERN") and "count" in m.inputs:
        c.status = _worst(c.status, "REQUIRES_REVIEW")
        c.reasons.append(f"Dãy lặp {group_status}: số đếm chỉ là phần thấy được – cần kỹ sư xác nhận")
    pv: dict[str, Decimal] = {}
    for name in m.params:
        v, why = _param(name, parameters.get(name))
        c.parameters[name] = parameters.get(name)
        if v is None:
            c.status = _worst(c.status, "REQUIRES_REVIEW")
            c.reasons.append(why or f"Thiếu tham số {name} – không tự đoán")
        else:
            pv[name] = v
    if c.status != "CALCULATED":
        return c  # never a final value from non-authoritative inputs
    c.raw = m.fn(vals, pv)  # exact Decimal, no intermediate rounding
    c.value = rounding.apply(c.raw, precision, rounding_rule)
    return c


_RANK = {"CALCULATED": 0, "REQUIRES_REVIEW": 1, "BLOCKED": 2}


def _worst(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b
