"""Rule-based drawing analysis (pure functions, no I/O, no LLM).

Principles:
- Only report what is written on the drawing. Nothing is inferred when absent.
- Ambiguous numbers ("6,000": 6 or 6000?) are flagged, never guessed.
- Scale and units are only *candidates* here; they become authoritative only after human confirmation.
- Every result keeps the id/bbox of the line it came from and a confidence (pattern certainty x OCR confidence).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

BBox = tuple[float, float, float, float]


@dataclass
class Line:
    id: str
    page_no: int
    text: str
    bbox: BBox
    source: str = "text"  # text | ocr
    confidence: float | None = None  # OCR confidence 0-1

    @property
    def source_conf(self) -> float:
        return self.confidence if self.source == "ocr" and self.confidence is not None else 1.0


@dataclass
class Finding:
    kind: str  # dimension | spec | symbol | reference | count
    raw: str
    data: dict
    confidence: float
    line: Line
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- text helpers
_SPECIAL = {"đ": "d", "Đ": "D", "×": "X", "∅": "Ø", "ø": "Ø", "Φ": "Ø", "φ": "Ø", "²": "2", "³": "3"}


def fold(s: str) -> str:
    """Upper-case, accent-free copy with the SAME length as the NFC input (so match spans map back)."""
    out = []
    for ch in unicodedata.normalize("NFC", s):
        if ch in _SPECIAL:
            out.append(_SPECIAL[ch])
            continue
        base = unicodedata.normalize("NFD", ch)[0]
        up = base.upper()
        out.append(up if len(up) == 1 else base)
    return "".join(out)


def parse_number(raw: str) -> tuple[Decimal | None, bool]:
    """Returns (value, ambiguous). Vietnamese and international separators both occur on drawings."""
    s = raw.strip()
    try:
        if "," in s and "." in s:
            dec = s[max(s.rfind(","), s.rfind("."))]
            thou = "." if dec == "," else ","
            return Decimal(s.replace(thou, "").replace(dec, ".")), False
        sep = "," if "," in s else "." if "." in s else None
        if sep is None:
            return Decimal(s), False
        parts = s.split(sep)
        if len(parts) > 2:
            return (Decimal("".join(parts)), False) if all(len(p) == 3 for p in parts[1:]) else (None, True)
        if len(parts[1]) == 3 and parts[0] != "0":
            return None, True  # 6,000 / 6.000 -> could be 6 or 6000
        return Decimal(f"{parts[0]}.{parts[1]}"), False
    except InvalidOperation:
        return None, True


NUM = r"\d+(?:[.,]\d+)*"
UNIT = r"(MM|CM|M)(?![0-9A-Z])"


def _num(raw: str) -> tuple[str | None, bool]:
    v, amb = parse_number(raw)
    return (format(v, "f") if v is not None else None), amb


# ---------------------------------------------------------------- dimensions, specs, symbols, references
# Order matters: earlier patterns claim their span first.
_BOLT_CUE = re.compile(r"BU\s*LONG|BULONG|\bBOLT")
_DIM_PATTERNS = [
    # M16x35, M8x100 (metric bolt: diameter x length)
    ("bolt", re.compile(rf"(?<![A-Z0-9])M\s?(\d{{1,2}})\s*X\s*({NUM})(?:\s*{UNIT})?")),
    # "Bu lông D20x180mm" - D-notation is a bolt only when the line talks about bolts
    ("bolt_d", re.compile(rf"(?<![A-Z0-9.])D\s?(\d{{1,2}})\s*X\s*({NUM})(?:\s*{UNIT})?")),
    # round / tubular sections: D88.3, D1.4m, D140x4.5x2500, D75x3,25, F75 (outer diameter [x thickness [x length]])
    ("round", re.compile(rf"(?<![A-Z0-9.])[DF]\s?(\d+(?:[.,]\d+)?)((?:\s*X\s*{NUM}){{0,2}})(?:\s*{UNIT})?")),
    # sections / sheet sizes: 300x600, 50x50x2, 170x65x5x1010, KT1780x700mm
    ("section", re.compile(rf"(?<![\w.,])(?:KT\s?)?({NUM}(?:\s*X\s*{NUM}){{1,3}})(?:\s*{UNIT})?")),
    ("bar", re.compile(r"(?:Ø|\bPHI)\s*(\d{1,2})(?:\s*(?:A|@)\s*(\d{2,4}))?")),
    # L=(4700+5200)mm - a member made of several lengths
    ("length_sum", re.compile(rf"\b(L|H|DAI)\s*=\s*\(\s*({NUM}(?:\s*\+\s*{NUM})+)\s*\)(?:\s*{UNIT})?")),
    ("labeled", re.compile(rf"\b(L|H|B|R|T|DAI|CAO|RONG|DAY)\s*=\s*({NUM})(?:\s*{UNIT})?")),
    ("count", re.compile(r"\b(SL|N|SO\s+LUONG)\s*=\s*(\d+)\b")),
    ("stated_quantity", re.compile(rf"(?<![\w.,])({NUM})\s*(M2|M3)\b")),
    ("value_with_unit", re.compile(rf"(?<![\w.,=])({NUM})\s*{UNIT}")),
]
_BARE = re.compile(r"\d{2,6}(?:[.,]\d+)?")
_SPLIT_X = re.compile(r"\s*X\s*")
_LENGTH_LABELS = {"L", "H", "DAI"}


def _token_values(raws: list[str]) -> tuple[list[str | None], list[bool], bool]:
    """Parse the numbers of ONE dimension token. If another number in the same token proves that '.' or ','
    is the decimal separator (e.g. '4.10' in '6.014x4.10m'), ambiguous numbers using that separator are
    read the same way. Returns (values, ambiguous flags, resolved_from_token)."""
    parsed = [parse_number(r) for r in raws]
    decimal_seps = {r for r in (".", ",") if any(
        (raw.count(r) == 1 and raw.count("." if r == "," else ",") == 0 and not amb)
        for raw, (v, amb) in zip(raws, parsed) if v is not None and r in raw)}
    resolved = False
    values, ambs = [], []
    for raw, (v, amb) in zip(raws, parsed):
        if amb and len(decimal_seps) == 1:
            sep = next(iter(decimal_seps))
            if raw.count(sep) == 1 and raw.count("." if sep == "," else ",") == 0:
                v, amb, resolved = Decimal(raw.replace(sep, ".")), False, True
        values.append(format(v, "f") if v is not None else None)
        ambs.append(amb)
    return values, ambs, resolved


def find_dimensions(line: Line) -> list[Finding]:
    F = fold(line.text)
    taken: list[tuple[int, int]] = []
    out: list[Finding] = []
    bolt_line = bool(_BOLT_CUE.search(F))
    mixed_case = any(c.islower() for c in line.text)

    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)

    for typ, rx in _DIM_PATTERNS:
        for m in rx.finditer(F):
            if not free(m.start(), m.end()):
                continue
            raw = line.text[m.start():m.end()]
            flags: list[str] = []
            if typ in ("bolt", "bolt_d"):
                if typ == "bolt_d" and not bolt_line:
                    continue
                values, ambs, res = _token_values([m.group(1), m.group(2)])
                unit = m.group(3).lower() if m.group(3) else None
                data = {"type": "bolt", "values": values, "unit": unit, "unit_explicit": unit is not None,
                        "note": "đường kính x chiều dài bu lông"}
                base = 0.9 if unit else 0.8
            elif typ == "round":
                rest = [x for x in _SPLIT_X.split(m.group(2).strip()) if x] if m.group(2).strip() else []
                unit = m.group(3).lower() if m.group(3) else None
                first = m.group(1)
                if not rest and not unit and "." not in first and "," not in first and len(first) < 2:
                    continue  # D1, D2 ... are element marks (e.g. beam D1), not diameters
                values, ambs, res = _token_values([first] + rest)
                data = {"type": "round", "values": values, "unit": unit, "unit_explicit": unit is not None,
                        "note": "đường kính ngoài [x chiều dày [x chiều dài]]"}
                base = 0.9 if unit else 0.75
            elif typ == "section":
                values, ambs, res = _token_values(_SPLIT_X.split(m.group(1)))
                unit = m.group(2).lower() if m.group(2) else None
                data = {"type": "section", "values": values, "unit": unit, "unit_explicit": unit is not None}
                base = 0.95 if unit else 0.8
            elif typ == "bar":
                taken.append((m.start(), m.end()))
                out.append(Finding("dimension", raw, {"type": "bar", "diameter": m.group(1), "spacing": m.group(2), "unit": None,
                                   "unit_explicit": False, "note": "Ký hiệu Ø thường tính bằng mm theo quy ước; cần xác nhận"},
                                   round(0.85 * line.source_conf, 3), line, ["unit_not_stated"]))
                continue
            elif typ == "length_sum":
                values, ambs, res = _token_values(re.split(r"\s*\+\s*", m.group(2)))
                unit = m.group(3).lower() if m.group(3) else None
                data = {"type": "length_sum", "label": m.group(1), "values": values, "unit": unit, "unit_explicit": unit is not None}
                base = 0.9 if unit else 0.75
            elif typ == "labeled":
                values, ambs, res = _token_values([m.group(2)])
                unit = m.group(3).lower() if m.group(3) else None
                data = {"type": "labeled", "label": m.group(1), "values": values, "unit": unit, "unit_explicit": unit is not None}
                base = 0.95 if unit else 0.8
            elif typ == "count":
                taken.append((m.start(), m.end()))
                out.append(Finding("count", raw, {"type": "count", "label": m.group(1), "count": m.group(2)}, 0.9 * line.source_conf, line))
                continue
            elif typ == "stated_quantity":
                values, ambs, res = _token_values([m.group(1)])
                data = {"type": "stated_quantity", "values": values, "unit": m.group(2).lower(), "unit_explicit": True}
                base = 0.9
            else:
                unit_raw = line.text[m.start(2):m.end(2)]
                if mixed_case and unit_raw == "M":
                    continue  # "3M" in mixed-case text is a name/brand, metres are written "m"
                values, ambs, res = _token_values([m.group(1)])
                data = {"type": "value_with_unit", "values": values, "unit": m.group(2).lower(), "unit_explicit": True}
                base = 0.9
            taken.append((m.start(), m.end()))
            if any(ambs):
                flags.append("ambiguous_number")
                base = 0.3
            if res:
                data["separator_resolved_in_token"] = True
            if not data.get("unit_explicit"):
                flags.append("unit_not_stated")
            if (data.get("label") in _LENGTH_LABELS and data.get("unit") == "mm"
                    and any(v is not None and Decimal(v) < 10 for v in data["values"])):
                flags.append("implausible_value")  # e.g. post length "L=1,89mm" - probably metres; engineer must confirm
            out.append(Finding("dimension", raw, data, round(base * line.source_conf, 3), line, flags))
    if not out and _BARE.fullmatch(F.strip()):
        v, amb = _num(F.strip())
        flags = ["unit_not_stated"] + (["ambiguous_number"] if amb else [])
        out.append(Finding("dimension", line.text.strip(),
                           {"type": "bare_number", "values": [v], "unit": None, "unit_explicit": False},
                           round((0.3 if amb else 0.5) * line.source_conf, 3), line, flags))
    return out


_CONCRETE_CUE = re.compile(r"BE\s*TONG|\bBT\b|CONCRETE|\bMAC\b|CAP\s+DO\s+BEN")
_REFLECTIVE_CUE = re.compile(r"PHAN\s+QUANG|REFLECT")
_GUARDRAIL_CUE = re.compile(r"TON\s+(?:LUON\s+)?SONG|HO\s+LAN|GUARDRAIL")
_FENCE_CUE = re.compile(r"HANG\s+RAO|KHUNG|LUOI|FENCE")
# (category, pattern, required cue on the same line or None)
_SPEC_PATTERNS = [
    ("concrete_grade", re.compile(r"\bC\d{2}/\d{2}\b"), None),
    ("concrete_grade", re.compile(r"\b(?:B\s?\d{2}(?:[.,]5)?|M\s?\d{3})\b"), _CONCRETE_CUE),
    ("rebar_grade", re.compile(r"\b(?:CB\s?\d{3}-?[VT]?|C(?:II|III|IV)|SD\s?\d{3}|GR\s?\d{2})\b"), None),
    ("steel_grade", re.compile(r"\b(?:SS\s?400|Q\s?(?:235|345)[A-D]?|A\s?36|S\s?(?:235|275|355)(?:JR|J0|J2)?|CT\s?3[A-Z]*)\b"), None),
    ("steel_box", re.compile(rf"\b(?:THEP\s+)?(?:HOP|RHS|SHS)\s+({NUM}\s*X\s*{NUM}\s*X\s*{NUM})"), None),
    ("plate", re.compile(r"\b(?:BAN\s+MA|THEP\s+TAM|PLATE)\b|\bPL\s?(\d{1,3}(?:[.,]\d)?)\b"), None),
    # road safety (ATGT): sign codes per QCVN 41 (P.127, W.203c, R.302a, I.414, IE.453c, S.509, DP.135 ...)
    ("traffic_sign", re.compile(r"(?<![A-Z0-9.])(?:IE|DP|P|R|W|I|S)\.\s?\d{3}[A-Z]?(?:\.\d)?(?![\d.])"), None),
    ("reflective_sheeting", re.compile(r"\bMPQ\s?\d{3,4}\b"), None),
    ("reflective_sheeting", re.compile(r"\bLOAI\s+(?:XI|X|IX|VIII|VII|VI|V|IV|III|II|I)\b"), _REFLECTIVE_CUE),
    ("guardrail_type", re.compile(r"\bLOAI\s+([A-Z]-\d)\b"), _GUARDRAIL_CUE),
    ("fence_type", re.compile(r"\bB40\b"), _FENCE_CUE),
    ("steel_profile", re.compile(rf"\b([IHU])\s?(\d{{3}})(?:\s*X\s*{NUM})*\b|\b([LV])\s?(\d{{2,3}}\s*X\s*\d{{1,3}}(?:\s*X\s*\d{{1,2}})?)\b"), None),
]


def find_specs(line: Line) -> list[Finding]:
    F = fold(line.text)
    out = []
    for cat, rx, cue in _SPEC_PATTERNS:
        if cue is not None and not cue.search(F):
            continue
        for m in rx.finditer(F):
            raw = line.text[m.start():m.end()]
            data = {"category": cat, "value": re.sub(r"\s+", "", m.group(0))}
            if cat == "plate" and m.group(1):
                data["thickness"] = m.group(1).replace(",", ".")
                data["unit"] = None
            out.append(Finding("spec", raw, data, round(0.9 * line.source_conf, 3), line))
    return out


_SYMBOLS = [
    ("elevation", re.compile(r"(?<![\w.,=])([±+\-])\s?(\d{1,3}[.,]\d{3})(?!\d)")),
    ("slope", re.compile(rf"\bI\s*=\s*({NUM})\s*%")),
    ("section_marker", re.compile(r"\b(?:MAT\s+CAT|SECTION)\s+([A-Z0-9]{1,3})\s*-\s*([A-Z0-9]{1,3})\b")),
    ("detail_marker", re.compile(r"\b(?:CHI\s+TIET|DETAIL)\s+([A-Z0-9]{1,3})\b")),
]
_REFS = [
    re.compile(r"(?:XEM|THAM\s+CHIEU|SEE|REFER\s+TO|REF\.?)\s+(?:BAN\s+VE|BV|DWG\.?|DRAWING|CHI\s+TIET|DETAIL)?\s*(?:SO\s*)?[:.]?\s*([A-Z]{1,4}\s?-\s?\d{1,4}(?:[.-]\d{1,3})?)"),
    re.compile(r"\b(?:CHI\s+TIET|DETAIL)\s+[A-Z0-9]{1,3}\s*/\s*([A-Z]{1,4}-?\d{1,4})"),
]


def find_symbols(line: Line) -> list[Finding]:
    F = fold(line.text)
    out = []
    for typ, rx in _SYMBOLS:
        for m in rx.finditer(F):
            data = {"type": typ, "groups": [g for g in m.groups() if g]}
            if typ == "elevation":
                data.update(sign=m.group(1), value=m.group(2).replace(",", "."), unit=None)
            out.append(Finding("symbol", line.text[m.start():m.end()], data, round(0.8 * line.source_conf, 3), line))
    for rx in _REFS:
        for m in rx.finditer(F):
            ref = re.sub(r"\s+", "", m.group(1))
            out.append(Finding("reference", line.text[m.start():m.end()], {"ref": ref}, round(0.85 * line.source_conf, 3), line))
    return out


# ---------------------------------------------------------------- title block, scale, units
_LABELS = {
    "drawing_number": re.compile(r"(?:SO\s+HIEU\s+BAN\s+VE|KY\s+HIEU\s+BAN\s+VE|BAN\s+VE\s+SO|SO\s+BAN\s+VE|MA\s+BAN\s+VE|DRAWING\s+NO\.?|DWG\.?\s*NO\.?|SHEET\s+NO\.?)\s*[:.#]?\s*"),
    "title": re.compile(r"(?:TEN\s+BAN\s+VE|DRAWING\s+TITLE|SHEET\s+TITLE|\bTITLE)\s*[:.]?\s*"),
    "revision": re.compile(r"(?:LAN\s+SUA(?:\s+DOI)?|LAN\s+HIEU\s+CHINH|PHIEN\s+BAN|REVISION|\bREV\.?)\s*[:.]?\s*"),
    "project": re.compile(r"(?:CONG\s+TRINH|DU\s+AN|PROJECT)\s*[:.]?\s*"),
    "scale": re.compile(r"(?:TY\s+LE|SCALE|\bTL)\s*[:.]?\s*"),
    "units": re.compile(r"(?:DON\s+VI(?:\s+KICH\s+THUOC|\s+DO)?|\bUNITS?|DIMENSIONS?\s+(?:ARE\s+)?IN|KICH\s+THUOC\s+(?:GHI\s+)?(?:TINH\s+)?(?:BANG|THEO))\s*[:.]?\s*"),
}
_VALID = {
    "drawing_number": re.compile(r"[A-Z0-9][A-Z0-9 ./_-]{0,30}"),
    "revision": re.compile(r"[A-Z0-9]{1,4}\b"),
}
_SCALE_IN_TEXT = re.compile(r"(?<![\d/:.])1\s*[:/]\s*(\d{1,5})(?![\d:/])")  # after a scale label
_SCALE_UNLABELED = re.compile(r"(?<![\d/:.])1\s*:\s*(\d{1,5})(?![\d:/])")  # no label: only "1:N" (never "1/2" footers)
_NTS = re.compile(r"\bN\.?\s?T\.?\s?S\b|KHONG\s+(?:THEO\s+)?TY\s+LE")
_UNIT_VALUE = re.compile(r"\(?\s*(MM|CM|M)\b")


def _neighbour_value(label: Line, lines: list[Line]) -> Line | None:
    """Value printed right of, or just below, a label that has no inline value."""
    x0, y0, x1, y1 = label.bbox
    h = max(y1 - y0, 1)
    right = [ln for ln in lines if ln is not label and ln.bbox[0] >= x1 - 1 and abs(ln.bbox[1] - y0) < h * 0.6]
    if right:
        return min(right, key=lambda ln: ln.bbox[0])
    below = [ln for ln in lines if ln is not label and 0 < ln.bbox[1] - y1 < h * 1.8 and ln.bbox[0] < x1 and ln.bbox[2] > x0]
    return min(below, key=lambda ln: ln.bbox[1]) if below else None


def title_block(lines: list[Line]) -> dict:
    """Returns {field: {"value", "item_ids", "bbox", "confidence"}} plus scale/unit candidates and NTS flag."""
    fields: dict[str, dict] = {}
    scale_candidates: list[dict] = []
    unit_candidates: list[dict] = []
    nts: list[str] = []
    for ln in lines:
        F = fold(ln.text)
        if _NTS.search(F):
            nts.append(ln.id)
        for name, rx in _LABELS.items():
            m = rx.search(F)
            if not m or (m.start() > 0 and F[m.start() - 1].isalpha()):
                continue
            value_text, used = ln.text[m.end():].strip(" :.-"), [ln]
            if not value_text:
                nb = _neighbour_value(ln, lines)
                if nb:
                    value_text, used = nb.text.strip(" :.-"), [ln, nb]
            VF = fold(value_text)
            conf = round(0.9 * min(u.source_conf for u in used), 3)
            if name == "scale":
                for sm in _SCALE_IN_TEXT.finditer(VF):
                    scale_candidates.append({"ratio": int(sm.group(1)), "labeled": True, "item_id": ln.id, "raw": value_text, "confidence": conf})
                continue
            if name == "units":
                um = _UNIT_VALUE.match(VF)
                if um:
                    unit_candidates.append({"unit": um.group(1).lower(), "item_id": ln.id, "raw": value_text, "confidence": conf})
                continue
            if not value_text or name in fields:
                continue
            if name in _VALID:
                vm = _VALID[name].match(VF)
                if not vm:
                    continue
                value_text = value_text[:vm.end()].strip()
            xs = [u.bbox for u in used]
            fields[name] = {"value": value_text, "item_ids": [u.id for u in used], "confidence": conf,
                            "bbox": [min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs)]}
    labeled_ratios = {c["ratio"] for c in scale_candidates}
    for ln in lines:  # unlabeled "1:100" anywhere on the sheet (e.g. under detail titles)
        for sm in _SCALE_UNLABELED.finditer(fold(ln.text)):
            r = int(sm.group(1))
            if r not in labeled_ratios and not _LABELS["scale"].search(fold(ln.text)):
                scale_candidates.append({"ratio": r, "labeled": False, "item_id": ln.id, "raw": ln.text, "confidence": round(0.6 * ln.source_conf, 3)})
    return {"fields": fields, "scale_candidates": scale_candidates, "unit_candidates": unit_candidates, "nts_item_ids": nts}


def scale_status(candidates: list[dict], nts: list[str]) -> str:
    if nts and not candidates:
        return "nts_declared"
    if not candidates:
        return "not_detected"
    return "conflicting" if len({c["ratio"] for c in candidates if c["labeled"]} or {c["ratio"] for c in candidates}) > 1 else "unverified"


def units_status(candidates: list[dict]) -> str:
    if not candidates:
        return "not_detected"
    return "conflicting" if len({c["unit"] for c in candidates}) > 1 else "unverified"


# ---------------------------------------------------------------- classification
_DISCIPLINES = {
    "architectural": [r"KIEN\s+TRUC", r"ARCHITECT"],
    "structural": [r"KET\s+CAU", r"STRUCTUR", r"COT\s+THEP", r"\bMONG\b", r"\bDAM\b", r"\bCOT\b"],
    "traffic": [r"GIAO\s+THONG", r"NUT\s+GIAO", r"MAT\s+DUONG", r"\bATGT\b", r"BIEN\s+BAO", r"VACH\s+SON", r"\bROAD\b", r"TRAFFIC"],
    "infrastructure": [r"HA\s+TANG", r"THOAT\s+NUOC", r"CAP\s+NUOC", r"SAN\s+NEN", r"CONG\s+HOP", r"CONG\s+TRON", r"DRAINAGE", r"INFRASTRUCT"],
    "mep": [r"CAP\s+DIEN", r"CHIEU\s+SANG", r"\bPCCC\b", r"DIEU\s+HOA", r"\bMEP\b", r"ELECTRICAL", r"PLUMBING", r"\bHVAC\b"],
}
_PREFIX = {"KT": "architectural", "AR": "architectural", "KC": "structural", "ST": "structural", "GT": "traffic",
           "HT": "infrastructure", "TN": "infrastructure", "CN": "infrastructure"}
_VIEWS = {
    "plan": [r"MAT\s+BANG", r"\bPLAN\b"], "section": [r"MAT\s+CAT", r"\bSECTION\b"],
    "elevation": [r"MAT\s+DUNG", r"ELEVATION"], "detail": [r"CHI\s+TIET", r"\bDETAIL\b"],
    "schedule": [r"BANG\s+THONG\s+KE", r"THONG\s+KE", r"SCHEDULE", r"BANG\s+KE"],
    "profile": [r"TRAC\s+DOC", r"MAT\s+CAT\s+NGANG", r"PROFILE"], "general_notes": [r"GHI\s+CHU\s+CHUNG", r"GENERAL\s+NOTES", r"THUYET\s+MINH"],
}


def _match(table: dict[str, list[str]], text: str) -> list[str]:
    F = fold(text)
    return [k for k, pats in table.items() if any(re.search(p, F) for p in pats)]


def classify(title: str | None, number: str | None, page_text: str, has_schedule_table: bool) -> dict:
    disciplines, views = [], []
    if title:
        disciplines += [{"value": v, "basis": "title", "confidence": 0.9} for v in _match(_DISCIPLINES, title)]
        views += [{"value": v, "basis": "title", "confidence": 0.9} for v in _match(_VIEWS, title)]
    if number:
        m = re.match(r"([A-Z]{2})", fold(number))
        if m and m.group(1) in _PREFIX and _PREFIX[m.group(1)] not in [d["value"] for d in disciplines]:
            disciplines.append({"value": _PREFIX[m.group(1)], "basis": "number_prefix", "confidence": 0.6})
    if not disciplines:
        disciplines = [{"value": v, "basis": "page_text", "confidence": 0.4} for v in _match(_DISCIPLINES, page_text)]
    if has_schedule_table and "schedule" not in [v["value"] for v in views]:
        views.append({"value": "schedule", "basis": "table", "confidence": 0.7})
    return {"disciplines": disciplines, "view_types": views}


_HEADER_SYNONYMS = {
    "stt": ["STT", "TT", "NO", "NO."], "description": ["TEN", "TEN CAU KIEN", "MO TA", "DESCRIPTION", "CAU KIEN", "HANG MUC", "ITEM", "NOI DUNG"],
    "spec": ["QUY CACH", "KICH THUOC", "SPEC", "CHUNG LOAI", "VAT LIEU"], "unit": ["DVT", "DON VI", "UNIT", "DON VI TINH"],
    "quantity": ["SO LUONG", "SL", "KHOI LUONG", "KL", "QTY", "QUANTITY"], "length": ["CHIEU DAI", "DAI", "LENGTH"],
    "weight": ["TRONG LUONG", "WEIGHT", "KG"], "diameter": ["DUONG KINH", "Ø", "PHI"], "mark": ["KY HIEU", "SO HIEU", "MARK"],
}


def classify_table(rows: list[list[str]]) -> dict:
    if not rows:
        return {"header_map": {}, "table_type": "unknown"}
    header_map = {}
    for i, cell in enumerate(rows[0]):
        F = re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", fold(cell))).strip(" .:")
        for canon, syns in _HEADER_SYNONYMS.items():
            if F in syns and canon not in header_map.values():
                header_map[str(i)] = canon
                break
    useful = set(header_map.values()) & {"description", "spec", "unit", "quantity", "weight", "length", "diameter"}
    return {"header_map": header_map, "table_type": "material_schedule" if len(useful) >= 2 else "unknown"}


def notes_regions(lines: list[Line]) -> list[dict]:
    out = []
    for ln in lines:
        if not re.match(r"\s*(GHI\s+CHU|NOTES?\b)", fold(ln.text)):
            continue
        members, last = [ln], ln
        for nxt in sorted((x for x in lines if x.bbox[1] > ln.bbox[1]), key=lambda x: x.bbox[1]):
            h = max(last.bbox[3] - last.bbox[1], 1)
            if abs(nxt.bbox[0] - ln.bbox[0]) < 60 and nxt.bbox[1] - last.bbox[3] < 2.5 * h:
                members.append(nxt)
                last = nxt
        bb = [min(m.bbox[0] for m in members), min(m.bbox[1] for m in members), max(m.bbox[2] for m in members), max(m.bbox[3] for m in members)]
        out.append({"bbox": bb, "item_ids": [m.id for m in members]})
    return out


# ---------------------------------------------------------------- duplicate detection
def _iou(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", fold(s))


def duplicate_findings(lines: list[Line], dims: list[Finding]) -> list[dict]:
    out = []
    # 1. identical text drawn on top of itself (double layer / overprint) -> may be counted twice
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        by_page.setdefault(ln.page_no, []).append(ln)
    for page, ls in by_page.items():
        for i, a in enumerate(ls):
            for b in ls[i + 1:]:
                if _norm(a.text) == _norm(b.text) and _iou(a.bbox, b.bbox) > 0.5:
                    out.append({"type": "overlapping_duplicate_text", "severity": "warning", "page_no": page,
                                "text": a.text, "item_ids": [a.id, b.id]})
    # 2. repeated dimension/spec annotations (often legitimate, but each repeat may be a double count)
    groups: dict[str, list[Finding]] = {}
    for f in dims:
        if f.data.get("type") in ("section", "labeled", "bar", "value_with_unit"):
            groups.setdefault(_norm(f.raw), []).append(f)
    for key, fs in groups.items():
        if len(fs) > 1:
            out.append({"type": "repeated_annotation", "severity": "info", "text": fs[0].raw,
                        "occurrences": [{"page_no": f.line.page_no, "bbox": list(f.line.bbox), "item_id": f.line.id} for f in fs]})
    # 3. near-identical pages inside one document (sheet included twice)
    sets = {p: {_norm(ln.text) for ln in ls} for p, ls in by_page.items()}
    pages = sorted(sets)
    for i, p in enumerate(pages):
        for q in pages[i + 1:]:
            a, b = sets[p], sets[q]
            if min(len(a), len(b)) >= 5 and len(a & b) / len(a | b) >= 0.9:
                out.append({"type": "duplicate_page", "severity": "warning", "pages": [p, q],
                            "similarity": round(len(a & b) / len(a | b), 3)})
    return out


def revision_rank(rev: str | None) -> tuple | None:
    if not rev:
        return None
    r = fold(rev).strip()
    if r.isdigit():
        return (0, int(r))
    if re.fullmatch(r"[A-Z]{1,2}", r):
        return (1, len(r), r)
    m = re.fullmatch(r"([A-Z])(\d+)", r)
    return (2, m.group(1), int(m.group(2))) if m else None
