"""Deterministic quantity calculation engine. No LLM, no floats: everything is Decimal.

Each module declares its input fields, an Excel-compatible expression (so the workbook keeps live formulas)
and the Python computation. Units are NEVER assumed: dimensional modules require an explicit `unit`.
Waste factors are NEVER defaulted to a non-zero value: they must be supplied by the user/rules.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Callable

PI = Decimal("3.14159265358979323846264338")
from app.quantity.units import factor as _unit_factor  # noqa: E402  (single unit table, 5E-1)

UNIT_TO_M = {u: _unit_factor(u, "m") for u in ("mm", "cm", "m")}


class CalcError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MeasurementRules:
    """Configurable rules. steel_density is a physical constant (kg/m3) used for weight from volume;
    it is configurable and recorded in every result - confirm it is the value your BOQ convention uses."""
    decimals: int = 3
    steel_density: Decimal = Decimal("7850")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label_vi: str
    kind: str  # "dim" (uses unit) | "count" (positive integer) | "number" (positive, unitless/fixed unit)


@dataclass
class CalcResult:
    module: str
    unit: str
    net: Decimal
    waste_factor: Decimal
    quantity: Decimal  # gross (with waste), rounded
    decimals: int
    excel_expr: str  # raw expression with {placeholders}
    inputs: dict[str, Decimal]  # every numeric used, incl. derived constants (to_m, steel_density)
    input_labels: dict[str, str]
    formula_text: str
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Module:
    key: str
    title_vi: str
    category: str
    out_unit: str
    fields: tuple[FieldSpec, ...]
    expr: str
    compute: Callable[[dict[str, Decimal], Decimal, MeasurementRules], Decimal]
    uses_density: bool = False
    validate: Callable[[dict[str, Decimal]], None] | None = None
    extras: Callable[[dict[str, Decimal], Decimal], dict[str, str]] | None = None

    @property
    def dimensional(self) -> bool:
        return any(f.kind == "dim" for f in self.fields)


def _dec(name: str, v) -> Decimal:
    if isinstance(v, bool) or v is None:
        raise CalcError("invalid_number", f"'{name}' không hợp lệ")
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise CalcError("invalid_number", f"'{name}' không phải số hợp lệ") from None
    if not d.is_finite():
        raise CalcError("invalid_number", f"'{name}' không hữu hạn")
    return d


def _steel_geometry(p: dict[str, Decimal]) -> None:
    if 2 * p["thickness"] >= min(p["width"], p["height"]):
        raise CalcError("invalid_geometry", "Chiều dày thành ≥ nửa cạnh nhỏ: tiết diện hộp không hợp lệ")


_L, _W, _H, _T = (FieldSpec("length", "Chiều dài", "dim"), FieldSpec("width", "Chiều rộng", "dim"),
                  FieldSpec("height", "Chiều cao", "dim"), FieldSpec("thickness", "Chiều dày", "dim"))
_N = FieldSpec("count", "Số lượng", "count")

MODULES: dict[str, Module] = {m.key: m for m in [
    Module("concrete_prism", "Bê tông khối lăng trụ (D×R×C×SL)", "concrete", "m3", (_L, _W, _H, _N),
           "{length}*{width}*{height}*{count}*{to_m}^3",
           lambda p, k, r: p["length"] * p["width"] * p["height"] * p["count"] * k ** 3),
    Module("concrete_area_thickness", "Bê tông theo diện tích × chiều dày", "concrete", "m3",
           (FieldSpec("area_m2", "Diện tích (m2)", "number"), _T),
           "{area_m2}*{thickness}*{to_m}",
           lambda p, k, r: p["area_m2"] * p["thickness"] * k),
    Module("rebar_weight", "Thép thanh theo đường kính (kg)", "rebar", "kg",
           (FieldSpec("diameter_mm", "Đường kính (mm)", "number"), _L, _N),
           "PI()/4*{diameter_mm}^2*0.000001*{length}*{to_m}*{steel_density}*{count}",
           lambda p, k, r: PI / 4 * p["diameter_mm"] ** 2 * Decimal("0.000001") * p["length"] * k * r.steel_density * p["count"],
           uses_density=True),
    Module("steel_section_by_weight", "Thép hình theo khối lượng đơn vị (kg/m) do người dùng/bảng cung cấp", "structural_steel", "kg",
           (_L, FieldSpec("unit_weight_kg_m", "Khối lượng đơn vị (kg/m)", "number"), _N),
           "{length}*{to_m}*{unit_weight_kg_m}*{count}",
           lambda p, k, r: p["length"] * k * p["unit_weight_kg_m"] * p["count"]),
    Module("steel_box_hollow", "Thép hộp chữ nhật (góc vuông, bỏ qua bo góc)", "steel_box", "kg",
           (FieldSpec("width", "Cạnh rộng", "dim"), FieldSpec("height", "Cạnh cao", "dim"), _T, _L, _N),
           "({width}*{height}-({width}-2*{thickness})*({height}-2*{thickness}))*{to_m}^2*{length}*{to_m}*{steel_density}*{count}",
           lambda p, k, r: (p["width"] * p["height"] - (p["width"] - 2 * p["thickness"]) * (p["height"] - 2 * p["thickness"]))
           * k ** 2 * p["length"] * k * r.steel_density * p["count"],
           uses_density=True, validate=_steel_geometry),
    Module("steel_plate", "Bản mã / thép tấm (D×R×dày×SL×tỷ trọng)", "plate", "kg", (_L, _W, _T, _N),
           "{length}*{width}*{thickness}*{to_m}^3*{steel_density}*{count}",
           lambda p, k, r: p["length"] * p["width"] * p["thickness"] * k ** 3 * r.steel_density * p["count"],
           uses_density=True,
           extras=lambda p, k: {"area_m2": str(p["length"] * p["width"] * k ** 2 * p["count"])}),
    Module("length_total", "Chiều dài tổng (D×SL)", "other", "m", (_L, _N),
           "{length}*{to_m}*{count}", lambda p, k, r: p["length"] * k * p["count"]),
    Module("area_rect", "Diện tích chữ nhật (D×R×SL)", "other", "m2", (_L, _W, _N),
           "{length}*{width}*{to_m}^2*{count}", lambda p, k, r: p["length"] * p["width"] * k ** 2 * p["count"]),
    Module("count_items", "Đếm số lượng", "other", "cái", (_N,), "{count}", lambda p, k, r: p["count"]),
]}


def list_modules() -> list[dict]:
    return [{"key": m.key, "title_vi": m.title_vi, "category": m.category, "out_unit": m.out_unit,
             "dimensional": m.dimensional,
             "fields": [{"name": f.name, "label_vi": f.label_vi, "kind": f.kind} for f in m.fields]}
            for m in MODULES.values()]


def calculate(module_key: str, params: dict, waste_factor=Decimal("0"),
              rules: MeasurementRules | None = None) -> CalcResult:
    rules = rules or MeasurementRules()
    m = MODULES.get(module_key)
    if m is None:
        raise CalcError("unknown_module", f"Module '{module_key}' không tồn tại")
    to_m = Decimal("1")
    if m.dimensional:
        unit = params.get("unit")
        if unit not in UNIT_TO_M:
            raise CalcError("unit_missing", "Phải chỉ rõ đơn vị kích thước (mm, cm hoặc m); hệ thống không tự giả định")
        to_m = UNIT_TO_M[unit]
    p: dict[str, Decimal] = {}
    for f in m.fields:
        if f.name not in params:
            raise CalcError("input_missing", f"Thiếu dữ liệu: {f.label_vi} ({f.name})")
        d = _dec(f.name, params[f.name])
        if d <= 0:
            raise CalcError("non_positive", f"{f.label_vi} phải > 0")
        if f.kind == "count" and d != d.to_integral_value():
            raise CalcError("count_not_integer", f"{f.label_vi} phải là số nguyên")
        p[f.name] = d
    if m.validate:
        m.validate(p)
    w = _dec("waste_factor", waste_factor)
    if not (Decimal("0") <= w <= Decimal("1")):
        raise CalcError("invalid_waste", "Hệ số hao hụt phải trong khoảng 0–1 (ví dụ 0.02 = 2%)")
    net = m.compute(p, to_m, rules)
    gross = net * (1 + w)
    q = gross.quantize(Decimal(1).scaleb(-rules.decimals), rounding=ROUND_HALF_UP)

    inputs = dict(p)
    labels = {f.name: f.label_vi for f in m.fields}
    if m.dimensional:
        inputs["to_m"] = to_m
        labels["to_m"] = f"Hệ số đổi {params['unit']} → m"
    if m.uses_density:
        inputs["steel_density"] = rules.steel_density
        labels["steel_density"] = "Tỷ trọng thép (kg/m3)"
    text = m.expr
    for k, v in inputs.items():
        text = text.replace("{" + k + "}", format(v, "f"))
    text = text.replace("*", " × ").replace("PI()", "π")
    if w:
        text = f"({text}) × (1 + {format(w, 'f')})"
    return CalcResult(m.key, m.out_unit, net, w, q, rules.decimals, m.expr, inputs, labels, text,
                      m.extras(p, to_m) if m.extras else {})
