import hashlib

import pytest

from app.pdf.extract import PdfError, extract_pdf, render_page_png
from app.pdf.ocr import OcrLine, TesseractOcr
from tests import pdf_factory as pf

needs_tesseract = pytest.mark.skipif(not TesseractOcr.available(), reason="tesseract binary not installed")


class FakeOcr:
    """Deterministic OCR stand-in: tests the pipeline (coordinates, confidence) independently of Tesseract."""
    name = "fake-ocr"

    def __init__(self, lines):
        self.lines, self.calls = lines, 0

    def recognize(self, png):
        self.calls += 1
        assert png.startswith(b"\x89PNG")
        return self.lines


def texts(page):
    return [ln.text for ln in page.lines]


def test_vector_text_with_coordinates_and_metadata():
    r = extract_pdf(pf.vector_pdf())
    assert r.page_count == 1
    p = r.pages[0]
    assert p.kind == "vector" and not p.ocr_used and p.vector_paths > 0
    assert (p.width, p.height) == (1190, 842)
    line = next(ln for ln in p.lines if ln.text.startswith("THÉP HỘP" if pf.VIETNAMESE else "THEP HOP"))
    x0, y0, x1, y1 = line.bbox
    assert 700 < x0 < 730 and 120 < y0 < 150 and x1 > x0 and y1 > y0
    assert line.source == "text" and line.confidence is None
    assert any("6000" == t for t in texts(p))
    vertical = next(ln for ln in p.lines if ln.text == "3500")
    assert vertical.direction != (1.0, 0.0)  # rotated dimension text recorded


def test_vector_table_extraction():
    p = extract_pdf(pf.vector_pdf()).pages[0]
    assert len(p.tables) == 1
    rows = p.tables[0].rows
    assert rows[0][0] == "STT" and rows[1][1].startswith("D") and rows[2][4] == "180,86"
    x0, y0, x1, y1 = p.tables[0].bbox
    assert (round(x0), round(y0)) == (60, 600)


def test_rotated_page_bboxes_in_displayed_space():
    p = extract_pdf(pf.vector_pdf(rotation=90)).pages[0]
    assert p.rotation == 90 and (p.width, p.height) == (842, 1190)
    for ln in p.lines:
        x0, y0, x1, y1 = ln.bbox
        assert 0 <= x0 <= x1 <= p.width + 1 and 0 <= y0 <= y1 <= p.height + 1


def test_scanned_page_detected_and_ocr_pipeline_with_fake_engine():
    fake = FakeOcr([OcrLine("BẢN VẼ SỐ: KC-01", 91.0, (2000, 1800, 2400, 1840)), OcrLine("  ", 50, (0, 0, 1, 1))])
    p = extract_pdf(pf.scanned_pdf(), ocr=fake, ocr_dpi=200).pages[0]
    assert p.kind == "scanned" and p.text_chars == 0 and p.image_coverage > 0.95
    assert p.ocr_used and p.ocr_engine == "fake-ocr" and fake.calls == 1
    assert len(p.lines) == 1  # blank OCR lines dropped
    ln = p.lines[0]
    assert ln.source == "ocr" and ln.confidence == 0.91
    assert ln.bbox == (720.0, 648.0, 864.0, 662.4)  # px * 72/200


def test_scanned_page_without_ocr_is_flagged_not_silently_empty():
    p = extract_pdf(pf.scanned_pdf(), ocr=None).pages[0]
    assert p.kind == "scanned" and "ocr_unavailable" in p.warnings and p.lines == []


def test_large_page_reduces_ocr_dpi():
    fake = FakeOcr([])
    p = extract_pdf(pf.scanned_pdf(dpi=72), ocr=fake, ocr_dpi=300, max_ocr_side_px=1000).pages[0]
    assert any(w.startswith("ocr_dpi_reduced_to_") for w in p.warnings) and "ocr_found_no_text" in p.warnings


@needs_tesseract
def test_real_tesseract_ocr_on_scanned_drawing():
    p = extract_pdf(pf.scanned_pdf(dpi=200), ocr=TesseractOcr(), ocr_dpi=300).pages[0]
    joined = " | ".join(texts(p)).upper()
    assert "KC-01" in joined
    assert "50X50X2" in joined.replace(" ", "")
    assert all(0 <= ln.confidence <= 1 for ln in p.lines)
    kc = next(ln for ln in p.lines if "KC-01" in ln.text.upper())
    x0, y0, _, _ = kc.bbox
    assert 820 < x0 < 1000 and 700 < y0 < 760  # located inside the title block area


def test_mixed_document_pages_classified_independently():
    r = extract_pdf(pf.mixed_doc(), ocr=FakeOcr([OcrLine("KC-02", 80, (10, 10, 50, 20))]))
    assert [p.kind for p in r.pages] == ["vector", "scanned"]
    assert not r.pages[0].ocr_used and r.pages[1].ocr_used


@pytest.mark.parametrize("data,code", [(b"hello", "not_pdf"), (b"%PDF-1.4 garbage", "corrupt_pdf")])
def test_invalid_inputs(data, code):
    with pytest.raises(PdfError) as e:
        extract_pdf(data)
    assert e.value.code == code


def test_encrypted_and_page_limit():
    with pytest.raises(PdfError) as e:
        extract_pdf(pf.encrypted_pdf())
    assert e.value.code == "encrypted_pdf"
    with pytest.raises(PdfError) as e:
        extract_pdf(pf.mixed_doc(), max_pages=1)
    assert e.value.code == "too_many_pages"


def test_extraction_and_rendering_never_modify_input():
    data = pf.vector_pdf()
    before = hashlib.sha256(data).hexdigest()
    extract_pdf(data)
    png = render_page_png(data, 1, dpi=50)
    assert png.startswith(b"\x89PNG") and hashlib.sha256(data).hexdigest() == before
    with pytest.raises(PdfError):
        render_page_png(data, 2)
