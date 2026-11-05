"""Phase 5D: component recognition. All drawings are SYNTHETIC (tests/component_helpers.py, tests/geometry_helpers.py).

Passing these tests proves the deterministic logic only; it says nothing about recognition accuracy on real construction
drawings (none available - see docs/PHASE5D_COMPONENT_RECOGNITION.md §17).
"""
import ast
import json
import pathlib
import random
import time
from decimal import Decimal

import pytest

from app.components import engine as E
from app.components import repetition as R
from app.components import spatial as S
from app.components import symbols as Y
from app.components.service import TRANSITIONS, catalog
from tests import component_helpers as H
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr
from tests.geometry_helpers import _t, sheet


# ------------------------------------------------------------------ helpers
def drawing(env, a, data, ratio=None, assoc=True):
    d = process(env, a, upload(env, a, data)["id"]).json()
    if ratio:
        for p in env.get(f"{B}/drawings/{d['id']}", headers=a).json()["pages"]:
            env.post(f"{B}/drawings/{d['id']}/pages/{p['page_no']}/calibration", json={"scale_ratio": ratio}, headers=a)
        if assoc:
            env.post(f"{B}/drawings/{d['id']}/associations/run", headers=a)
    r = env.post(f"{B}/drawings/{d['id']}/components/run", headers=a)
    assert r.status_code == 200, r.text
    return d, r.json()


def comps(env, a, d, **q):
    return env.get(f"{B}/drawings/{d['id']}/components", params=q, headers=a).json()


def evidence(env, a, c):
    return env.get(f"{B}/components/{c['id']}/evidence", headers=a).json()


@pytest.fixture()
def admin(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def specs():
    cat = catalog()
    types = [E.TypeSpec(t["code"], t["group"], t["name_vi"], t["parent"], t["family"], t["rule"], t.get("boq"), t.get("member_type"))
             for t in cat["types"]]
    pats = [Y.Pattern(str(i), p["component_type"], p["pattern_type"], p["parameters"], p["tolerance"], p["confidence_weight"])
            for i, p in enumerate(cat["symbol_patterns"])]
    return types, pats, cat


def G(id_, pts, kind="line", closed=False, order=0, length=None):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if length is None and not closed:
        length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))
    return S.Geo(id_, kind, pts, closed, (min(xs), min(ys), max(xs), max(ys)), order, kind == "fill_region", length)


def circle(id_, cx, cy, r, order=0):
    import math
    pts = [(cx + r * math.cos(k * math.pi / 8), cy + r * math.sin(k * math.pi / 8)) for k in range(16)]
    g = G(id_, pts, "circle", True, order)
    g.bbox = (cx - r, cy - r, cx + r, cy + r)
    return g


def fake_measure(kind, gids):
    return E.Measured(f"m-{kind}-{'-'.join(gids)}", kind, None, Decimal("1"), None, "scale_unconfirmed")


# ------------------------------------------------------------------ taxonomy is data
def test_taxonomy_is_data_and_covers_required_types():
    cat = catalog()
    codes = {t["code"] for t in cat["types"]}
    required = {"GUARDRAIL", "CRASH_BARRIER", "FENCE", "FENCE_POST", "STEEL_POST", "ROAD_SIGN", "SIGN_POST", "DELINEATOR", "REFLECTOR",
                "BOLLARD", "DRAINAGE_GRATING", "PIPE", "CULVERT", "MANHOLE", "DRAIN", "CONCRETE_CHANNEL", "ROAD_SURFACE", "KERB",
                "SIDEWALK", "COLUMN", "BEAM", "SLAB", "FOOTING", "WALL", "STEEL_MEMBER", "PLATE", "BOLT", "BRACKET", "ROUND_PIPE",
                "RECTANGULAR_TUBE", "H_BEAM", "I_BEAM", "ANGLE", "CHANNEL", "REBAR", "CORRUGATED_SHEET"}
    assert required <= codes
    for t in cat["types"]:
        assert t["parent"] is None or t["parent"] in codes and t["group"] in cat["discipline_groups"]
    assert {p["pattern_type"] for p in cat["symbol_patterns"]} == set(Y.PATTERN_TYPES)
    # the engine module holds no component-type literal from the taxonomy (rules come from data)
    src = pathlib.Path(E.__file__).read_text()
    assert not any(f'"{c}"' in src for c in required - {"STEEL_POST"})  # STEEL_POST = documented default for unlabelled post rows


