"""Phase 5C – text normalisation, typed values and rule-based text_type classification (no LLM).

Reuses the Phase 4B token rules (find_dimensions / find_specs / find_symbols - tuned on the real document,
incl. "3M is not 3 metres") and the 5A.1 encoding detector. The original text is never modified; the normalised
text is a separate field used only for matching.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.pdf.analysis import Line, find_dimensions, find_specs, find_symbols, fold, parse_number
from app.text.encoding import detect as detect_encoding

TEXT_TYPES = ("UNKNOWN", "DIMENSION", "LENGTH", "AREA", "COUNT", "CHAINAGE", "MATERIAL", "SPECIFICATION", "LABEL", "NOTE",
              "DETAIL_REFERENCE", "TITLE", "TABLE", "SCALE", "REVISION", "OTHER")
_TO_M = {"mm": Decimal("0.001"), "cm": Decimal("0.01"), "m": Decimal("1")}
_CHAINAGE = re.compile(r"(?<![\w.])(?:KM|K)\s*(\d{1,4})\s*\+\s*(\d{3}(?:[.,]\d+)?)(?![\d])")
_CHAINAGE_BARE = re.compile(r"(?<![\w.(=+])(\d{1,4})\s*\+\s*(\d{3}(?:[.,]\d+)?)(?![\d+])")
_SCALE = re.compile(r"(?:TY\s+LE|SCALE|\bTL)\s*[:.]?\s*1\s*[:/]\s*\d+|^\s*1\s*:\s*\d{1,5}\s*$")
_REVISION = re.compile(r"^\s*(?:LAN\s+SUA|REV(?:ISION)?\.?)\b")
_TITLE_LABEL = re.compile(r"^\s*(?:BAN\s+VE\s+SO|SO\s+BAN\s+VE|TEN\s+BAN\s+VE|CONG\s+TRINH|DU\s+AN|DRAWING\s+NO|TITLE)\b")
_PAGE_NO = re.compile(r"^\s*(?:TRANG\s+)?\d{1,4}\s*/\s*\d{1,4}\s*$|^\s*(?:TRANG|PAGE)\s+\d{1,4}\s*$")
_NOTE = re.compile(r"^\s*(?:GHI\s+CHU|NOTES?\b|\d{1,2}[.)]\s+\S)")
_DETAIL = re.compile(r"\b(?:CHI\s+TIET|DETAIL|MAT\s+CAT|SECTION)\b|(?<![A-Z0-9])([A-Z0-9]{1,2})\s*-\s*\1(?![A-Z0-9])")
_MATERIAL_CATS = {"concrete_grade", "rebar_grade", "steel_grade", "reflective_sheeting"}
_SPEC_CATS = {"steel_box", "plate", "steel_profile", "traffic_sign", "guardrail_type", "fence_type"}


@dataclass
class Classified:
    original_text: str
    normalized_text: str
    text_type: str
    values: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    encoding: dict | None = None


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFC", text or "").replace("×", "x").replace("­", "")
    s = re.sub(r"\s*=\s*", "=", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_chainage(text: str) -> list[dict]:
    """'Km12+350' -> 12350 m; 'K0+250', '0+250' accepted. Never inside 'L=(4700+5200)' expressions."""
    F = fold(normalize(text))
    out, taken = [], []
    for rx, bare in ((_CHAINAGE, False), (_CHAINAGE_BARE, True)):
        for m in rx.finditer(F):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            km, rest = m.group(1), m.group(2).replace(",", ".")
            try:
                meters = Decimal(km) * 1000 + Decimal(rest)
            except InvalidOperation:
                continue
            taken.append((m.start(), m.end()))
            out.append({"raw": normalize(text)[m.start():m.end()], "meters": str(meters), "bare": bare})
    return out


def parse_length(text: str) -> dict | None:
    """Explicit length with a unit (L=25.50m, 125,50m, 12550 mm). Bare numbers are NOT lengths."""
    for f in find_dimensions(Line("t", 0, normalize(text), (0, 0, 0, 0))):
        d = f.data
        if f.kind != "dimension" or d.get("type") not in ("labeled", "value_with_unit", "length_sum") or not d.get("unit"):
            continue
        if d.get("type") == "labeled" and d.get("label") not in ("L", "DAI", "H", "B", "R", "T", "CAO", "RONG", "DAY"):
            continue
        vals = d.get("values") or []
        upper_m = d.get("type") == "value_with_unit" and f.raw.rstrip().endswith("M") and d["unit"] == "m"
        if upper_m and fold(normalize(text)).replace(" ", "") == fold(f.raw).replace(" ", ""):
            return None  # a lone "3M" is a name/notation by default, never 3 metres
        if any(v is None for v in vals) or not vals:
            return {"raw": f.raw, "value_m": None, "unit": d["unit"], "ambiguous": True, "flags": f.flags}
        total = sum((Decimal(v) for v in vals), Decimal(0))
        return {"raw": f.raw, "value_m": str(total * _TO_M[d["unit"]]), "value": str(total), "unit": d["unit"],
                "label": d.get("label"), "ambiguous": upper_m, "flags": f.flags + (["unit_case_ambiguous"] if upper_m else []),
                "decimal_comma": "," in f.raw and "." not in f.raw}
    return None


def classify(text: str, *, in_table: bool = False, in_title_block: bool = False) -> Classified:
    norm = normalize(text)
    F = fold(norm)
    enc = detect_encoding(text)
    flags, values = [], {}
    c = Classified(text, norm, "UNKNOWN", values, flags, enc.as_dict() if enc.suspicious else None)
    if enc.suspicious:
        flags.append("legacy_encoding" if enc.confidence >= 0.7 else "ENCODING_UNKNOWN")
    if not norm:
        return c
    if in_table:
        c.text_type = "TABLE"
        return c
    if _PAGE_NO.match(F):
        c.text_type, values["page_number"] = "OTHER", True
        flags.append("page_number")
        return c
    if _SCALE.search(F):
        c.text_type = "SCALE"
        return c
    if _REVISION.match(F):
        c.text_type = "REVISION"
        return c
    if in_title_block or _TITLE_LABEL.match(F):
        c.text_type = "TITLE"
        return c
    if enc.suspicious and not re.search(r"\d", norm):
        return c  # garbled legacy text: no semantic classification without a verified conversion (UNKNOWN)
    if re.fullmatch(r"\d+(?:[.,]\d+)?\s*M", norm):  # lone "3M": brand/model/notation by default, never a length
        c.text_type = "OTHER"
        flags.append("brand_or_notation_possible")
        return c
    ch = parse_chainage(norm)
    if ch:
        c.text_type, values["chainage"] = "CHAINAGE", ch
        return c
    if _DETAIL.search(F):
        refs = [f.data for f in find_symbols(Line("t", 0, norm, (0, 0, 0, 0)))]
        c.text_type, values["references"] = "DETAIL_REFERENCE", refs
        return c
    length = parse_length(norm)
    if length:
        c.text_type, values["length"] = "LENGTH", length
        if length["ambiguous"]:
            flags.extend(x for x in (length.get("flags") or ["ambiguous_number"]) if x not in flags)
        return c
    dims = [f for f in find_dimensions(Line("t", 0, norm, (0, 0, 0, 0)))]
    if any(f.data.get("type") == "stated_quantity" and f.data.get("unit") == "m2" for f in dims):
        c.text_type, values["area"] = "AREA", next(f.data for f in dims if f.data.get("type") == "stated_quantity")
        return c
    if any(f.kind == "count" for f in dims):
        c.text_type, values["count"] = "COUNT", next(f.data for f in dims if f.kind == "count")
        return c
    if _NOTE.match(F):
        c.text_type = "NOTE"
        return c
    specs = find_specs(Line("t", 0, norm, (0, 0, 0, 0)))
    real_dims = [f for f in dims if f.data.get("type") != "bare_number"]
    if real_dims:
        values["dimensions"] = [f.data | {"raw": f.raw} for f in real_dims]
    if specs:  # a material/profile with its size ("Thép hộp 50x50x2", "Thép CB300-V D12") is a specification, not a dimension
        cats = {f.data["category"] for f in specs}
        c.text_type = "MATERIAL" if cats & _MATERIAL_CATS and not cats & _SPEC_CATS and not real_dims else "SPECIFICATION"
        values["specs"] = [f.data | {"raw": f.raw} for f in specs]
        return c
    if real_dims:
        c.text_type = "DIMENSION"
        return c
    letters = [ch for ch in norm if ch.isalpha()]
    words = re.findall(r"\w{2,}", norm)
    if len(words) >= 2 and not re.search(r"\d", F) and letters and sum(ch.isupper() for ch in letters) / len(letters) >= 0.8:
        c.text_type = "LABEL"
        return c
    if re.search(r"(?<![\w.,])\d+(?:[.,]\d+)?\s*M\b", norm):
        flags.append("brand_or_notation_possible")  # e.g. "3M": never a length by default
    c.text_type = "OTHER" if re.search(r"\w", norm) else "UNKNOWN"
    return c
