"""Phase 5E-2: rule registry, deterministic rules, duplicate/occlusion control, drawing runner, demo (SYNTHETIC only)."""
import io
import pathlib
import re

import pytest

from app.quantity import engine as E
from app.quantity import rules as RR
from tests import component_helpers as H
from tests.conftest import B, login
from tests.drawing_helpers import FakeOcr, process, upload, use_ocr
from tests.geometry_helpers import sheet

SRC = {"source_type": "ENGINEER_INPUT", "source_reference": "test – chi tiết trụ"}


# ------------------------------------------------------------------ registry
def test_registry_is_data_validated_against_engine_methods():
    reg = RR.registry()
    for t in ("STEEL_POST", "BOLT", "CORRUGATED_SHEET", "LINEAR_COMPONENT", "GUARDRAIL", "NOISE_BARRIER"):
        assert RR.rules_for(t), t
    assert {r.rule_code for r in RR.rules_for("STEEL_POST")} == {"STEEL_POST.COUNT", "STEEL_POST.TOTAL_LENGTH", "STEEL_POST.WEIGHT"}
    assert reg["STEEL_POST.TOTAL_LENGTH"].formula == "COUNT × UNIT_LENGTH" and reg["FENCE_POST.SPACING"].auto is False
    bad = {"rules": [{"rule_code": "X", "component_type": "X", "quantity_type": "AREA", "method": "COUNT_REFERENCE",
                      "required_measurements": ["count"], "required_parameters": [], "formula": "", "output_unit": "ea"}]}
    with pytest.raises(RR.RuleError):
        RR.load(bad)  # quantity type must match the method
    dup = {"rules": [dict(bad["rules"][0], quantity_type="COUNT")] * 2}
    with pytest.raises(RR.RuleError):
        RR.load(dup)


def test_no_component_name_branching_in_engine_or_service():
    pkg = pathlib.Path(E.__file__).parent
    codes = {r.component_type for r in RR.registry().values()}
    for f in ("engine.py", "service.py", "rules.py"):
        src = (pkg / f).read_text()
        assert not any(re.search(rf'["\']{c}["\']', src) for c in codes), f


# ------------------------------------------------------------------ demo (spec §20 dataset)
def test_demo_is_deterministic_and_matches_expected():
    from app.quantity.demo import demo_seeded
    out = io.StringIO()
    rows = {(r["label"], r["rule"]): r for r in demo_seeded(out)}
    exp = {("C1", "STEEL_POST.COUNT"): ("51", "ea", "51 ea"),
           ("C1", "STEEL_POST.TOTAL_LENGTH"): ("127.500", "m", "51 × 2.500 m = 127.500 m"),
           ("C2", "GUARDRAIL.LENGTH"): ("125.400", "m", "125.400 m"),
           ("C3", "BOLT.COUNT"): ("240", "ea", "240 ea"),
           ("C4", "CORRUGATED_SHEET.AREA"): ("85.750", "m2", "85.750 m²"),
           ("C5", "STEEL_POST.WEIGHT"): ("395.000", "kg", "100.000 m × 3.950 kg/m = 395.000 kg")}
    for k, (val, unit, trace) in exp.items():
        assert (rows[k]["value"], rows[k]["unit"], rows[k]["trace"], rows[k]["status"]) == (val, unit, trace, "CALCULATED"), k
    assert rows[("C6", "STEEL_POST.COUNT")]["status"] == "BLOCKED (HTTP 422)"
    again = io.StringIO()
    demo_seeded(again)
    strip = lambda s: re.sub(r"measurement [0-9a-f,]+", "", s)  # ids differ per run; values/formulas must not
    assert strip(out.getvalue()) == strip(again.getvalue())


def test_demo_cli_runs():
    from app.quantity.demo import main
    assert main([]) == 0


# ------------------------------------------------------------------ API on synthetic drawings
@pytest.fixture()
def admin(env, monkeypatch):
    use_ocr(monkeypatch, FakeOcr())
    return login(env, "admin@a.test", "pw-admin-1")


def build(env, a, data, ratio):
    d = process(env, a, upload(env, a, data)["id"]).json()
    for p in env.get(f"{B}/drawings/{d['id']}", headers=a).json()["pages"]:
        env.post(f"{B}/drawings/{d['id']}/pages/{p['page_no']}/calibration", json={"scale_ratio": ratio}, headers=a)
    env.post(f"{B}/drawings/{d['id']}/associations/run", headers=a)
    env.post(f"{B}/drawings/{d['id']}/components/run", headers=a)
    return d, env.get(f"{B}/drawings/{d['id']}/components", headers=a).json()