def test_new_component_type_without_code_change(env, admin):
    body = {"code": "NOISE_BARRIER", "group": "ATGT", "name_vi": "Tường chống ồn", "family": "barrier",
            "rule": {"keywords": ["TƯỜNG CHỐNG ỒN"], "geometry_kinds": ["line", "polyline"], "measurement_kind": "length"},
            "boq": {"description_vi": "Tường chống ồn", "unit": "m", "measurement_kind": "length"}}
    assert env.post(f"{B}/component-types", json={**body, "rule": {"bogus": 1}}, headers=admin).status_code == 422
    assert env.post(f"{B}/component-types", json=body, headers=admin).status_code == 201
    assert env.post(f"{B}/component-types", json=body, headers=admin).status_code == 409

    def build(p):
        p.draw_line((100, 400), (500, 400), width=0.6)
        _t(p, (250, 394), "TƯỜNG CHỐNG ỒN", 9)
    d, _ = drawing(env, admin, H.pdf(("MẶT BẰNG", build, "GT-09")))
    assert [c["component_type"] for c in comps(env, admin, d)] == ["NOISE_BARRIER"]
    assert any(t["code"] == "NOISE_BARRIER" and t["source"] == "company" for t in env.get(f"{B}/component-types", headers=admin).json())


# ------------------------------------------------------------------ pure engine: spatial, symbols, repetition
def test_spatial_relationships():
    h = G("h", [(0, 0), (100, 0)])
    assert {"PARALLEL_TO", "ALIGNED_WITH", "NEAR"} <= set(S.relations(G("a", [(120, 0), (200, 0)]), h))
    assert "PARALLEL_TO" in S.relations(G("p", [(0, 10), (100, 10)]), h)
    v = G("v", [(50, -10), (50, 10)])
    assert {"PERPENDICULAR_TO", "INTERSECTS"} <= set(S.relations(v, h))
    assert "CONNECTED_TO" in S.relations(G("c", [(100, 0), (100, 50)]), h)
    assert "ON" in S.relations(G("o", [(10, 0), (20, 0)]), h)
    box = G("box", [(0, 0), (100, 0), (100, 100), (0, 100)], "rect", True)
    assert "INSIDE" in S.relations(circle("in", 50, 50, 5), box)
    assert S.between((40, 3, 60, 7), h, G("h2", [(0, 10), (100, 10)]))
    assert S.text_relation((40, -8, 60, -1), h, 30)[0] == "NEAR"
    assert S.relations(G("far", [(0, 500), (10, 500)]), h) in ([], ["PARALLEL_TO"])


def test_symbol_patterns_match_vector_geometry():
    types, pats, _ = specs()
    geoms = [circle("post", 100, 100, 10), G("stem", [(100, 110), (100, 180)]),
             G("r", [(300, 300), (320, 300), (320, 320), (300, 320)], "rect", True),
             G("l1", [(400, 400), (500, 400)]), G("l2", [(400, 404), (500, 404)]),
             G("x1", [(600, 600), (610, 610)]), G("x2", [(600, 610), (610, 600)]),
             G("arrow", [(700, 700), (706, 703), (700, 706)], "polygon", True),
             G("fill", [(800, 100), (900, 100), (900, 200), (800, 200)], "fill_region", True),
             G("leader", [(200, 520), (260, 560)]), circle("target", 263, 563, 3)]
    grid = S.Grid(geoms)
    found = {(s.pattern_type, tuple(s.geometry_ids)) for s in Y.match(pats, geoms, grid, [("t1", (170, 512, 198, 522))])}
    assert ("circle_with_stem", ("post", "stem")) in found
    assert ("rectangle", ("r",)) in found and ("parallel_lines", ("l1", "l2")) in found
    assert any(p == "cross" for p, _ in found) and ("arrow", ("arrow",)) in found and ("filled_region", ("fill",)) in found
    assert ("leader", ("leader", "target")) in found and any(p == "line" for p, _ in found)


