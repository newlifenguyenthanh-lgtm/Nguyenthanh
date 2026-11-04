import hashlib
from pathlib import Path

import pytest

from app.pdf.ocr import TesseractOcr
from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr


@pytest.fixture()
def a(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def test_process_vector_pdf_persists_pages_items_and_task(env, a):
    doc = upload(env, a, pf.vector_pdf())
    r = process(env, a, doc["id"])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "processed" and d["page_count"] == 1 and d["version_no"] == 1
    full = env.get(f"{B}/drawings/{d['id']}", headers=a).json()
    p = full["pages"][0]
    assert p["kind"] == "vector" and p["width_pt"] == 1190 and not p["ocr_used"]
    assert full["item_counts"]["table"] == 1 and full["item_counts"]["text"] >= 10
    items = env.get(f"{B}/drawings/{d['id']}/items?kind=text&q=6000", headers=a).json()
    assert any(i["text"] == "6000" for i in items)
    assert all(len(i["bbox"]) == 4 and i["page_no"] == 1 and i["source"] == "text" for i in items)
    table = env.get(f"{B}/drawings/{d['id']}/items?kind=table", headers=a).json()[0]
    assert table["data"]["rows"][2][4] == "180,86"
    # AI task mirrors the processing for the virtual office
    tasks = env.get(f"{B}/ai-tasks?department=engineering_qs", headers=a).json()
    assert tasks[0]["agent_key"] == "pdf_drawing" and tasks[0]["status"] == "completed"
    assert "1 trang" in tasks[0]["output_summary"]


def test_scanned_page_uses_ocr_with_confidence(env, a):
    doc = upload(env, a, pf.mixed_doc())
    d = process(env, a, doc["id"]).json()
    pages = env.get(f"{B}/drawings/{d['id']}", headers=a).json()["pages"]
    assert [p["kind"] for p in pages] == ["vector", "scanned"]
    assert pages[1]["ocr_used"] and pages[1]["ocr_engine"] == "fake-ocr" and pages[1]["ocr_mean_confidence"] == 0.703
    ocr_items = env.get(f"{B}/drawings/{d['id']}/items?page=2", headers=a).json()
    assert {i["source"] for i in ocr_items} == {"ocr"} and ocr_items[0]["confidence"] is not None


def test_scanned_without_ocr_flags_warning(env, monkeypatch):
    use_ocr(monkeypatch, None)
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, pf.scanned_pdf())["id"]).json()
    page = env.get(f"{B}/drawings/{d['id']}", headers=a).json()["pages"][0]
    assert d["status"] == "processed" and page["kind"] == "scanned" and "ocr_unavailable" in page["warnings"]


@pytest.mark.skipif(not TesseractOcr.available(), reason="tesseract not installed")
def test_real_ocr_end_to_end(env, monkeypatch):
    use_ocr(monkeypatch, TesseractOcr())
    a = login(env, "admin@a.test", "pw-admin-1")
    d = process(env, a, upload(env, a, pf.scanned_pdf())["id"]).json()
    items = env.get(f"{B}/drawings/{d['id']}/items?q=KC-01", headers=a).json()
    assert items and items[0]["source"] == "ocr" and 0 < items[0]["confidence"] <= 1


def test_invalid_pdf_fails_task_with_error(env, a):
    d = process(env, a, upload(env, a, b"not a pdf at all", name="x.pdf")["id"]).json()
    assert d["status"] == "failed" and d["error_code"] == "not_pdf"
    task = env.get(f"{B}/ai-tasks?department=engineering_qs", headers=a).json()[0]
    assert task["status"] == "error" and "PDF" in task["error_message"]
    office = env.get(f"{B}/office/departments/engineering_qs", headers=a).json()
    assert office["status"] == "error"
    # a failed run may be retried
    assert process(env, a, d["document_id"]).status_code == 201


def test_duplicates_and_revisions(env, a):
    data = pf.vector_pdf()
    doc1 = upload(env, a, data, title="A")
    d1 = process(env, a, doc1["id"]).json()
    assert process(env, a, doc1["id"]).status_code == 409  # same version already processed
    doc2 = upload(env, a, data, title="B (copy)")
    d2 = process(env, a, doc2["id"]).json()
    assert d2["duplicate_of_drawing_id"] == d1["id"]
    # new revision of the same document = new version, explicitly linked
    env.post(f"{B}/documents/{doc1['id']}/versions", data={"note": "Rev B"},
             files={"file": ("kc.pdf", pf.vector_pdf(rev="B"), "application/pdf")}, headers=a)
    d3 = process(env, a, doc1["id"]).json()
    assert d3["version_no"] == 2 and d3["document_id"] == doc1["id"] and d3["duplicate_of_drawing_id"] is None
    assert d3["document_version_id"] != d1["document_version_id"]
    assert process(env, a, doc1["id"], version_no=1).status_code == 409
    assert process(env, a, doc1["id"], version_no=9).status_code == 404


def test_page_image_and_original_untouched(env, a, tmp_path):
    data = pf.vector_pdf()
    doc = upload(env, a, data)
    d = process(env, a, doc["id"]).json()
    img = env.get(f"{B}/drawings/{d['id']}/pages/1/image?dpi=50", headers=a)
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert env.get(f"{B}/drawings/{d['id']}/pages/3/image", headers=a).status_code == 404
    stored = env.get(f"{B}/documents/{doc['id']}/versions/1/download", headers=a).content
    assert hashlib.sha256(stored).hexdigest() == hashlib.sha256(data).hexdigest() == d["sha256"]


def test_permissions_and_company_isolation(env, a):
    b = login(env, "admin@b.test", "pw-admin-2")
    v = login(env, "viewer@a.test", "pw-x")
    doc = upload(env, a, pf.vector_pdf())
    assert process(env, v, doc["id"]).status_code == 403
    d = process(env, a, doc["id"]).json()
    assert env.get(f"{B}/drawings", headers=v).status_code == 200
    assert process(env, b, doc["id"]).status_code == 404
    assert env.get(f"{B}/drawings", headers=b).json() == []
    for path in ("", "/items", "/pages/1/image"):
        assert env.get(f"{B}/drawings/{d['id']}{path}", headers=b).status_code == 404
