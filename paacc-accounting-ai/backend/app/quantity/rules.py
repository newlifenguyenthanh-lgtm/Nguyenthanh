"""Phase 5E-2 – quantity rule registry: component_type -> rules (DATA in rules.json, validated against engine.METHODS).

Adding a component type's rule = adding a JSON entry; the engine and the service never branch on component names.
"""
import functools
import json
import pathlib
from dataclasses import dataclass, field

from app.quantity import engine as E

RULES_FILE = pathlib.Path(__file__).with_name("rules.json")


@dataclass(frozen=True)
class Rule:
    rule_code: str
    component_type: str
    quantity_type: str
    method: str
    required_measurements: tuple[str, ...]
    required_parameters: tuple[str, ...]
    formula: str
    output_unit: str
    validation: dict = field(default_factory=dict)
    auto: bool = True
    note: str = ""


class RuleError(ValueError):
    pass


def validate(r: Rule) -> None:
    m = E.METHODS.get(r.method)
    if not m:
        raise RuleError(f"{r.rule_code}: phương pháp không tồn tại {r.method}")
    if (r.quantity_type, r.output_unit) != (m.quantity_type, m.unit):
        raise RuleError(f"{r.rule_code}: loại/đơn vị {r.quantity_type}/{r.output_unit} ≠ phương pháp {m.quantity_type}/{m.unit}")
    if tuple(r.required_measurements) != m.inputs or tuple(r.required_parameters) != m.params:
        raise RuleError(f"{r.rule_code}: đầu vào không khớp phương pháp {r.method}")
    if r.quantity_type not in E.QUANTITY_TYPES or set(r.validation) - {"integer", "positive", "max"}:
        raise RuleError(f"{r.rule_code}: loại khối lượng hoặc kiểm tra không hợp lệ")


def load(data: dict) -> dict[str, Rule]:
    out: dict[str, Rule] = {}
    for x in data["rules"]:
        r = Rule(x["rule_code"], x["component_type"], x["quantity_type"], x["method"], tuple(x["required_measurements"]),
                 tuple(x["required_parameters"]), x["formula"], x["output_unit"], x.get("validation") or {}, x.get("auto", True),
                 x.get("note", ""))
        validate(r)
        if r.rule_code in out:
            raise RuleError(f"Trùng mã quy tắc {r.rule_code}")
        out[r.rule_code] = r
    return out


@functools.lru_cache
def registry() -> dict[str, Rule]:
    return load(json.loads(RULES_FILE.read_text()))


def rules_for(component_type: str) -> list[Rule]:
    return [r for r in registry().values() if r.component_type == component_type]