def test_repetition_groups_regular_irregular_and_never_extrapolates():
    pat = Y.Pattern("p", "STEEL_POST", "circle", {"repeatable": True}, {}, 0.6)
    line = G("route", [(0, 0), (1000, 0)])

    def run(xs, fills=()):
        cs = [circle(f"c{i}", x, 0, 3, order=1) for i, x in enumerate(xs)]
        syms = Y.match([pat], cs, S.Grid(cs))
        return R.detect(syms, [line], list(fills), {c.id: c.order for c in cs})
    g = run([50 * i + 50 for i in range(10)])
    assert len(g) == 1 and len(g[0].members) == 10 and g[0].pattern_status == R.REGULAR and g[0].carrier_id == "route"
    assert run([50, 100, 150, 230, 280, 300])[0].pattern_status == R.IRREGULAR
    hidden = run([50, 100, 150, 250, 300], [G("box", [(180, -10), (220, -10), (220, 10), (180, 10)], "fill_region", True, order=9)])[0]
    assert hidden.pattern_status == R.OCCLUDED and len(hidden.members) == 5  # 5 visible, the hidden one is NOT added
    assert run([50, 100]) == []  # below the minimum count: no group


# ------------------------------------------------------------------ required scenarios (API, synthetic PDFs)
def test_1_steel_post_from_text_circle_and_stem(env, admin):
    d, _ = drawing(env, admin, H.sheet_post(), ratio=10)
    [c] = comps(env, admin, d)
    assert c["component_type"] == "STEEL_POST" and c["status"] != "CONFIRMED" and c["dimensions"]["diameter_mm"] == "88.3"
    assert len(c["source_geometry_ids"]) == 2 and c["scores"]["symbol"] > 0.8 and c["scores"]["measurement"] == 1.0
    ev = evidence(env, admin, c)
    [m] = ev["measurements"]
    assert m["kind"] == "diameter" and m["value_real"] == "0.0883" and m["method"] == "component-5D"  # 5B engine, referenced
    assert ev["detail"]["comparisons"][0]["stated"] == "88.3" and ev["detail"]["comparisons"][0]["unit"] == "mm"


def test_2_bolt_and_context(env, admin):
    d, _ = drawing(env, admin, H.sheet_bolt())
    [c] = comps(env, admin, d)
    assert c["component_type"] == "BOLT" and c["dimensions"]["bolt_diameter_mm"] == "16" and c["dimensions"]["bolt_length_mm"] == "35"
    assert c["status"] in ("REVIEW_REQUIRED", "CANDIDATE") and c["source_measurement_ids"] == []
    d2, _ = drawing(env, admin, H.sheet_bolt(in_note=True))
    assert comps(env, admin, d2) == []  # "M16x35" inside a general note is not a component


def test_3_corrugated_sheet(env, admin):
    d, _ = drawing(env, admin, sheet())
    c = next(x for x in comps(env, admin, d) if x["component_type"] == "CORRUGATED_SHEET")
    assert c["description"] == "HỘ LAN TÔN LƯỢN SÓNG" and len(c["source_geometry_ids"]) == 1
    assert not any(x["component_type"] == "GUARDRAIL" for x in comps(env, admin, d))  # the more specific type wins


def test_4_repeated_posts_one_group(env, admin):
    d, _ = drawing(env, admin, H.sheet_fence(), ratio=100)
    cs = comps(env, admin, d)
    assert sorted(c["component_type"] for c in cs) == ["FENCE", "FENCE_POST"]  # NOT 10 separate post components
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    fence = next(c for c in cs if c["component_type"] == "FENCE")
    assert post["parent_id"] == fence["id"] and len(post["source_geometry_ids"]) == 10
    ev = evidence(env, admin, post)
    grp = ev["repeat_group"]
    assert grp["pattern_status"] == "REGULAR" and len(grp["gaps_pt"]) == 9
    vals = {m["kind"]: m["value_real"] for m in ev["measurements"]}
    assert vals == {"count": "10", "spacing": "2.117"}  # candidate count/spacing come from 5B measurements
    assert {r["type"] for r in ev["relations"]} >= {"PART_OF", "REPEATED_ALONG"}


@pytest.mark.parametrize("kw,status,count", [({"gaps": [60, 60, 90, 60, 60, 40, 60, 60, 60]}, "REVIEW_REQUIRED", "10"),
                                             ({"occlude": "member"}, "OCCLUDED", "10"), ({"occlude": "gap"}, "OCCLUDED", "9")])
