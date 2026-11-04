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
