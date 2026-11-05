"""Coordinate systems (Phase 5A). Deterministic; real-world values in Decimal.

  PDF user space (points, origin bottom-left of the MediaBox, unrotated, as written in the content stream)
    -> PAGE space   = what PyMuPDF returns for drawings/text: points, origin top-left of the UNROTATED page,
                      y down, CropBox offset already applied by PyMuPDF
    -> DISPLAY space = PAGE space x page.rotation_matrix: the page as shown/rendered (all stored geometry and
                      text bboxes use this space, so overlays match rendered images; same as Phase 4 `_disp`)
    -> PAPER space  = DISPLAY points converted to millimetres on paper (1 pt = 25.4/72 mm), exact Decimal
    -> REAL space   = PAPER mm x confirmed scale ratio (1:N) -> mm in the real world -> m

PAPER -> REAL is refused unless an engineer confirmed the page scale (Phase 4 calibration); a not-to-scale page
never yields real lengths. Raster (scanned) pages have no vector geometry at all.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import pymupdf

from app.takeoff.engine import CalcError

PT_TO_MM = Decimal("25.4") / Decimal("72")  # exact ratio, kept as Decimal
COORD_DP = Decimal("0.01")  # stored coordinates: 0.01 pt (= 0.0035 mm on paper)
DEFAULT_TOLERANCE_PT = Decimal("0.5")  # snapping / duplicate tolerance on paper


def q(v, dp: Decimal = COORD_DP) -> Decimal:
    return Decimal(str(v)).quantize(dp, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PageFrame:
    """Everything needed to move between spaces for one page."""
    page_no: int
    rotation: int
    width_pt: float  # DISPLAY width
    height_pt: float
    mediabox: tuple[float, float, float, float]
    cropbox: tuple[float, float, float, float]
    matrix: tuple[float, float, float, float, float, float]  # PAGE -> DISPLAY (rotation_matrix)

    @classmethod
    def of(cls, page: "pymupdf.Page", page_no: int) -> "PageFrame":
        m = page.rotation_matrix
        return cls(page_no, page.rotation, round(page.rect.width, 2), round(page.rect.height, 2),
                   tuple(round(v, 2) for v in page.mediabox), tuple(round(v, 2) for v in page.cropbox),
                   (m.a, m.b, m.c, m.d, m.e, m.f))

    def to_display(self, x: float, y: float) -> tuple[Decimal, Decimal]:
        a, b, c, d, e, f = self.matrix
        return q(x * a + y * c + e), q(x * b + y * d + f)

    def inside(self, x: Decimal, y: Decimal, tol: Decimal = DEFAULT_TOLERANCE_PT) -> bool:
        return -tol <= x <= Decimal(str(self.width_pt)) + tol and -tol <= y <= Decimal(str(self.height_pt)) + tol

    def as_dict(self) -> dict:
        return {"rotation": self.rotation, "width_pt": self.width_pt, "height_pt": self.height_pt,
                "mediabox": list(self.mediabox), "cropbox": list(self.cropbox), "matrix": list(self.matrix),
                "space": "display_pt_top_left"}


def paper_mm(length_pt: Decimal) -> Decimal:
    return Decimal(length_pt) * PT_TO_MM


def real_mm(length_pt: Decimal, scale_ratio: int | None, scale_status: str) -> Decimal:
    """Paper length (pt) -> real length (mm). Only on an engineer-confirmed scale; never on N.T.S. pages."""
    if scale_status != "confirmed" or not scale_ratio:
        raise CalcError("scale_unconfirmed", "Tỷ lệ trang chưa được kỹ sư xác nhận – không thể đổi sang kích thước thật")
    if scale_ratio <= 0:
        raise CalcError("invalid_scale", "Tỷ lệ không hợp lệ")
    return paper_mm(length_pt) * scale_ratio


def real_m(length_pt: Decimal, scale_ratio: int | None, scale_status: str, dp: Decimal = Decimal("0.001")) -> Decimal:
    return (real_mm(length_pt, scale_ratio, scale_status) / 1000).quantize(dp, rounding=ROUND_HALF_UP)
