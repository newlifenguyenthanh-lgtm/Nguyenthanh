"""PDF extraction (read-only). Works on bytes; never writes to the source file.

Coordinates: every bbox is in PDF points (1/72 inch) in the DISPLAYED page space (rotation applied,
origin top-left) - the same space as the rendered page image, so overlays line up.
"""
import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

from app.pdf.ocr import OcrEngine

BBox = tuple[float, float, float, float]


class PdfError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class TextLine:
    page_no: int
    text: str
    bbox: BBox
    source: str  # "text" (embedded vector text) | "ocr"
    confidence: float | None  # 0-1; None for embedded text (exact)
    direction: tuple[float, float] = (1.0, 0.0)
    font_size: float | None = None


@dataclass
class TableResult:
    page_no: int
    bbox: BBox
    rows: list[list[str]]
    cells: list[list[BBox | None]] = field(default_factory=list)  # per-cell bbox (displayed space) for traceability


@dataclass
class PageResult:
    page_no: int
    width: float
    height: float
    rotation: int
    kind: str  # vector | scanned | mixed | vector_no_text | empty
    text_chars: int
    image_coverage: float
    vector_paths: int
    ocr_used: bool = False
    ocr_engine: str | None = None
    ocr_mean_confidence: float | None = None
    lines: list[TextLine] = field(default_factory=list)
    tables: list[TableResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    page_count: int
    metadata: dict
    pages: list[PageResult]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def _disp(rect, page) -> BBox:
    r = pymupdf.Rect(rect) * page.rotation_matrix
    r.normalize()
    return (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))


def _image_coverage(page) -> float:
    area = page.rect.width * page.rect.height or 1
    total = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if not r.is_empty:
            total += r.width * r.height
    return round(min(1.0, total / area), 3)


def _cell_text(cell, words) -> str:
    """Rebuild cell text from word positions (find_tables' own text can scramble glyph order in some fonts)."""
    if cell is None:
        return ""
    x0, y0, x1, y1 = cell
    inside = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    inside.sort(key=lambda w: (round(w[3]), w[0]))
    return clean(" ".join(w[4] for w in inside))


def _classify(text_chars: int, coverage: float, paths: int, min_chars: int) -> str:
    if text_chars >= min_chars:
        return "mixed" if coverage >= 0.5 else "vector"
    if coverage >= 0.5:
        return "scanned"
    return "vector_no_text" if paths else "empty"


def extract_pdf(data: bytes, ocr: OcrEngine | None = None, *, min_text_chars: int = 20, ocr_dpi: int = 200,
                max_ocr_side_px: int = 6000, max_pages: int = 200, ocr_mixed: bool = False) -> ExtractionResult:
    if not data.startswith(b"%PDF"):
        raise PdfError("not_pdf", "Tệp không phải PDF")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001 - PyMuPDF raises several types for corrupt files
        raise PdfError("corrupt_pdf", f"Không mở được PDF: {e}") from None
    with doc:
        if doc.needs_pass:
            raise PdfError("encrypted_pdf", "PDF được bảo vệ bằng mật khẩu")
        if doc.page_count > max_pages:
            raise PdfError("too_many_pages", f"PDF có {doc.page_count} trang, vượt giới hạn {max_pages}")
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        pages = [_page(doc[i], i + 1, ocr, min_text_chars, ocr_dpi, max_ocr_side_px, ocr_mixed) for i in range(doc.page_count)]
        return ExtractionResult(doc.page_count, meta, pages)


def _page(page, page_no, ocr, min_chars, ocr_dpi, max_side, ocr_mixed) -> PageResult:
    lines: list[TextLine] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for ln in block["lines"]:
            text = clean("".join(s["text"] for s in ln["spans"]))
            if text:
                lines.append(TextLine(page_no, text, _disp(ln["bbox"], page), "text", None,
                                      tuple(round(v, 3) for v in ln["dir"]),
                                      round(max(s["size"] for s in ln["spans"]), 2)))
    chars = sum(len(t.text) for t in lines)
    coverage = _image_coverage(page)
    paths = len(page.get_drawings())
    kind = _classify(chars, coverage, paths, min_chars)
    res = PageResult(page_no, round(page.rect.width, 2), round(page.rect.height, 2), page.rotation, kind,
                     chars, coverage, paths, lines=lines)

    if kind in ("vector", "mixed"):
        try:
            words = page.get_text("words", sort=True)
            for t in page.find_tables().tables:
                rows = [[_cell_text(c, words) for c in r.cells] for r in t.rows]
                cells = [[_disp(c, page) if c else None for c in r.cells] for r in t.rows]
                if any(any(c for c in r) for r in rows):
                    res.tables.append(TableResult(page_no, _disp(t.bbox, page), rows, cells))
        except Exception as e:  # noqa: BLE001
            res.warnings.append(f"table_detection_failed: {e}")

    needs_ocr = kind == "scanned" or (kind == "mixed" and ocr_mixed)
    if needs_ocr and ocr is None:
        res.warnings.append("ocr_unavailable")
    elif needs_ocr:
        dpi = int(min(ocr_dpi, max_side * 72 / max(page.rect.width, page.rect.height)))
        if dpi < ocr_dpi:
            res.warnings.append(f"ocr_dpi_reduced_to_{dpi}")
        png = page.get_pixmap(dpi=dpi).tobytes("png")
        k = 72 / dpi
        ocr_lines = [ln for ln in ocr.recognize(png) if clean(ln.text)]
        for ln in ocr_lines:
            x0, y0, x1, y1 = ln.bbox_px
            res.lines.append(TextLine(page_no, clean(ln.text), (round(x0 * k, 2), round(y0 * k, 2), round(x1 * k, 2), round(y1 * k, 2)),
                                      "ocr", round(ln.confidence / 100, 3)))
        res.ocr_used, res.ocr_engine = True, ocr.name
        if ocr_lines:
            res.ocr_mean_confidence = round(sum(ln.confidence for ln in ocr_lines) / len(ocr_lines) / 100, 3)
        else:
            res.warnings.append("ocr_found_no_text")
    if kind == "mixed" and not ocr_mixed:
        res.warnings.append("raster_content_not_ocr")  # large image area on a text page: may hide information
    return res


def render_page_png(data: bytes, page_no: int, dpi: int = 100, max_side_px: int = 4000) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not 1 <= page_no <= doc.page_count:
            raise PdfError("page_out_of_range", "Trang không tồn tại")
        page = doc[page_no - 1]
        dpi = int(min(dpi, max_side_px * 72 / max(page.rect.width, page.rect.height)))
        return page.get_pixmap(dpi=max(dpi, 10)).tobytes("png")