def test_4b_irregular_and_occluded_rows(env, admin, kw, status, count):
    d, _ = drawing(env, admin, H.sheet_fence(**kw), ratio=100)
    post = next(c for c in comps(env, admin, d) if c["component_type"] == "FENCE_POST")
    ev = evidence(env, admin, post)
    assert post["status"] == status
    assert ev["repeat_group"]["pattern_status"] == ("IRREGULAR_PATTERN" if "gaps" in kw else "OCCLUDED")
    assert {m["kind"]: m["value_real"] for m in ev["measurements"]}["count"] == count  # visible count only, never interpolated


def test_5_duplicate_representation_is_one_identity(env, admin):
    d, _ = drawing(env, admin, sheet(extra=lambda p: _t(p, (600, 412), "L=8.82m", 8)), ratio=100)
    on_route = [c for c in comps(env, admin, d) if c["component_type"] in ("CORRUGATED_SHEET", "LINEAR_COMPONENT")
                and c["bbox"][0] == 500]
    assert len(on_route) == 1 and on_route[0]["component_type"] == "CORRUGATED_SHEET"
    texts = {t["id"]: t["original_text"] for t in env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=admin).json()}
    assert {"HỘ LAN TÔN LƯỢN SÓNG", "L=8.82m"} <= {texts[t] for t in on_route[0]["source_text_ids"]}
    d2, _ = drawing(env, admin, H.sheet_post(), ratio=10)
    assert len(comps(env, admin, d2)) == 1  # text + circle + stem + diameter = one component


def test_6_plan_and_detail_not_double_counted(env, admin):
    d, stats = drawing(env, admin, H.sheet_plan_detail(), ratio=10)
    cs = comps(env, admin, d)
    plan = next(c for c in cs if c["page_no"] == 1)
    det = next(c for c in cs if c["page_no"] == 2)
    assert plan["view_context"] == "PLAN" and det["view_context"] == "DETAIL" and stats["representations"] == 1
    assert det["representation_of_id"] == plan["id"] and plan["representation_of_id"] is None
    rels = {(r["type"], r["from"], r["to"]) for r in evidence(env, admin, plan)["relations"]}
    assert ("DETAILED_IN", plan["id"], det["id"]) in rels and ("REPRESENTATION_OF", det["id"], plan["id"]) in rels
    assert ("REFERENCES", plan["id"], det["id"]) in rels  # "CHI TIẾT A" callout -> page titled "CHI TIẾT A"
    for c in (plan, det):
        env.post(f"{B}/components/{c['id']}/review", json={}, headers=admin)
        assert env.post(f"{B}/components/{c['id']}/confirm", json={"note": "ok"}, headers=admin).status_code == 200
    boq = env.get(f"{B}/drawings/{d['id']}/component-boq-candidates", headers=admin).json()
    assert [b["component_id"] for b in boq] == [plan["id"]]  # the detail is a representation: no second candidate
    assert env.get(f"{B}/components/{det['id']}", headers=admin).json()["downstream_allowed"] is False


def test_7_conflict_text_vs_geometry(env, admin):
    d, _ = drawing(env, admin, sheet(), ratio=100)
    texts = {t["id"]: t["original_text"] for t in env.get(f"{B}/drawings/{d['id']}/pages/1/text-blocks", headers=admin).json()}
    c = next(x for x in comps(env, admin, d) if any(texts[t] == "L=13.50m" for t in x["source_text_ids"]))
    assert c["status"] == "CONFLICT" and c["scores"]["measurement"] == 0.0
    cmp_ = evidence(env, admin, c)["detail"]["comparisons"][0]
    assert (cmp_["stated"], cmp_["measured"], cmp_["difference"]) == ("13.5", "12.7", "0.8")
    assert "13.5" in c["ambiguity_reason"] and "không tự sửa" in c["ambiguity_reason"]
    env.post(f"{B}/components/{c['id']}/review", json={}, headers=admin)  # CONFLICT -> REVIEW_REQUIRED is allowed
    ok = next(x for x in comps(env, admin, d) if x["id"] == c["id"])
    assert ok["status"] == "REVIEW_REQUIRED"