def confirm_all(env, a, comps, measurements=True):
    for c in comps:
        if c["status"] == "CANDIDATE":
            env.post(f"{B}/components/{c['id']}/review", json={}, headers=a)
        assert env.post(f"{B}/components/{c['id']}/confirm", json={"note": "test"}, headers=a).status_code == 200
        if measurements:
            for m in c["source_measurement_ids"]:
                env.post(f"{B}/measurements/{m}/confirm", json={"note": "test"}, headers=a)


def test_drawing_runner_fence(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    s = env.post(f"{B}/drawings/{d['id']}/quantities/run",
                 json={"parameters": {post["id"]: {"unit_length": {"value": "2.5", "unit": "m", **SRC}}}}, headers=admin).json()
    assert (s["components_scanned"], s["rules_matched"], s["calculated"], s["requires_review"], s["blocked"]) == (2, 3, 3, 0, 0)
    rows = {r["rule_code"]: r for r in env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=admin).json()}
    assert rows["FENCE.LENGTH"]["formula_trace"] == "20.461 m" and rows["FENCE_POST.COUNT"]["quantity_value"] == "10"
    tl = rows["FENCE_POST.TOTAL_LENGTH"]
    assert tl["formula_trace"] == "10 × 2.500 m = 25.000 m" and tl["formula"] == "COUNT × UNIT_LENGTH"
    assert tl["parameters"]["unit_length"]["entered_by"] == "admin@a.test" and tl["page_no"] == 1
    assert "FENCE_POST.SPACING" not in rows  # spacing is never turned into a total length / never auto-run


def test_repeated_spacing_is_not_total_length(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    ev = env.get(f"{B}/components/{post['id']}/evidence", headers=admin).json()
    spacing = next(m for m in ev["measurements"] if m["kind"] == "spacing")
    r = env.post(f"{B}/components/{post['id']}/quantity/run",
                 json={"rule_code": "FENCE_POST.TOTAL_LENGTH", "parameters": {"unit_length": {"measurement_id": spacing["id"]}}}, headers=admin)
    assert r.status_code == 422 and "spacing" in r.json()["detail"]
    sp = env.post(f"{B}/components/{post['id']}/quantity/run", json={"rule_code": "FENCE_POST.SPACING"}, headers=admin).json()
    assert (sp["quantity_type"], sp["quantity_value"], sp["unit"]) == ("SPACING", "2.117", "m")  # information, not a length total


def test_unit_length_from_a_confirmed_length_measurement(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    fence = next(c for c in cs if c["component_type"] == "FENCE")
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    length_mid = fence["source_measurement_ids"][0]
    r = env.post(f"{B}/components/{post['id']}/quantity/run",
                 json={"rule_code": "FENCE_POST.TOTAL_LENGTH", "parameters": {"unit_length": {"measurement_id": length_mid}}}, headers=admin).json()
    # BOTH measurements are recorded: the count (primary input) and the length measurement used as unit length
    assert r["status"] == "CALCULATED" and r["input_measurement_ids"][1] == length_mid
    assert r["input_measurement_ids"][0] == r["measurement_id"] and r["measurement_id"] in post["source_measurement_ids"]
    assert r["formula_trace"] == "10 × 20.461 m = 204.610 m" and [m["kind"] for m in r["source_measurement"]] == ["count", "length"]


def test_missing_parameter_source_is_never_authoritative(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    for spec in ({"value": "2.5", "unit": "m"}, {"value": "2.5", "unit": "m", "source_type": "ENGINEER_INPUT", "source_reference": "  "},
                 {"value": "2.5", "unit": "m", "source_type": "GUESS", "source_reference": "x"}):
        r = env.post(f"{B}/components/{post['id']}/quantity/run",
                     json={"rule_code": "FENCE_POST.TOTAL_LENGTH", "parameters": {"unit_length": spec}}, headers=admin).json()
        assert r["status"] == "REQUIRES_REVIEW" and r["quantity_value"] is None and "nguồn" in r["reason"]
    w = env.post(f"{B}/components/{post['id']}/quantity/run", json={"rule_code": "STEEL_POST.WEIGHT"}, headers=admin)
    assert w.status_code == 422  # a rule of another component type is refused


def test_occluded_row_requires_review_and_never_interpolates(env, admin):
    d, cs = build(env, admin, H.sheet_fence(occlude="gap"), 100)
    confirm_all(env, admin, cs)
    env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin)
    rows = {r["rule_code"]: r for r in env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=admin).json()}
    cnt = rows["FENCE_POST.COUNT"]
    assert cnt["status"] == "REQUIRES_REVIEW" and cnt["quantity_value"] is None and "OCCLUDED" in cnt["reason"]


def test_ambiguous_or_candidate_component_is_not_quantified(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    fence = next(c for c in cs if c["component_type"] == "FENCE")
    env.post(f"{B}/components/{fence['id']}/ambiguous", json={"note": "chưa rõ"}, headers=admin)
    assert env.post(f"{B}/components/{fence['id']}/quantity/run", json={}, headers=admin).status_code == 422
    s = env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin).json()
    assert s["not_confirmed"] == 2 and s["calculated"] == 0 and s["result_ids"] == []


def test_rejected_measurement_blocks_in_runner(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    fence = next(c for c in cs if c["component_type"] == "FENCE")
    env.post(f"{B}/measurements/{fence['source_measurement_ids'][0]}/reject", json={"note": "đo sai"}, headers=admin)
    env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin)
    r = next(x for x in env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=admin).json() if x["rule_code"] == "FENCE.LENGTH")
    assert r["status"] == "BLOCKED" and r["quantity_value"] is None


