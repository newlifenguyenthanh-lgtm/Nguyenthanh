import io
import shutil
import subprocess
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest

from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, make_boq, processed_drawing, use_ocr

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


@pytest.fixture()
def ctx(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    qs = login(env, "qs_engineer@a.test", "pw-x")
    pid = env.post(f"{B}/projects", json={"code": "NX-01", "name": "Nhà xưởng mẫu"}, headers=login(env, "admin@a.test", "pw-admin-1")).json()["id"]
    d = processed_drawing(env, qs)
    boq = make_boq(env, qs, [d["id"]], project_id=pid, rules={"waste": {"steel_box": "0.03"}}).json()
    # accept computed items, reject the schedule duplicates
    for i in boq["items"]:
        dec = "accept" if i["module"] and not i["has_blocking"] else "reject"
        env.post(f"{B}/boqs/{boq['id']}/items/{i['id']}/review", json={"decision": dec, "note": "trùng bảng thống kê"}, headers=qs)
    return {"qs": qs, "dir": login(env, "director@a.test", "pw-x"), "viewer": login(env, "viewer@a.test", "pw-x"),
            "boq": env.get(f"{B}/boqs/{boq['id']}", headers=qs).json(), "drawing": d, "project_id": pid}


def export(env, ctx, who="qs"):
    return env.post(f"{B}/boqs/{ctx['boq']['id']}/exports", headers=ctx[who])


def workbook(env, ctx, exp, who="qs"):
    r = env.get(f"{B}/boq-exports/{exp['id']}/download", headers=ctx[who])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    return r.content


def test_export_structure_traceability_and_formulas(env, ctx):
    r = export(env, ctx)
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["boq_status"] == "draft" and exp["boq_version_no"] == 1 and exp["filename"].endswith(".xlsx") and "_NHAP_" in exp["filename"]
    assert exp["project_id"] == ctx["project_id"] and exp["item_count"] == 6
    data = workbook(env, ctx, exp)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Tổng hợp", "BOQ", "Tính chi tiết", "Truy vết nguồn"]
    s = wb["Tổng hợp"]
    assert "BẢN NHÁP" in s["A3"].value
    boq = wb["BOQ"]
    headers = [c.value for c in boq[3]]
    assert headers[:10] == ["STT", "Danh mục", "Mô tả công việc / cấu kiện", "Quy cách", "ĐVT", "Khối lượng", "Công thức / căn cứ tính",
                            "Bản vẽ", "Trang", "Vùng trên trang (pt: x0, y0, x1, y1)"]
    rows = {r[14].value: r for r in boq.iter_rows(min_row=4) if r[14].value}
    for it in ctx["boq"]["items"]:
        row = rows[it["id"]]
        assert row[0].value == it["item_no"] and row[7].value == "KC-01" and row[8].value == 1
        assert row[9].value == ", ".join(f"{v:.1f}" for v in it["bbox"])
        if it["quantity"] is not None:
            assert str(row[5].value).startswith("='Tính chi tiết'!B")
    beam = next(it for it in ctx["boq"]["items"] if it["module"] == "concrete_prism")
    assert rows[beam["id"]][4].value == "m³" and rows[beam["id"]][11].value == "Chấp nhận"
    calc_formulas = [c.value for row in wb["Tính chi tiết"].iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert any(f.startswith("=ROUND(") for f in calc_formulas) and any("PI()/4" in f for f in calc_formulas)
    sums = [c.value for row in s.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUMIFS(")]
    assert sums and all('"Chấp nhận"' in f for f in sums)
    manual = env.post(f"{B}/boqs/{ctx['boq']['id']}/items", json={"category": "other", "description": "Bulông M20", "quantity": "48",
                                                                  "stated_unit": "bộ"}, headers=ctx["qs"]).json()
    wb2 = openpyxl.load_workbook(io.BytesIO(workbook(env, ctx, export(env, ctx).json())))
    row = next(r for r in wb2["BOQ"].iter_rows(min_row=4) if r[14].value == manual["id"])
    assert row[7].value == "Kỹ sư nhập" and row[8].value is None and row[10].value == "Kỹ sư nhập"
    trace = wb["Truy vết nguồn"]
    assert trace["E3"].value == ctx["drawing"]["sha256"]
    texts = [r[4].value for r in trace.iter_rows(min_row=6) if r[4].value]
    assert any("300x600" in t for t in texts)


@pytest.mark.skipif(not SOFFICE, reason="LibreOffice not installed")
def test_formula_integrity_recalculated_by_libreoffice(env, ctx, tmp_path):
    exp = export(env, ctx).json()
    src = tmp_path / "boq.xlsx"
    src.write_bytes(workbook(env, ctx, exp))
    out = tmp_path / "out"
    subprocess.run([SOFFICE, f"-env:UserInstallation=file://{tmp_path}/lo-profile", "--headless", "--calc",
                    "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)],
                   check=True, capture_output=True, timeout=180)
    wb = openpyxl.load_workbook(out / "boq.xlsx", data_only=True)
    rows = {r[14].value: r for r in wb["BOQ"].iter_rows(min_row=4) if r[14].value}
    checked = 0
    for it in ctx["boq"]["items"]:
        if it["quantity"] is None:
            continue
        excel_value = D(str(rows[it["id"]][5].value)).quantize(D("0.0001"))
        assert excel_value == D(it["quantity"]), (it["description"], excel_value, it["quantity"])
        checked += 1
    assert checked == 6
    summary = {(r[0].value, r[1].value): r[2].value for r in wb["Tổng hợp"].iter_rows(min_row=1) if isinstance(r[2].value, (int, float))}
    unit_vi = {"m3": "m³", "kg": "kg"}
    cat_vi = {"concrete": "Bê tông", "rebar": "Cốt thép", "steel_box": "Thép hộp", "plate": "Bản mã / thép tấm"}
    for t in ctx["boq"]["totals"]:
        key = (cat_vi[t["category"]], unit_vi[t["unit"]])
        assert D(str(summary[key])).quantize(D("0.0001")) == D(t["accepted"]), key
    box = next(it for it in ctx["boq"]["items"] if it["module"] == "steel_box_hollow")
    assert box["quantity"] == "186.2900"  # 180.864 * 1.03 = 186.28992 -> 186.290 (waste rule applied in both engines)


def test_export_permissions_history_and_isolation(env, ctx):
    assert export(env, ctx, "viewer").status_code == 403  # drafts only by BOQ editors
    first = export(env, ctx).json()
    base = f"{B}/boqs/{ctx['boq']['id']}"
    env.post(f"{base}/submit", json={"note": ""}, headers=ctx["qs"])
    env.post(f"{base}/decision", json={"decision": "approve"}, headers=ctx["dir"])
    approved = export(env, ctx, "viewer").json()
    assert approved["boq_status"] == "approved" and "_NHAP_" not in approved["filename"]
    wb = openpyxl.load_workbook(io.BytesIO(workbook(env, ctx, approved, "viewer")))
    assert "ĐÃ PHÊ DUYỆT" in wb["Tổng hợp"]["A3"].value and "director@a.test" in str(wb["Tổng hợp"]["B7"].value)
    hist = env.get(f"{base}/exports", headers=ctx["viewer"]).json()
    assert [h["id"] for h in hist] == [approved["id"], first["id"]]
    assert [h["boq_status"] for h in env.get(f"{B}/projects/{ctx['project_id']}/boq-exports", headers=ctx["viewer"]).json()] == ["approved", "draft"]
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/boq-exports/{first['id']}/download", headers=b).status_code == 404
    assert env.post(f"{base}/exports", headers=b).status_code == 404
    assert env.get(f"{B}/projects/{ctx['project_id']}/boq-exports", headers=b).status_code == 404
    actions = [x["action"] for x in env.get(f"{B}/audit-logs", headers=login(env, "admin@a.test", "pw-admin-1")).json()]
    assert actions.count("export") == 2 and "download" in actions


def test_multi_page_export_names_the_sheet_of_each_item(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    qs = login(env, "qs_engineer@a.test", "pw-x")
    from tests.drawing_helpers import process, upload
    d = process(env, qs, upload(env, qs, pf.mixed_doc())["id"]).json()
    for page in (1, 2):
        env.post(f"{B}/drawings/{d['id']}/pages/{page}/calibration", json={"units": "mm"}, headers=qs)
    boq = make_boq(env, qs, [d["id"]]).json()
    exp = env.post(f"{B}/boqs/{boq['id']}/exports", headers=qs).json()
    wb = openpyxl.load_workbook(io.BytesIO(env.get(f"{B}/boq-exports/{exp['id']}/download", headers=qs).content))
    sheets = {(r[8].value, r[7].value) for r in wb["BOQ"].iter_rows(min_row=4) if r[14].value}
    assert sheets == {(1, "KC-01"), (2, "KC-02")}


# ---------------------------------------------------------------- Phase 4.1: company BOQ template layout
def company_export(env, h, boq_id):
    exp = env.post(f"{B}/boqs/{boq_id}/exports?layout=company_kl", headers=h)
    assert exp.status_code == 201, exp.text
    e = exp.json()
    return e, env.get(f"{B}/boq-exports/{e['id']}/download", headers=h).content


def quotation_boq(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    qs = login(env, "qs_engineer@a.test", "pw-x")
    from tests.drawing_helpers import process, upload
    d = process(env, qs, upload(env, qs, pf.quotation_pdf())["id"]).json()
    boq = make_boq(env, qs, [d["id"]]).json()
    for i in boq["items"]:
        ok = not i["has_blocking"]
        env.post(f"{B}/boqs/{boq['id']}/items/{i['id']}/review",
                 json={"decision": "accept" if ok else "reject", "note": "đã kiểm tra" if ok else "thiếu khối lượng"}, headers=qs)
    return qs, env.get(f"{B}/boqs/{boq['id']}", headers=qs).json()


def test_company_layout_structure_matches_template_spec(env, monkeypatch):
    from app.boq import company_layout as CL
    qs, boq = quotation_boq(env, monkeypatch)
    e, data = company_export(env, qs, boq["id"])
    assert e["layout"] == "company_kl" and "_TongHop" in e["filename"]
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Tong hop", "BOQ", "Tính chi tiết", "Truy vết nguồn"] and wb.active.title == "Tong hop"
    ws = wb["Tong hop"]
    assert [ws[f"{c}2"].value for c in "ABCDE"] == ["STT", "HẠNG MỤC", "ĐƠN VỊ", "TỔNG KHỐI LƯỢNG", "GHI CHÚ"]
    assert {"A2:A3", "B2:B3", "C2:C3", "D2:D3", "E2:E3"} <= {str(r) for r in ws.merged_cells.ranges}
    assert ws["A2"].fill.fgColor.rgb == "FFC0C0C0" and ws["B2"].font.name == "Times New Roman" and ws["B2"].font.b
    assert [round(ws.column_dimensions[c].width, 1) for c in "ABCDE"] == [24.1, 52.7, 12.2, 25.6, 27.2]
    assert ws.print_title_rows == "$1:$3" and ws.page_setup.orientation == "landscape" and str(ws.page_setup.paperSize) == ws.PAPERSIZE_A3
    rows = [[ws.cell(r, c).value for c in range(1, 7)] for r in range(4, ws.max_row + 1)]
    stt = [r[0] for r in rows if r[0]]
    assert stt[:3] == ["I", "1", "2"] and "3.1" in stt and "3.2" in stt and "4.1" in stt
    by_desc = {r[1]: (n + 4, r) for n, r in enumerate(rows)}
    hdr_row, hdr = by_desc["Tôn lượn sóng"]
    assert hdr[0] == "3" and hdr[3] is None and ws[f"A{hdr_row}"].fill.fgColor.rgb == "FFFFFF00"  # level-1 group: yellow, no total
    asm_row, asm = by_desc["Tôn sóng làm mới loại B-1"]
    assert asm[0] == "3.1" and ws[f"B{asm_row}"].font.b and asm[3].startswith("='Tính chi tiết'!B") and asm[2] == "m"
    comp_row, comp = next((n + 4, r) for n, r in enumerate(rows) if r[1] == "Cột thép D140x4.5x2500")
    assert ws[f"B{comp_row}"].font.i and comp[0] is None  # assembly components: italic, no STT (as in the template)
    assert ws[f"D{comp_row}"].number_format == CL.NUMBER_FORMAT
    assert comp[5].startswith("tr.1") or "tr.1" in comp[5]  # traceability extension column F
    assert "Hạng mục chưa có khối lượng" not in by_desc  # rejected rows are not in the company sheet
    assert ws.print_area.endswith(f"$E${ws.max_row}") or "$E$" in ws.print_area  # column F outside the print area


@pytest.mark.skipif(not SOFFICE, reason="LibreOffice not installed")
def test_company_layout_formulas_recalculate_to_engine_values(env, monkeypatch, tmp_path):
    qs, boq = quotation_boq(env, monkeypatch)
    _, data = company_export(env, qs, boq["id"])
    src = tmp_path / "company.xlsx"
    src.write_bytes(data)
    subprocess.run([SOFFICE, f"-env:UserInstallation=file://{tmp_path}/lo", "--headless", "--calc", "--convert-to",
                    "xlsx:Calc MS Excel 2007 XML", "--outdir", str(tmp_path / "out"), str(src)], check=True, capture_output=True, timeout=180)
    ws = openpyxl.load_workbook(tmp_path / "out" / "company.xlsx", data_only=True)["Tong hop"]
    got = {}
    for r in range(4, ws.max_row + 1):
        trace = ws.cell(r, 6).value
        if trace and ws.cell(r, 4).value is not None:
            got[str(trace).split("| ")[-1]] = D(str(ws.cell(r, 4).value)).quantize(D("0.0001"))
    expected = {i["id"]: D(i["quantity"]) for i in boq["items"] if i["review_status"] == "accepted"}
    assert got == expected and len(got) == 12


def test_company_layout_groups_annotation_items_by_category(env, ctx):
    e, data = company_export(env, ctx["qs"], ctx["boq"]["id"])
    ws = openpyxl.load_workbook(io.BytesIO(data))["Tong hop"]
    heads = [ws.cell(r, 2).value for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value]
    assert heads[:4] == ["Bê tông", "Cốt thép", "Thép hộp", "Bản mã / thép tấm"]  # synthesised groups for drawing annotations
    assert env.post(f"{B}/boqs/{ctx['boq']['id']}/exports?layout=nope", headers=ctx["qs"]).status_code == 422
