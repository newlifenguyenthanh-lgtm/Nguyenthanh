"""Draft BOQ generation from analysed drawing data (deterministic; no LLM arithmetic).

Every candidate is built only from values written on the drawing:
- component type is chosen by explicit rules over detected specs/dimensions on the same text line;
- quantities come from app.takeoff.engine (Decimal) or are copied verbatim from schedule tables;
- a missing value stays missing (None) and is flagged for the engineer - nothing is filled in;
- units come from the line itself, or from page units CONFIRMED by an engineer; otherwise the item is blocked.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.pdf.analysis import fold, parse_number
from app.takeoff.engine import MODULES, CalcError, MeasurementRules, calculate

ORIGINS = ("extracted", "ai_inferred", "engineer")
STANDARD_REBAR_MM = {6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 32, 36, 40}
CATEGORY_ORDER = ["concrete", "rebar", "structural_steel", "steel_box", "plate", "other"]
_ELEMENT = re.compile(r"\b(DAM|COT|MONG|SAN|GIANG|VACH|BE\s*TONG|BTCT)\b")
_MARK = re.compile(r"\b(?:DAM|COT|MONG|GIANG|SAN)\s+([A-Z]{1,3}\d{1,3}[A-Z]?)\b")


@dataclass
class Flag:
    code: str
    severity: str  # blocking | warning | info
    message: str

    def as_dict(self):
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class Candidate:
    category: str
    description: str
    spec: str
    module: str | None  # None = quantity stated on the drawing (schedule table)
    inputs: dict[str, dict]  # name -> {"value": str|None, "origin", "source_item_id", "note"?}
    unit_system: str | None
    page_no: int
    bbox: list[float]
    source_item_ids: list[str]
    drawing_id: str
    stated_unit: str | None = None
    flags: list[Flag] = field(default_factory=list)
    mark: str | None = None
    section_key: str | None = None


@dataclass
class Computed:
    quantity: Decimal | None
    unit: str | None
    formula_text: str
    excel_expr: str | None
    calc_inputs: dict[str, str]
    flags: list[Flag]


# ---------------------------------------------------------------- candidate extraction
def _inp(value, src_id, origin="extracted", note=None) -> dict:
    d = {"value": None if value is None else str(value), "origin": origin, "source_item_id": src_id}
    if note:
        d["note"] = note
    return d


def candidates_from_line(line: dict, derived: list[dict], page_units: str | None, page_units_status: str,
                         drawing_id: str) -> Candidate | None:
    """line: raw text item; derived: analysis items whose data.from_item_id == line id."""
    F = fold(line["text"])
    dims = [x for x in derived if x["kind"] == "dimension"]
    specs = {x["data"]["category"]: x for x in derived if x["kind"] == "spec"}
    count = next((x for x in derived if x["kind"] == "count"), None)
    sections = [x for x in dims if x["data"]["type"] == "section"]
    labeled = {x["data"]["label"]: x for x in dims if x["data"]["type"] == "labeled"}
    bars = [x for x in dims if x["data"]["type"] == "bar"]
    length = labeled.get("L") or labeled.get("DAI")
    flags: list[Flag] = []
    inputs: dict[str, dict] = {}

    def val(item, idx=0):
        if item is None:
            return None
        vs = item["data"].get("values") or []
        return vs[idx] if idx < len(vs) else None

    def put(name, item, idx=0):
        inputs[name] = _inp(val(item, idx), item["id"] if item else None)

    sec3 = next((s for s in sections if len(s["data"]["values"]) == 3), None)
    sec2 = next((s for s in sections if len(s["data"]["values"]) == 2), None)
    if "steel_box" in specs and sec3:
        module, category = "steel_box_hollow", "steel_box"
        put("width", sec3, 0); put("height", sec3, 1); put("thickness", sec3, 2); put("length", length)
        used = [sec3, length]
    elif "plate" in specs and specs["plate"]["data"].get("thickness") and sec2:
        module, category = "steel_plate", "plate"
        p = specs["plate"]
        inputs["thickness"] = _inp(p["data"]["thickness"], p["id"])
        put("length", sec2, 0); put("width", sec2, 1)
        used = [sec2]
    elif "steel_profile" in specs:
        module, category = "steel_section_by_weight", "structural_steel"
        put("length", length)
        inputs["unit_weight_kg_m"] = _inp(None, None, note="Nhập khối lượng đơn vị (kg/m) theo catalogue của nhà sản xuất")
        flags.append(Flag("unit_weight_required", "blocking", "Thiếu khối lượng đơn vị kg/m của thép hình – hệ thống không tự tra"))
        used = [length]
    elif bars:
        module, category = "rebar_weight", "rebar"
        b = bars[0]
        inputs["diameter_mm"] = _inp(b["data"]["diameter"], b["id"],
                                     note="Ký hiệu Ø được hiểu là mm theo quy ước bản vẽ")
        flags.append(Flag("diameter_convention_mm", "warning", f"Ø{b['data']['diameter']} được hiểu là {b['data']['diameter']} mm theo quy ước – cần kỹ sư xác nhận"))
        put("length", length)
        used = [length]
    elif sec2 and (_ELEMENT.search(F) or "concrete_grade" in specs):
        module, category = "concrete_prism", "concrete"
        put("width", sec2, 0); put("height", sec2, 1); put("length", length)
        used = [sec2, length]
    else:
        return None
    inputs["count"] = _inp(count["data"]["count"] if count else None, count["id"] if count else None)

    # ---- units: explicit on the line, else engineer-confirmed page units, else blocked
    explicit = {x["data"]["unit"] for x in used if x and x["data"].get("unit")}
    unit = None
    if len(explicit) > 1:
        flags.append(Flag("inconsistent_units", "blocking", f"Các kích thước trên cùng dòng dùng đơn vị khác nhau: {sorted(explicit)}"))
    elif explicit:
        unit = explicit.pop()
        if page_units_status == "confirmed" and page_units and unit != page_units:
            flags.append(Flag("unit_conflict", "warning", f"Dòng ghi {unit} nhưng đơn vị trang đã xác nhận là {page_units}"))
    elif MODULES[module].dimensional:
        if page_units_status == "confirmed" and page_units:
            unit = page_units
        else:
            flags.append(Flag("unit_unconfirmed", "blocking", "Kích thước không ghi đơn vị và đơn vị trang chưa được xác nhận"))

    for x in derived:
        for f in x["data"].get("flags", []):
            if f == "ambiguous_number":
                flags.append(Flag("ambiguous_number", "blocking", f"Số mơ hồ trong '{x['text']}' – cần nhập lại giá trị"))
    low = [x for x in derived if x.get("confidence") is not None and x["confidence"] < 0.6 and x["data"].get("from_source") == "ocr"]
    if low:
        flags.append(Flag("low_confidence_source", "warning", "Giá trị đọc bằng OCR với độ tin cậy thấp – đối chiếu với bản vẽ"))

    mark = _MARK.search(F)
    sec = sec3 or sec2
    return Candidate(category=category, description=line["text"], spec=", ".join(dict.fromkeys(s["text"].strip() for s in specs.values())),
                     module=module, inputs=inputs, unit_system=unit, page_no=line["page_no"], bbox=list(line["bbox"]),
                     source_item_ids=[line["id"]] + [x["id"] for x in derived], drawing_id=drawing_id, flags=flags,
                     mark=mark.group(1) if mark else None,
                     section_key="x".join(sec["data"]["values"]) if sec and all(sec["data"]["values"]) else None)


_UNIT_NORM = {"M3": "m3", "M2": "m2", "M": "m", "KG": "kg", "TAN": "tấn", "T": "tấn", "CAI": "cái", "CHIEC": "cái",
              "BO": "bộ", "THANH": "thanh", "TAM": "tấm", "MD": "m"}


def category_for(text: str) -> str:
    F = fold(text)
    if re.search(r"THEP\s+HOP|\bRHS\b|\bSHS\b", F):
        return "steel_box"
    if re.search(r"BAN\s+MA|THEP\s+TAM|\bPL\d", F):
        return "plate"
    if re.search(r"THEP\s+HINH|\b[IHU]\d{3}\b", F):
        return "structural_steel"
    if re.search(r"COT\s+THEP|THEP\s+(?:THANH|TRON|GAN)|Ø", F):
        return "rebar"
    if _ELEMENT.search(F):
        return "concrete"
    return "other"


def candidates_from_table(table: dict, drawing_id: str) -> list[Candidate]:
    data = table["data"]
    if data.get("table_type") != "material_schedule":
        return []
    hm = {v: int(k) for k, v in data["header_map"].items()}
    qcol = hm.get("quantity", hm.get("weight"))
    if qcol is None:
        return []
    out = []
    cells = data.get("cells") or []
    for r, row in enumerate(data["rows"][1:], start=1):
        if not any(row):
            continue
        get = lambda name: row[hm[name]] if name in hm and hm[name] < len(row) else ""
        raw_q = row[qcol] if qcol < len(row) else ""
        qv, amb = parse_number(raw_q) if raw_q else (None, False)
        flags = []
        if not raw_q:
            flags.append(Flag("quantity_missing", "blocking", "Ô khối lượng trong bảng để trống"))
        elif qv is None:
            flags.append(Flag("ambiguous_number", "blocking", f"Khối lượng '{raw_q}' mơ hồ (dấu phân cách) – cần nhập lại"))
        unit_raw = get("unit") or ("kg" if "quantity" not in hm and "weight" in hm else "")
        unit = _UNIT_NORM.get(fold(unit_raw).replace(" ", "").replace(".", ""), unit_raw or None)
        if not unit:
            flags.append(Flag("unit_missing", "blocking", "Bảng không ghi đơn vị tính cho dòng này"))
        row_boxes = [c for c in (cells[r] if r < len(cells) else []) if c]
        bbox = [min(c[0] for c in row_boxes), min(c[1] for c in row_boxes), max(c[2] for c in row_boxes), max(c[3] for c in row_boxes)] \
            if row_boxes else [table["bbox"][0], table["bbox"][1], table["bbox"][2], table["bbox"][3]]
        desc = get("description") or get("mark") or f"Dòng {r}"
        spec = get("spec")
        F = fold(f"{desc} {spec}")
        mark = re.search(r"\b([A-Z]{1,3}\d{1,3}[A-Z]?)\b", fold(desc))
        sec = re.search(r"(\d+(?:[.,]\d+)?)\s*X\s*(\d+(?:[.,]\d+)?)(?:\s*X\s*(\d+(?:[.,]\d+)?))?", F)
        out.append(Candidate(category=category_for(f"{desc} {spec}"), description=desc, spec=spec, module=None,
                             inputs={"quantity": {**_inp(format(qv, "f") if qv is not None else None, table["id"]), "cell": [r, qcol], "raw": raw_q}},
                             unit_system=None, stated_unit=unit, page_no=table["page_no"], bbox=bbox, source_item_ids=[table["id"]],
                             drawing_id=drawing_id, flags=flags, mark=mark.group(1) if mark else None,
                             section_key="x".join(g.replace(",", ".") for g in sec.groups() if g) if sec else None))
    return out


# ---------------------------------------------------------------- computation + validation
def compute(module: str | None, inputs: dict[str, dict], unit_system: str | None, waste: Decimal,
            rules: MeasurementRules, stated_unit: str | None = None) -> Computed:
    flags: list[Flag] = []
    if module is None:  # stated quantity, copied verbatim (no arithmetic except optional waste)
        v = inputs.get("quantity", {}).get("value")
        if v is None:
            return Computed(None, stated_unit, "Số liệu từ bảng thống kê – thiếu giá trị", None, {}, flags)
        q = Decimal(v) * (1 + waste)
        q = q.quantize(Decimal(1).scaleb(-rules.decimals))
        text = f"{v} (trích nguyên văn bảng thống kê)" + (f" × (1 + {waste})" if waste else "")
        return Computed(q, stated_unit, text, "{quantity}", {"quantity": v}, flags)
    m = MODULES[module]
    missing = [f.label_vi for f in m.fields if inputs.get(f.name, {}).get("value") in (None, "")]
    if missing:
        flags.append(Flag("input_missing", "blocking", "Thiếu dữ liệu: " + ", ".join(missing)))
        return Computed(None, m.out_unit, "", m.expr, {}, flags)
    if m.dimensional and not unit_system:
        return Computed(None, m.out_unit, "", m.expr, {}, flags)  # unit flag already raised by generator/editor
    params = {f.name: inputs[f.name]["value"] for f in m.fields}
    if m.dimensional:
        params["unit"] = unit_system
    try:
        r = calculate(module, params, waste, rules)
    except CalcError as e:
        flags.append(Flag(e.code, "blocking", str(e)))
        return Computed(None, m.out_unit, "", m.expr, {}, flags)
    flags += sanity_flags(module, r.inputs, unit_system)
    return Computed(r.quantity, r.unit, r.formula_text, r.excel_expr, {k: format(v, "f") for k, v in r.inputs.items()}, flags)


def sanity_flags(module: str, inp: dict[str, Decimal], unit: str | None) -> list[Flag]:
    """Plausibility warnings (never block, never change values)."""
    out = []
    k = inp.get("to_m", Decimal(1))
    for name in ("length", "width", "height", "thickness"):
        if name in inp:
            metres = inp[name] * k
            if metres > 200:
                out.append(Flag("suspicious_large_dimension", "warning", f"{name} = {metres} m – kiểm tra đơn vị/tỷ lệ"))
            if metres < Decimal("0.001"):
                out.append(Flag("suspicious_small_dimension", "warning", f"{name} = {metres} m – kiểm tra đơn vị"))
    if module == "rebar_weight":
        d = inp["diameter_mm"]
        if d % 1 or int(d) not in STANDARD_REBAR_MM:
            out.append(Flag("nonstandard_rebar_diameter", "warning", f"Đường kính {d} mm không thuộc dãy thông dụng"))
    if module == "steel_plate" and inp["thickness"] * k > Decimal("0.1"):
        out.append(Flag("suspicious_plate_thickness", "warning", "Bản mã dày > 100 mm"))
    if inp.get("count", 0) > 10000:
        out.append(Flag("suspicious_count", "warning", "Số lượng > 10.000"))
    return out


def duplicate_groups(items: list[dict]) -> dict[str, list[dict]]:
    """items: {id, module, calc_inputs, unit_system, source_item_ids, mark, section_key, category, quantity, unit}.
    Returns item_id -> list of {other_id, reason, quantities_match?}."""
    out: dict[str, list[dict]] = {}

    def add(a, b, reason, **kw):
        out.setdefault(a["id"], []).append({"other_id": b["id"], "reason": reason, **kw})
        out.setdefault(b["id"], []).append({"other_id": a["id"], "reason": reason, **kw})

    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if set(a["source_item_ids"][:1]) & set(b["source_item_ids"][:1]) and a["module"] and b["module"]:
                add(a, b, "same_source_annotation")
            elif a["module"] and a["module"] == b["module"] and a["calc_inputs"] and a["calc_inputs"] == b["calc_inputs"]:
                add(a, b, "identical_calculation")
            elif (a["module"] is None) != (b["module"] is None) and a["category"] == b["category"] \
                    and a["section_key"] and a["section_key"] == b["section_key"] and (not a["mark"] or not b["mark"] or a["mark"] == b["mark"]):
                match = None
                if a["quantity"] is not None and b["quantity"] is not None and a["unit"] == b["unit"]:
                    qa, qb = Decimal(str(a["quantity"])), Decimal(str(b["quantity"]))
                    match = abs(qa - qb) <= max(abs(qa), abs(qb)) * Decimal("0.005")
                add(a, b, "schedule_and_annotation", quantities_match=match)
    return out