def test_8_unconfirmed_component_cannot_reach_boq(env, admin):
    d, _ = drawing(env, admin, H.sheet_fence(), ratio=100)
    fence = next(c for c in comps(env, admin, d) if c["component_type"] == "FENCE")
    assert fence["status"] == "CANDIDATE" and fence["confidence_band"] == "HIGH"  # HIGH is evidence strength, not approval
    assert env.post(f"{B}/components/{fence['id']}/boq-candidate", headers=admin).status_code == 409
    assert env.post(f"{B}/components/{fence['id']}/confirm", json={"note": "x"}, headers=admin).status_code == 409  # review first
    assert env.get(f"{B}/drawings/{d['id']}/component-boq-candidates", headers=admin).json() == []
    before = env.post(f"{B}/boqs", json={"title": "x", "drawing_ids": [d["id"]]}, headers=admin)
    env.post(f"{B}/components/{fence['id']}/review", json={}, headers=admin)
    conf = env.post(f"{B}/components/{fence['id']}/confirm", json={}, headers=admin).json()
    assert conf["status"] == "CONFIRMED" and conf["downstream_allowed"]
    [b] = env.get(f"{B}/drawings/{d['id']}/component-boq-candidates", headers=admin).json()
    assert (b["status"], b["approval_status"], b["unit"]) == ("DRAFT", "NOT_APPROVED", "m")
    assert b["measurement"]["kind"] == "length" and b["measurement"]["value_real"] == "20.461"  # a REFERENCE, not a copy
    after = env.post(f"{B}/boqs", json={"title": "y", "drawing_ids": [d["id"]]}, headers=admin)
    # the BOQ engine (Phase 4) is unaffected by 5D: same items, none sourced from components
    if before.status_code == 201:
        assert len(after.json()["items"]) == len(before.json()["items"])
    # withdrawing: re-opening the component withdraws the draft hand-over
    env.post(f"{B}/components/{fence['id']}/review", json={"note": "kiểm tra lại"}, headers=admin)
    [b] = env.get(f"{B}/drawings/{d['id']}/component-boq-candidates", headers=admin).json()
    assert b["status"] == "WITHDRAWN"


def test_9_company_isolation(env, admin):
    d, _ = drawing(env, admin, H.sheet_post(), ratio=10)
    [c] = comps(env, admin, d)
    b = login(env, "admin@b.test", "pw-admin-2")
    assert env.get(f"{B}/drawings/{d['id']}/components", headers=b).status_code == 404
    for path in ("", "/evidence", "/history"):
        assert env.get(f"{B}/components/{c['id']}{path}", headers=b).status_code == 404
    for action in ("review", "confirm", "reject", "ambiguous"):
        assert env.post(f"{B}/components/{c['id']}/{action}", json={"note": "x"}, headers=b).status_code == 404
    assert env.post(f"{B}/drawings/{d['id']}/components/run", headers=b).status_code == 404
    v = login(env, "viewer@a.test", "pw-x")
    assert env.get(f"{B}/components/{c['id']}", headers=v).status_code == 200
    assert env.post(f"{B}/components/{c['id']}/reject", json={"note": "x"}, headers=v).status_code == 403
    assert env.post(f"{B}/drawings/{d['id']}/components/run", headers=v).status_code == 403


def test_10_audit_and_history(env, admin):
    d, _ = drawing(env, admin, H.sheet_fence(), ratio=100)
    cs = comps(env, admin, d)
    fence = next(c for c in cs if c["component_type"] == "FENCE")
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    assert env.post(f"{B}/components/{post['id']}/reject", json={}, headers=admin).status_code == 422  # reason required
    assert env.post(f"{B}/components/{post['id']}/reject", json={"note": "không phải trụ"}, headers=admin).json()["rejection_reason"]
    assert env.post(f"{B}/components/{fence['id']}/reclassify", json={"component_type": "GUARDRAIL"}, headers=admin).status_code == 422
    assert env.post(f"{B}/components/{fence['id']}/reclassify", json={"dimensions": {"length_m": "5"}, "reason": "x"},
                    headers=admin).status_code == 422  # quantities are never edited here
    assert env.post(f"{B}/components/{fence['id']}/reclassify", json={"component_type": "NOPE", "reason": "x"}, headers=admin).status_code == 422
    rc = env.post(f"{B}/components/{fence['id']}/reclassify", json={"component_type": "GUARDRAIL", "material": "Thép mạ kẽm",
                                                                    "dimensions": {"height_mm": "1500"}, "reason": "là hộ lan"},
                  headers=admin).json()
    assert rc["component_type"] == "GUARDRAIL" and rc["status"] == "REVIEW_REQUIRED" and rc["recognition_method"] == "engineer"
    assert env.post(f"{B}/components/{fence['id']}/confirm", json={"note": "đúng"}, headers=admin).json()["status"] == "CONFIRMED"
    h = env.get(f"{B}/components/{fence['id']}/history", headers=admin).json()
    assert [x["action"] for x in h] == ["reclassify", "confirm", "prepare_boq_candidate"]
    assert h[0]["detail"]["before"]["component_type"] == "FENCE" and h[0]["user"] == "admin@a.test"
    assert [x["action"] for x in env.get(f"{B}/components/{post['id']}/history", headers=admin).json()] == ["reject"]
    assert env.post(f"{B}/components/{fence['id']}/ambiguous", json={}, headers=admin).status_code == 422


