import pytest

from tests import pdf_factory as pf
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, make_boq, processed_drawing, use_ocr


@pytest.fixture()
def ctx(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    qs = login(env, "qs_engineer@a.test", "pw-x")
    d = processed_drawing(env, qs, units=None)  # units NOT confirmed -> annotation items blocked
    boq = make_boq(env, qs, [d["id"]]).json()
    return {"qs": qs, "dir": login(env, "director@a.test", "pw-x"), "viewer": login(env, "viewer@a.test", "pw-x"),
            "admin": login(env, "admin@a.test", "pw-admin-1"), "boq": boq, "drawing": d}


def norm(s):
    return pf._ascii(s).upper()


def item(boq, prefix):
    return next(i for i in boq["items"] if norm(i["description"]).startswith(norm(prefix)))


def url(ctx, i=None, tail=""):
    base = f"{B}/boqs/{ctx['boq']['id']}"
    return f"{base}/items/{i['id']}{tail}" if i else f"{base}{tail}"


def get(env, ctx, who="qs"):
    return env.get(url(ctx), headers=ctx[who]).json()


def review(env, ctx, i, decision, note="", who="qs"):
    return env.post(url(ctx, i, "/review"), json={"decision": decision, "note": note}, headers=ctx[who])


def accept_all_reviewable(env, ctx):
    for i in get(env, ctx)["items"]:
        if i["review_status"] == "pending":
            r = review(env, ctx, i, "accept" if not i["has_blocking"] else "reject", "" if not i["has_blocking"] else "Bỏ – trùng/thiếu dữ liệu")
            assert r.status_code == 200, r.text


def test_blocked_item_cannot_be_accepted_until_engineer_fixes_it(env, ctx):
    beam = item(ctx["boq"], "DẦM D1")
    r = review(env, ctx, beam, "accept")
    assert r.status_code == 409 and "đơn vị" in r.json()["detail"].lower()
    assert env.patch(url(ctx, beam), json={"unit_system": "mm"}, headers=ctx["qs"]).status_code == 422  # reason required
    fixed = env.patch(url(ctx, beam), json={"unit_system": "mm", "reason": "Đơn vị theo khung tên: mm"}, headers=ctx["qs"]).json()
    assert fixed["quantity"] == "4.3200" and not fixed["has_blocking"] and fixed["version"] == 2
    assert review(env, ctx, fixed, "accept").json()["review_status"] == "accepted"


def test_edit_marks_engineer_origin_resets_review_and_keeps_history(env, ctx):
    beam = item(ctx["boq"], "DẦM D1")
    env.patch(url(ctx, beam), json={"unit_system": "mm", "reason": "mm"}, headers=ctx["qs"])
    review(env, ctx, beam, "accept")
    e = env.patch(url(ctx, beam), json={"inputs": {"count": "5"}, "reason": "Thực tế 5 dầm theo mặt bằng"}, headers=ctx["qs"]).json()
    assert e["quantity"] == "5.4000" and e["review_status"] == "pending"
    assert e["inputs"]["count"]["origin"] == "engineer" and e["inputs"]["count"]["previous_value"] == "4"
    assert e["inputs"]["length"]["origin"] == "extracted" and e["origin"] == "mixed"
    hist = env.get(url(ctx, beam, "/history"), headers=ctx["viewer"]).json()
    assert [h["action"] for h in hist] == ["generated", "edited", "accepted", "edited"]
    assert [h["quantity"] for h in hist] == [None, "4.3200", "4.3200", "5.4000"]
    assert hist[-1]["reason"] == "Thực tế 5 dầm theo mặt bằng" and hist[-1]["inputs"]["count"] == "5"
    assert env.patch(url(ctx, beam), json={"inputs": {"bogus": "1"}, "reason": "x"}, headers=ctx["qs"]).status_code == 422
    assert env.patch(url(ctx, beam), json={"inputs": {"count": "abc"}, "reason": "x"}, headers=ctx["qs"]).status_code == 422


def test_reject_requires_note_and_annotations(env, ctx):
    beam = item(ctx["boq"], "DẦM D1")
    assert review(env, ctx, beam, "reject").status_code == 422
    r = review(env, ctx, beam, "reject", "Trùng với bảng thống kê").json()
    assert r["review_status"] == "rejected" and "Trùng với bảng thống kê" in r["notes"]
    n = env.post(url(ctx, beam, "/notes"), json={"note": "Đã đối chiếu với KC-01"}, headers=ctx["qs"]).json()
    assert "Đã đối chiếu" in n["notes"] and "qs_engineer@a.test" in n["notes"]


def test_submit_rules_four_eyes_and_approval(env, ctx):
    assert env.post(url(ctx, tail="/submit"), json={"note": ""}, headers=ctx["qs"]).status_code == 409  # pending items
    accept_all_reviewable(env, ctx)
    s = env.post(url(ctx, tail="/submit"), json={"note": "Trình duyệt"}, headers=ctx["qs"]).json()
    assert s["status"] == "submitted" and s["approval_task_id"]
    # locked while submitted
    i = s["items"][0]
    assert env.patch(url(ctx, i), json={"description": "x", "reason": "x"}, headers=ctx["qs"]).status_code == 409
    office = env.get(f"{B}/office/departments/engineering_qs", headers=ctx["viewer"]).json()
    m = {x["key"]: x["value"] for x in office["metrics"]}
    assert office["status"] == "waiting_approval" and m["boq_submitted"] == "1" and m["boq_draft"] == "0"
    # QS engineer cannot approve; viewer cannot approve
    assert env.post(url(ctx, tail="/decision"), json={"decision": "approve"}, headers=ctx["qs"]).status_code == 403
    assert env.post(url(ctx, tail="/decision"), json={"decision": "approve"}, headers=ctx["viewer"]).status_code == 403
    assert env.post(url(ctx, tail="/decision"), json={"decision": "return"}, headers=ctx["dir"]).status_code == 422  # note required
    a = env.post(url(ctx, tail="/decision"), json={"decision": "approve", "note": "OK"}, headers=ctx["dir"]).json()
    assert a["status"] == "approved" and a["decided_by"]
    task = next(t for t in env.get(f"{B}/ai-tasks?department=engineering_qs", headers=ctx["dir"]).json() if t["id"] == s["approval_task_id"])
    assert task["status"] == "completed"
    m = {x["key"]: x["value"] for x in env.get(f"{B}/office/departments/engineering_qs", headers=ctx["dir"]).json()["metrics"]}
    assert m["boq_approved"] == "1" and m["boq_submitted"] == "0"
    # approved = immutable
    assert env.patch(url(ctx, i), json={"description": "x", "reason": "x"}, headers=ctx["qs"]).status_code == 409
    assert review(env, ctx, i, "reset").status_code == 409
    assert env.patch(url(ctx, tail="/rules"), json={"decimals": 2}, headers=ctx["qs"]).status_code == 409
    assert env.post(url(ctx, tail="/items"), json={"category": "other", "description": "x", "quantity": "1", "stated_unit": "m"}, headers=ctx["qs"]).status_code == 409


def test_four_eyes_blocks_self_approval_even_for_admin(env, ctx):
    accept_all_reviewable(env, ctx)
    env.post(url(ctx, tail="/submit"), json={"note": ""}, headers=ctx["admin"])
    r = env.post(url(ctx, tail="/decision"), json={"decision": "approve"}, headers=ctx["admin"])
    assert r.status_code == 403 and "4 mắt" in r.json()["detail"]


def test_return_then_resubmit_and_generic_task_approval_delegates(env, ctx):
    accept_all_reviewable(env, ctx)
    s = env.post(url(ctx, tail="/submit"), json={"note": ""}, headers=ctx["qs"]).json()
    r = env.post(url(ctx, tail="/decision"), json={"decision": "return", "note": "Kiểm tra lại cốt thép"}, headers=ctx["dir"]).json()
    assert r["status"] == "returned" and r["decision_note"] == "Kiểm tra lại cốt thép"
    tasks = {t["id"]: t for t in env.get(f"{B}/ai-tasks", headers=ctx["dir"]).json()}
    assert tasks[s["approval_task_id"]]["status"] == "cancelled"
    # editable again, resubmit, approve via the generic AI-task endpoint (office panel button)
    s2 = env.post(url(ctx, tail="/submit"), json={"note": "Đã sửa"}, headers=ctx["qs"]).json()
    assert s2["approval_task_id"] != s["approval_task_id"]
    assert env.post(f"{B}/ai-tasks/{s2['approval_task_id']}/approve", headers=ctx["qs"]).status_code == 403
    t = env.post(f"{B}/ai-tasks/{s2['approval_task_id']}/approve", headers=ctx["dir"]).json()
    assert t["status"] == "completed" and get(env, ctx)["status"] == "approved"


def test_new_version_after_approval(env, ctx):
    accept_all_reviewable(env, ctx)
    env.post(url(ctx, tail="/submit"), json={"note": ""}, headers=ctx["qs"])
    env.post(url(ctx, tail="/decision"), json={"decision": "approve"}, headers=ctx["dir"])
    assert env.post(url(ctx, tail="/new-version"), json={"reason": ""}, headers=ctx["qs"]).status_code == 422
    nv = env.post(url(ctx, tail="/new-version"), json={"reason": "Phụ lục 1: thêm dầm"}, headers=ctx["qs"]).json()
    assert nv["version_no"] == 2 and nv["previous_boq_id"] == ctx["boq"]["id"] and nv["status"] == "draft"
    assert nv["item_count"] == ctx["boq"]["item_count"] and all(i["review_status"] == "pending" for i in nv["items"])
    assert nv["sources"] == get(env, ctx)["sources"]
    assert env.post(url(ctx, tail="/new-version"), json={"reason": "again"}, headers=ctx["qs"]).status_code == 409
    hist = env.get(f"{B}/boqs/{nv['id']}/items/{nv['items'][0]['id']}/history", headers=ctx["qs"]).json()
    assert hist[0]["action"] == "copied_from_version"
    assert get(env, ctx)["status"] == "approved"  # previous version untouched


def test_totals_and_isolation(env, ctx):
    beam = item(ctx["boq"], "DẦM D1")
    env.patch(url(ctx, beam), json={"unit_system": "mm", "reason": "mm"}, headers=ctx["qs"])
    review(env, ctx, beam, "accept")
    t = {(x["category"], x["unit"]): x for x in get(env, ctx)["totals"]}
    assert t[("concrete", "m3")]["accepted"] == "4.3200" and t[("concrete", "m3")]["all_active"] == "8.6400"
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(url(ctx, beam, "/history"), headers=b).status_code == 404
    assert env.patch(url(ctx, beam), json={"unit_system": "m", "reason": "x"}, headers=b).status_code == 404
    assert review(env, ctx, beam, "reset", who="viewer").status_code == 403
