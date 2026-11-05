"""Phase 5B – deterministic measurement engine (pure functions, Decimal only, no LLM).

Inputs are stored primitives (DISPLAY points). Paper values are exact Decimal arithmetic on stored coordinates;
real values use ONE engineer-confirmed scale: a confirmed scale region that contains every measured primitive,
otherwise the page's confirmed calibration. Mixed scales, unconfirmed or N.T.S. scales -> refused, never guessed.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.geometry.coords import PT_TO_MM
from app.takeoff.engine import CalcError

Pt = tuple[Decimal, Decimal]
KINDS = ("length", "perimeter", "area", "count", "distance", "spacing")
REAL_DP = {"length": Decimal("0.001"), "perimeter": Decimal("0.001"), "distance": Decimal("0.001"),
           "spacing": Decimal("0.001"), "area": Decimal("0.0001"), "count": Decimal("1")}


@dataclass(frozen=True)
class Prim:
    id: str
    kind: str
    points: list[Pt]
    closed: bool
    length_pt: Decimal | None
    area_pt2: Decimal | None
    bbox: tuple[Decimal, Decimal, Decimal, Decimal]


@dataclass(frozen=True)
class ScaleRegion:
    id: str
    bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    ratio: int


@dataclass
class ScaleChoice:
    ratio: int
    source: str  # "region:<id>" | "page"


@dataclass
class Result:
    kind: str
    value_paper: Decimal  # pt, pt² or count
    paper_unit: str
    value_real: Decimal | None
    real_unit: str | None
    scale: ScaleChoice | None
    formula: str
    details: dict = field(default_factory=dict)


def _contains(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def choose_scale(prims: list[Prim], regions: list[ScaleRegion], page_ratio: int | None, page_status: str) -> ScaleChoice:
    """Confirmed region containing ALL primitives (smallest wins) > page calibration. Anything else is refused."""
    containing = [r for r in regions if all(_contains(r.bbox, p.bbox) for p in prims)]
    touching = [r for r in regions if any(_overlaps(r.bbox, p.bbox) for p in prims)]
    if containing:
        best = min(containing, key=lambda r: (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]))
        others = {r.ratio for r in touching if r.id != best.id and not _contains(r.bbox, best.bbox)}
        if others - {best.ratio}:
            raise CalcError("scale_ambiguous", "Đối tượng nằm trên nhiều vùng tỷ lệ khác nhau – cần kỹ sư xác định")
        return ScaleChoice(best.ratio, f"region:{best.id}")
    if {r.ratio for r in touching}:
        raise CalcError("scale_ambiguous", "Đối tượng nằm một phần trong vùng tỷ lệ riêng – cần kỹ sư xác định")
    if page_status == "confirmed" and page_ratio:
        return ScaleChoice(page_ratio, "page")
    raise CalcError("scale_unconfirmed", "Chưa có tỷ lệ được kỹ sư xác nhận cho vùng này")


def _centroid(p: Prim) -> Pt:
    n = Decimal(len(p.points))
    return sum((x for x, _ in p.points), Decimal(0)) / n, sum((y for _, y in p.points), Decimal(0)) / n


def _dist(a: Pt, b: Pt) -> Decimal:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2).sqrt()


def _paper(kind: str, prims: list[Prim]) -> tuple[Decimal, str, str, dict]:
    if not prims:
        raise CalcError("no_geometry", "Chưa chọn đối tượng hình học")
    if kind in ("length", "perimeter"):
        if kind == "perimeter" and not all(p.closed for p in prims):
            raise CalcError("not_closed", "Chu vi chỉ đo được trên hình khép kín")
        if kind == "length" and any(p.length_pt is None for p in prims):
            raise CalcError("no_length", "Có đối tượng không đo được chiều dài")
        v = sum((p.length_pt for p in prims), Decimal(0))
        return v, "pt", " + ".join(f"{p.length_pt}" for p in prims) + " pt", {"parts": [str(p.length_pt) for p in prims]}
    if kind == "area":
        if not all(p.closed and p.area_pt2 is not None for p in prims):
            raise CalcError("not_closed", "Diện tích chỉ đo được trên hình khép kín")
        v = sum((p.area_pt2 for p in prims), Decimal(0))
        return v, "pt2", " + ".join(f"{p.area_pt2}" for p in prims) + " pt²", {"parts": [str(p.area_pt2) for p in prims]}
    if kind == "count":
        return Decimal(len(prims)), "count", f"đếm {len(prims)} đối tượng", {}
    if kind == "distance":
        if len(prims) != 2:
            raise CalcError("need_two", "Khoảng cách cần đúng 2 đối tượng")
        a, b = _centroid(prims[0]), _centroid(prims[1])
        v = _dist(a, b)
        return v, "pt", "khoảng cách tâm–tâm", {"from": [str(x) for x in a], "to": [str(x) for x in b]}
    if kind == "spacing":
        if len(prims) < 3:
            raise CalcError("need_three", "Bước lặp cần ít nhất 3 đối tượng")
        cs = [_centroid(p) for p in prims]
        horiz = (max(c[0] for c in cs) - min(c[0] for c in cs)) >= (max(c[1] for c in cs) - min(c[1] for c in cs))
        cs.sort(key=lambda c: c[0] if horiz else c[1])
        gaps = [_dist(cs[i], cs[i + 1]) for i in range(len(cs) - 1)]
        mean = sum(gaps, Decimal(0)) / len(gaps)
        spread = max(gaps) - min(gaps)
        return mean, "pt", f"trung bình {len(gaps)} khoảng", {"gaps_pt": [str(g.quantize(Decimal('0.01'))) for g in gaps],
                                                              "spread_pt": str(spread.quantize(Decimal('0.01'))),
                                                              "uniform": spread <= mean * Decimal("0.02")}
    raise CalcError("unknown_kind", f"Loại phép đo không hợp lệ: {kind}")


def measure(kind: str, prims: list[Prim], regions: list[ScaleRegion], page_ratio: int | None, page_status: str) -> Result:
    v, unit, formula, details = _paper(kind, prims)
    if kind == "count":
        return Result(kind, v, "count", v, "count", None, formula, details)
    try:
        scale = choose_scale(prims, regions, page_ratio, page_status)
    except CalcError as e:
        return Result(kind, v, unit, None, None, None, formula, {**details, "real_refused": e.code, "real_reason": str(e)})
    k = PT_TO_MM / 1000 * scale.ratio  # pt -> m
    real = (v * k * k if kind == "area" else v * k).quantize(REAL_DP[kind], rounding=ROUND_HALF_UP)
    return Result(kind, v, unit, real, "m2" if kind == "area" else "m", scale,
                  f"{formula} × 25,4/72 mm × 1:{scale.ratio}" + (" (bình phương)" if kind == "area" else ""), details)