def test_state_machine_is_validated():
    assert "CONFIRMED" not in TRANSITIONS["CANDIDATE"]
    assert all(t in TRANSITIONS for v in TRANSITIONS.values() for t in v)
    assert TRANSITIONS["CONFIRMED"] == {"REVIEW_REQUIRED"} and TRANSITIONS["REJECTED"] == {"REVIEW_REQUIRED"}


def test_ai_task_waits_for_review_and_metrics_are_real(env, admin):
    d, stats = drawing(env, admin, H.sheet_post(), ratio=10)
    assert stats["task_status"] == "waiting_approval" and stats["open"] == 1
    task = next(t for t in env.get(f"{B}/ai-tasks", headers=admin).json() if t["id"] == stats["task_id"])
    assert task["agent_key"] == "pdf_drawing" and task["status"] == "waiting_approval"
    assert env.post(f"{B}/ai-tasks/{task['id']}/approve", headers=admin).status_code == 409  # no bulk approval of components
    metrics = {m["key"]: m["value"] for m in env.get(f"{B}/office/departments/engineering_qs", headers=admin).json()["metrics"]}
    assert metrics["components_detected"] == "1" and metrics["components_awaiting_review"] == "1"
    [c] = comps(env, admin, d)
    env.post(f"{B}/components/{c['id']}/review", json={}, headers=admin)
    env.post(f"{B}/components/{c['id']}/confirm", json={}, headers=admin)
    task = next(t for t in env.get(f"{B}/ai-tasks", headers=admin).json() if t["id"] == stats["task_id"])
    assert task["status"] == "completed"
    metrics = {m["key"]: m["value"] for m in env.get(f"{B}/office/departments/engineering_qs", headers=admin).json()["metrics"]}
    assert metrics["components_confirmed"] == "1" and metrics["components_awaiting_review"] == "0"


def test_rerun_keeps_engineer_decisions(env, admin):
    d, _ = drawing(env, admin, H.sheet_fence(), ratio=100)
    fence = next(c for c in comps(env, admin, d) if c["component_type"] == "FENCE")
    env.post(f"{B}/components/{fence['id']}/reject", json={"note": "sai"}, headers=admin)
    env.post(f"{B}/drawings/{d['id']}/components/run", headers=admin)
    env.post(f"{B}/drawings/{d['id']}/components/run", headers=admin)
    cs = comps(env, admin, d)
    assert [c["status"] for c in cs if c["id"] == fence["id"]] == ["REJECTED"]
    assert sum(1 for c in cs if c["component_type"] == "FENCE") == 1  # the rejected text is not re-recognised
    # still ONE repeated group after two re-runs (its type no longer comes from the rejected fence: never duplicated)
    assert sum(1 for c in cs if c["repeat_group_id"]) == 1
    ms = env.get(f"{B}/drawings/{d['id']}/measurements", headers=admin).json()
    assert sum(1 for m in ms if m["kind"] == "count") == 1  # measurements re-used, not piled up


def test_processing_runs_recognition_and_failure_is_contained(env, admin, monkeypatch):
    d = process(env, admin, upload(env, admin, H.sheet_fence())["id"]).json()
    assert {c["component_type"] for c in comps(env, admin, d)} == {"FENCE", "FENCE_POST"}
    import app.components.service as CS

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(CS, "run", boom)
    d2 = process(env, admin, upload(env, admin, H.sheet_fence(n=5))["id"]).json()
    assert d2["status"] == "processed"
    summ = env.get(f"{B}/drawings/{d2['id']}/geometry/summary", headers=admin).json()
    assert summ["pages"][0]["stats"]["components"]["error"].startswith("RuntimeError")