def test_plan_and_detail_give_one_quantity(env, admin):
    d, cs = build(env, admin, H.sheet_plan_detail(), 10)
    confirm_all(env, admin, cs)
    s = env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin).json()
    assert s["representations_skipped"] == 1  # the detail view is a representation of the plan post
    det = next(c for c in cs if c["page_no"] == 2)
    assert env.post(f"{B}/components/{det['id']}/quantity/run", json={}, headers=admin).status_code == 422


def test_unresolved_duplicates_require_review_not_merge(env, admin):
    """Two confirmed primary components sharing the same 5B measurement: cannot tell -> REQUIRES_REVIEW, nothing deleted."""
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    post = next(c for c in cs if c["component_type"] == "FENCE_POST")
    from app.db import get_db
    from app.main import app
    from app.models import ComponentSource, DrawingComponent
    import uuid
    db = next(app.dependency_overrides[get_db]())
    orig = db.get(DrawingComponent, uuid.UUID(post["id"]))
    twin = DrawingComponent(**{k: getattr(orig, k) for k in ("company_id", "project_id", "drawing_id", "page_id", "page_no", "component_type",
                                                              "component_type_id", "x0", "y0", "x1", "y1", "centroid_x", "centroid_y",
                                                              "view_context", "repeat_group_id")}, status="CONFIRMED", name="twin")
    db.add(twin)
    db.flush()
    for mid in post["source_measurement_ids"]:
        db.add(ComponentSource(company_id=orig.company_id, component_id=twin.id, source_type="measurement", role="count",
                               measurement_id=uuid.UUID(mid)))
    db.commit()
    db.close()
    env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin)
    counts = [r for r in env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=admin).json() if r["rule_code"] == "FENCE_POST.COUNT"]
    assert len(counts) == 2 and all(r["status"] == "REQUIRES_REVIEW" and r["quantity_value"] is None for r in counts)
    assert all("có thể trùng" in r["reason"] for r in counts)
    assert len(env.get(f"{B}/drawings/{d['id']}/components", headers=admin).json()) == 3  # nothing silently deleted


def test_provenance_chain_and_audit(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    confirm_all(env, admin, cs)
    env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=admin)
    r = next(x for x in env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=admin).json() if x["rule_code"] == "FENCE.LENGTH")
    p = env.get(f"{B}/quantity-results/{r['id']}", headers=admin).json()["provenance"]
    assert p["component"]["type"] == "FENCE" and p["measurements"][0]["status"] == "confirmed"
    assert p["geometry_ids"] and p["association_ids"] and p["texts"][0]["original_text"] == "HÀNG RÀO B40"
    assert p["drawing"]["page_no"] == 1 and [a["action"] for a in p["audit"]] == ["quantity_run"]


def test_company_isolation_drawing_endpoints(env, admin):
    d, cs = build(env, admin, H.sheet_fence(), 100)
    other = login(env, "admin@b.test", "pw-admin-2")
    assert env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=other).status_code == 404
    assert env.get(f"{B}/drawings/{d['id']}/quantity-results", headers=other).status_code == 404
    v = login(env, "viewer@a.test", "pw-x")
    assert env.post(f"{B}/drawings/{d['id']}/quantities/run", json={}, headers=v).status_code == 403
    assert env.get(f"{B}/quantity-rules?component_type=bolt", headers=v).json()[0]["rule_code"] == "BOLT.COUNT"


def test_conflict_component_still_needs_confirmed_measurement(env, admin):
    d, cs = build(env, admin, sheet(), 100)
    lin = next(c for c in cs if c["component_type"] == "LINEAR_COMPONENT" and c["status"] == "CONFLICT")
    env.post(f"{B}/components/{lin['id']}/confirm", json={"note": "chấp nhận theo hình học"}, headers=admin)
    r = env.post(f"{B}/components/{lin['id']}/quantity/run", json={"rule_code": "LINEAR_COMPONENT.LENGTH"}, headers=admin).json()
    assert r["status"] == "REQUIRES_REVIEW"  # the 5B measurement itself is not engineer-confirmed yet
