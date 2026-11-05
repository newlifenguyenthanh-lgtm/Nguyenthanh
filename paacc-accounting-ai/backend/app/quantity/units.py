"""Phase 5E-1 – the ONE unit table of the system (Decimal, exact factors). Every conversion goes through here."""
from decimal import Decimal

# unit -> (dimension, factor to the dimension's base unit). Count units never convert into each other (ea ≠ set ≠ piece).
UNITS: dict[str, tuple[str, Decimal]] = {
    "mm": ("length", Decimal("0.001")), "cm": ("length", Decimal("0.01")), "m": ("length", Decimal("1")),
    "mm2": ("area", Decimal("0.000001")), "cm2": ("area", Decimal("0.0001")), "m2": ("area", Decimal("1")),
    "mm3": ("volume", Decimal("0.000000001")), "cm3": ("volume", Decimal("0.000001")), "m3": ("volume", Decimal("1")),
    "kg": ("mass", Decimal("1")), "t": ("mass", Decimal("1000")),
    "ea": ("count_ea", Decimal("1")), "set": ("count_set", Decimal("1")), "piece": ("count_piece", Decimal("1")),
    "kg/m": ("linear_mass", Decimal("1")), "kg/m2": ("area_mass", Decimal("1")),
}
BASE = {"length": "m", "area": "m2", "volume": "m3", "mass": "kg", "count_ea": "ea", "count_set": "set", "count_piece": "piece",
        "linear_mass": "kg/m", "area_mass": "kg/m2"}
ALIASES = {"m²": "m2", "mm²": "mm2", "cm²": "cm2", "m³": "m3", "mm³": "mm3", "cm³": "cm3", "count": "ea", "cái": "ea", "each": "ea",
           "pcs": "piece", "bộ": "set", "tấn": "t", "ton": "t", "kg/md": "kg/m"}


class UnitError(ValueError):
    pass


def normalize(unit: str) -> str:
    u = (unit or "").strip()
    u = ALIASES.get(u, ALIASES.get(u.lower(), u.lower()))
    if u not in UNITS:
        raise UnitError(f"Đơn vị không hỗ trợ: {unit!r}")
    return u


def dimension(unit: str) -> str:
    return UNITS[normalize(unit)][0]


def factor(src: str, dst: str) -> Decimal:
    s, d = normalize(src), normalize(dst)
    if UNITS[s][0] != UNITS[d][0]:
        raise UnitError(f"Không đổi được {src} → {dst} (khác thứ nguyên)")
    return UNITS[s][1] / UNITS[d][1]


def convert(value: Decimal, src: str, dst: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise UnitError("Giá trị phải là Decimal")
    return value * factor(src, dst)


def to_base(value: Decimal, unit: str) -> tuple[Decimal, str]:
    u = normalize(unit)
    base = BASE[UNITS[u][0]]
    return convert(value, u, base), base