def test_table_and_title_text_never_trigger_components(env, admin):
    def build(p):
        y = 100
        for row in (["STT", "Hạng mục", "Đơn vị"], ["1", "Hàng rào B40", "m"], ["2", "Bu lông M16x35", "bộ"]):
            for x, cell in zip((63, 103, 263), row):
                _t(p, (x, y + 14), cell, 8)
            y += 20
        for i in range(4):
            p.draw_line((60, 100 + i * 20), (360, 100 + i * 20), width=0.5)
        for x in (60, 100, 260, 360):
            p.draw_line((x, 100), (x, 160), width=0.5)
    d, _ = drawing(env, admin, H.pdf(("BẢNG THỐNG KÊ HÀNG RÀO", build, "GT-10")))
    assert comps(env, admin, d) == []


def test_component_engine_has_no_llm_dependency():
    pkg = pathlib.Path(E.__file__).parent
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(("app.ai", "app.llm", "anthropic", "openai")) for m in mods), f


# ------------------------------------------------------------------ performance (pure engine, spatial index)
def test_benchmark_1000_geometry_5000_texts(capsys):
    types, pats, cat = specs()
    rnd = random.Random(7)
    geoms = []
    for i in range(1000):
        x, y = rnd.uniform(0, 3000), rnd.uniform(0, 2000)
        geoms.append(circle(f"c{i}", x, y, 4) if i % 4 == 0 else G(f"l{i}", [(x, y), (x + rnd.uniform(10, 200), y)]))
    words = ["HÀNG RÀO", "D88.3", "M16x35", "GHI CHÚ: xem bản vẽ", "TÔN LƯỢN SÓNG", "BIỂN BÁO", "L=5.00m", "CỌC TIÊU", "abc"]
    texts = []
    for i in range(5000):
        x, y = rnd.uniform(0, 3000), rnd.uniform(0, 2000)
        w = words[i % len(words)]
        ttype = {"HÀNG RÀO": "LABEL", "D88.3": "DIMENSION", "M16x35": "DIMENSION", "L=5.00m": "LENGTH", "abc": "OTHER"}.get(w, "LABEL")
        vals = {"dimensions": [{"type": "round", "values": ["88.3"], "unit": None}]} if w == "D88.3" else \
               {"dimensions": [{"type": "bolt", "values": ["16", "35"], "unit": None}]} if w == "M16x35" else {}
        if w.startswith("GHI"):
            ttype = "NOTE"
        texts.append(E.TextIn(f"t{i}", ttype, w, w, (x, y, x + 40, y + 9), 9.0, [], vals))
    t0 = time.perf_counter()
    res = E.recognize(texts, geoms, [], types, pats, cat, disciplines=["traffic"], measure=fake_measure)
    total = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\n[5D benchmark] geometry=1000 texts=5000 components={len(res.comps)} timings_ms={res.timings_ms} wall={total:.2f}s")
    assert total < 30 and res.comps


def test_rerunning_5c_keeps_evidence_of_reviewed_components(env, admin):
    """Regression (found on PostgreSQL FKs): re-running 5C must not delete associations a reviewed component relies on."""
    d, _ = drawing(env, admin, sheet(), ratio=100)
    c = next(x for x in comps(env, admin, d) if x["component_type"] == "CORRUGATED_SHEET")
    assert c["source_association_ids"]
    env.post(f"{B}/components/{c['id']}/review", json={"note": "x"}, headers=admin)
    env.post(f"{B}/components/{c['id']}/confirm", json={"note": "chấp nhận dù lý trình xung đột"}, headers=admin)
    assert env.post(f"{B}/drawings/{d['id']}/associations/run", headers=admin).status_code == 200
    after = env.get(f"{B}/components/{c['id']}", headers=admin).json()
    assert after["status"] == "CONFIRMED" and after["source_association_ids"] == c["source_association_ids"]
    for aid in after["source_association_ids"]:
        assert env.get(f"{B}/associations/{aid}", headers=admin).status_code == 200
