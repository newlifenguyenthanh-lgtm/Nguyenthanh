"""Real construction drawing validation harness (5A -> 5E-2) – runs the EXISTING pipeline, never a parallel one.

    python -m tools.validate_real_drawing --pdf <drawing.pdf> --out <dir OUTSIDE the repo>
        [--decisions decisions.json] [--manual-ref manual_qs.csv]

* Isolated temporary SQLite DB + storage; the input PDF is read, never modified or copied into the repository.
* Nothing is auto-confirmed. Without a decisions file the run stops at candidates: no component is CONFIRMED, so no
  authoritative quantity exists – that is the correct result, not a failure.
* Engineer decisions (decisions.json) are keyed by stable fingerprints printed in the first report:
    {"reviewer": "Name (QS)",
     "scale": {"1": 100},                                     # page -> ratio CONFIRMED by the engineer
     "scale_regions": [{"page": 1, "bbox": [x0,y0,x1,y1], "ratio": 20, "label": "CHI TIẾT A"}],
     "confirm_components": ["p1:FENCE:80,292,660,304"],
     "reject_components": {"p1:BOLT:...": "reason"},
     "confirm_measurements_of": ["p1:FENCE:80,292,660,304"],  # engineer checked this component's 5B measurements
     "parameters": {"p1:STEEL_POST:...": {"unit_length": {"value": "2.5", "unit": "m",
                    "source_type": "DRAWING_NOTE", "source_reference": "Sheet 03 note 2"}}}}
* manual_qs.csv (optional): item,rule_code,unit,quantity  (rule_code may be a component type instead, e.g. FENCE)
* Output (Markdown + JSON) contains data derived from the drawing: keep it OUT of git.
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

B = "/api/v1"
TOL_ABS, TOL_REL = Decimal("0.01"), Decimal("0.005")


def fingerprint(c: dict) -> str:
    x0, y0, x1, y1 = c["bbox"]
    return f"p{c['page_no']}:{c['component_type']}:{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}"


def _repo_root() -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=Path(__file__).parent)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def _client(tmp: Path):
    os.environ.update(PAACC_DATABASE_URL=f"sqlite:///{tmp}/validate.db", PAACC_STORAGE_DIR=str(tmp / "store"))
    os.environ.setdefault("PAACC_JWT_SECRET", "validate-run-local-secret-0123456789")
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.cli import create_admin, create_user
    from app.db import get_db
    from app.main import app
    from app.models import Base
    engine = create_engine(os.environ["PAACC_DATABASE_URL"])
    Base.metadata.create_all(engine)

    def override():
        with Session(engine, expire_on_commit=False) as s:
            yield s
    app.dependency_overrides[get_db] = override
    with Session(engine) as s:
        create_admin(s, "Validation", "admin@validate.local", "validate-admin-pw")
        create_user(s, "admin@validate.local", "qs@validate.local", "qs_engineer", "validate-qs-pw1")
    c = TestClient(app)
    tok = c.post(f"{B}/auth/login", json={"email": "qs@validate.local", "password": "validate-qs-pw1"}).json()["access_token"]
    return c, {"Authorization": f"Bearer {tok}"}, app


def _ok(r, what: str, errors: list) -> dict | list | None:
    if r.status_code >= 400:
        errors.append(f"{what}: HTTP {r.status_code} {r.text[:300]}")
        return None
    return r.json()


def run(pdf: Path, out: Path, decisions: dict | None = None, manual_ref: Path | None = None) -> dict:
    data = pdf.read_bytes()
    t_all = time.perf_counter()
    errors, warnings, timings = [], [], {}
    tmp = Path(tempfile.mkdtemp(prefix="paacc-validate-"))
    c, h, app = _client(tmp)
    try:
        # ---- 5A..5D: the existing processing task (ingestion, analysis, geometry, associations, components)
        t = time.perf_counter()
        doc = _ok(c.post(f"{B}/documents", data={"title": pdf.stem, "kind": "drawing"},
                         files={"file": (pdf.name, data, "application/pdf")}, headers=h), "upload", errors)
        d = _ok(c.post(f"{B}/drawings", json={"document_id": doc["id"]}, headers=h), "process", errors) if doc else None
        timings["processing_5A_to_5D"] = time.perf_counter() - t
        if not d or d.get("status") != "processed":
            errors.append(f"processing status: {d and d.get('status')} {d and d.get('error_message')}")
            return _finish(pdf, data, out, d, {}, errors, warnings, timings, t_all, decisions, manual_ref, c, h)
        did = d["id"]
        # ---- engineer scale decisions only (never inferred)
        dec = decisions or {}
        for page, ratio in (dec.get("scale") or {}).items():
            _ok(c.post(f"{B}/drawings/{did}/pages/{int(page)}/calibration",
                       json={"scale_ratio": int(ratio), "note": f"engineer decision file ({dec.get('reviewer', '?')})"}, headers=h),
                f"scale p{page}", errors)
        for sr in dec.get("scale_regions") or []:
            r = _ok(c.post(f"{B}/drawings/{did}/scale-regions", json={"page_no": sr["page"], "bbox": sr["bbox"],
                                                                     "scale_ratio": sr["ratio"], "label": sr.get("label", "")}, headers=h),
                    "scale region", errors)
            if r:
                _ok(c.post(f"{B}/scale-regions/{r['id']}/confirm", json={"note": f"engineer ({dec.get('reviewer', '?')})"}, headers=h),
                    "confirm region", errors)
        if dec.get("scale") or dec.get("scale_regions"):  # re-derive 5C/5D on the confirmed scale
            t = time.perf_counter()
            _ok(c.post(f"{B}/drawings/{did}/associations/run", headers=h), "5C rerun", errors)
            timings["5C_rerun"] = time.perf_counter() - t
            t = time.perf_counter()
            _ok(c.post(f"{B}/drawings/{did}/components/run", headers=h), "5D rerun", errors)
            timings["5D_rerun"] = time.perf_counter() - t
        comps = _ok(c.get(f"{B}/drawings/{did}/components", headers=h), "components", errors) or []
        by_fp = {fingerprint(x): x for x in comps}
        applied = {"confirmed_components": [], "rejected_components": [], "confirmed_measurements": [], "unknown_fingerprints": []}
        for fp in dec.get("confirm_components") or []:
            x = by_fp.get(fp)
            if not x:
                applied["unknown_fingerprints"].append(fp)
                continue
            if x["status"] == "CANDIDATE":
                c.post(f"{B}/components/{x['id']}/review", json={"note": "engineer decision file"}, headers=h)
            if _ok(c.post(f"{B}/components/{x['id']}/confirm", json={"note": f"engineer decision file ({dec.get('reviewer', '?')})"},
                          headers=h), f"confirm {fp}", errors):
                applied["confirmed_components"].append(fp)
        for fp, why in (dec.get("reject_components") or {}).items():
            x = by_fp.get(fp)
            if x and _ok(c.post(f"{B}/components/{x['id']}/reject", json={"note": why}, headers=h), f"reject {fp}", errors):
                applied["rejected_components"].append(fp)
            elif not x:
                applied["unknown_fingerprints"].append(fp)
        for fp in dec.get("confirm_measurements_of") or []:
            x = by_fp.get(fp)
            if not x:
                applied["unknown_fingerprints"].append(fp)
                continue
            for mid in x["source_measurement_ids"]:
                if _ok(c.post(f"{B}/measurements/{mid}/confirm", json={"note": f"engineer decision file ({dec.get('reviewer', '?')})"},
                              headers=h), f"confirm measurement {mid[:8]}", errors):
                    applied["confirmed_measurements"].append(mid)
        if applied["unknown_fingerprints"]:
            warnings.append(f"{len(applied['unknown_fingerprints'])} fingerprint(s) in the decision file not found in this run")
        # ---- 5E: whole-drawing quantity runner (only CONFIRMED components produce results)
        params = {by_fp[fp]["id"]: p for fp, p in (dec.get("parameters") or {}).items() if fp in by_fp}
        t = time.perf_counter()
        qsum = _ok(c.post(f"{B}/drawings/{did}/quantities/run", json={"parameters": params}, headers=h), "5E run", errors) or {}
        timings["5E_quantities"] = time.perf_counter() - t
        return _finish(pdf, data, out, d, {"applied": applied, "quantity_summary": qsum}, errors, warnings, timings, t_all,
                       decisions, manual_ref, c, h)
    finally:
        app.dependency_overrides.clear()


def _finish(pdf, data, out, d, extra, errors, warnings, timings, t_all, decisions, manual_ref, c, h) -> dict:
    rep: dict = {"file": {"name": pdf.name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                 "code_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                               cwd=Path(__file__).parent).stdout.strip(),
                 "decisions": {"provided": bool(decisions), "reviewer": (decisions or {}).get("reviewer")}, **extra,
                 "errors": errors, "warnings": warnings}
    if d and d.get("id"):
        did = d["id"]
        det = c.get(f"{B}/drawings/{did}", headers=h).json()
        geo = c.get(f"{B}/drawings/{did}/geometry/summary", headers=h).json()
        items = c.get(f"{B}/drawings/{did}/items?limit=5000", headers=h).json()
        if not isinstance(items, list):
            errors.append(f"items: {items}")
            items = []
        pages = []
        for p in det["pages"]:
            n = p["page_no"]
            gp = next((g for g in geo["pages"] if g["page_no"] == n), {})
            tb = c.get(f"{B}/drawings/{did}/pages/{n}/text-blocks", headers=h).json()
            asc = c.get(f"{B}/drawings/{did}/pages/{n}/associations", headers=h).json()
            pages.append({"page_no": n, "kind": p["kind"], "rotation": p["rotation"], "size_pt": [p["width_pt"], p["height_pt"]],
                          "ocr_used": p["ocr_used"], "ocr_confidence": p["ocr_mean_confidence"], "warnings": p["warnings"],
                          "drawing_number": p["drawing_number"], "title": p["title"], "revision": p["revision"],
                          "view_types": [v["value"] for v in p.get("view_types") or []],
                          "disciplines": [v["value"] for v in p.get("disciplines") or []],
                          "scale_status": p["scale_status"], "scale_ratio": p["scale_ratio"],
                          "scale_candidates": [x.get("raw") for x in p.get("scale_candidates") or []],
                          "items_by_kind": dict(Counter(i["kind"] for i in items if i["page_no"] == n)),
                          "geometry_status": gp.get("geometry_status"), "geometry_by_kind": (gp.get("stats") or {}).get("by_kind"),
                          "geometry_stats": {k: v for k, v in (gp.get("stats") or {}).items() if k not in ("association", "components", "by_kind")},
                          "stage_stats_5C": (gp.get("stats") or {}).get("association"), "stage_stats_5D": (gp.get("stats") or {}).get("components"),
                          "text_blocks_by_type": dict(Counter(b["text_type"] for b in tb)),
                          "associations_by_status": dict(Counter(a["status"] for a in asc))})
        comps = c.get(f"{B}/drawings/{did}/components", headers=h).json()
        ms = c.get(f"{B}/drawings/{did}/measurements", headers=h).json()
        mby = {m["id"]: m for m in ms}
        qrs = c.get(f"{B}/drawings/{did}/quantity-results", headers=h).json()
        qprov = {q["id"]: c.get(f"{B}/quantity-results/{q['id']}", headers=h).json()["provenance"] for q in qrs}
        crow = []
        for x in comps:
            ev = c.get(f"{B}/components/{x['id']}/evidence", headers=h).json()
            mine = [q for q in qrs if q["component_id"] == x["id"]]
            crow.append({"fingerprint": fingerprint(x), "page": x["page_no"], "component_id": x["id"], "type": x["component_type"],
                         "description": x["description"], "specification": x["specification"], "material": x["material"],
                         "view_context": x["view_context"], "confidence": x["recognition_confidence"], "band": x["confidence_band"],
                         "scores": x["scores"], "state": x["status"], "review_required": x["status"] != "CONFIRMED",
                         "representation_of": x["representation_of_id"], "repeat_group": (ev.get("repeat_group") or {}).get("pattern_status"),
                         "geometry_ids": x["source_geometry_ids"], "text_ids": x["source_text_ids"],
                         "association_ids": x["source_association_ids"], "measurement_ids": x["source_measurement_ids"],
                         "measurements": [{"kind": mby[m]["kind"], "value_real": mby[m]["value_real"], "real_unit": mby[m]["real_unit"],
                                           "value_paper": mby[m]["value_paper"], "status": mby[m]["status"],
                                           "scale_source": mby[m]["scale_source"]} for m in x["source_measurement_ids"] if m in mby],
                         "reasons": (ev.get("detail") or {}).get("reasons", []) + (ev.get("detail") or {}).get("conflicts", []) +
                                    (ev.get("detail") or {}).get("ambiguous", []),
                         "quantities": [{"rule": q["rule_code"], "trace": q["formula_trace"], "value": q["quantity_value"],
                                         "unit": q["unit"], "status": q["status"]} for q in mine]})
        rep.update(pages=pages, components=crow, measurements={"total": len(ms), "by_status": dict(Counter(m["status"] for m in ms)),
                                                               "real_value": sum(1 for m in ms if m["value_real"] is not None),
                                                               "paper_only": sum(1 for m in ms if m["value_real"] is None)},
                   quantities=[{**q, "provenance": qprov[q["id"]]} for q in qrs])
    rep["timings_s"] = {k: round(v, 3) for k, v in {**timings, "total": time.perf_counter() - t_all}.items()}
    if rep.get("pages"):
        rep["timings_s"]["per_page"] = round(rep["timings_s"]["total"] / len(rep["pages"]), 3)
    rep["manual_comparison"] = compare_manual(rep.get("quantities", []), rep.get("components", []), manual_ref)
    rep["result"] = verdict(rep)
    out.mkdir(parents=True, exist_ok=True)
    stem = pdf.stem
    (out / f"{stem}.validation.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    (out / f"{stem}.validation.md").write_text(markdown(rep))
    return rep


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


def compare_manual(qrs: list, comps: list, manual_ref: Path | None) -> dict:
    if not manual_ref:
        return {"reference": "MANUAL_REFERENCE: NOT_AVAILABLE", "rows": [],
                "needs_engineer_confirmation": [c["fingerprint"] for c in comps if c["state"] != "CONFIRMED"]}
    rows = []
    for r in csv.DictReader(manual_ref.open(encoding="utf-8-sig")):
        key, unit, ref = r["rule_code"].strip(), r["unit"].strip(), _dec(r["quantity"])
        match = [q for q in qrs if (q["rule_code"] == key or q.get("component_type") == key) and q["unit"] == unit]
        calc = [q for q in match if q["status"] == "CALCULATED" and _dec(q["quantity_value"]) is not None]
        pending = [c for c in comps if c["type"] == key.split(".")[0] and c["state"] != "CONFIRMED"]
        if calc and len(calc) == len(match):
            got = sum((_dec(q["quantity_value"]) for q in calc), Decimal(0))
            diff = got - ref if ref is not None else None
            ok = diff is not None and abs(diff) <= max(TOL_ABS, abs(ref) * TOL_REL)
            status = "CORRECT" if ok else "WRONG"
            rows.append({"item": r["item"], "key": key, "unit": unit, "manual": str(ref), "paacc": f"{got.normalize():f}",
                         "difference": None if diff is None else f"{diff.normalize():f}", "status": status})
        elif match or pending:
            rows.append({"item": r["item"], "key": key, "unit": unit, "manual": str(ref), "paacc": None, "difference": None,
                         "status": "NEEDS_REVIEW"})
        else:
            rows.append({"item": r["item"], "key": key, "unit": unit, "manual": str(ref), "paacc": None, "difference": None,
                         "status": "CANNOT_TAKEOFF"})
    return {"reference": str(manual_ref.name), "rows": rows, "counts": dict(Counter(x["status"] for x in rows))}


def verdict(rep: dict) -> dict:
    """Mechanical stage verdicts (documented in the report). NOT_EXERCISED / NOT_VALIDATED are reported as such –
    never upgraded to PASS."""
    pages = rep.get("pages") or []
    if not pages:
        return {"5A PDF ingestion": "FAIL"}
    kinds = Counter(p["kind"] for p in pages)
    v = {}
    v["5A PDF ingestion"] = "PASS" if not rep["errors"] and all(p["kind"] in ("vector", "mixed", "scanned") for p in pages) else "PARTIAL"
    vec = [p for p in pages if p["kind"] in ("vector", "mixed")]
    ext = [p for p in vec if p["geometry_status"] == "extracted"]
    v["5B Geometry"] = "NOT_EXERCISED (no vector page)" if not vec else "PASS" if len(ext) == len(vec) else "PARTIAL" if ext else "FAIL"
    m = rep.get("measurements") or {}
    v["5B Measurement"] = ("NOT_EXERCISED (no measurement)" if not m.get("total") else
                           "PASS" if m.get("paper_only") == 0 else "PARTIAL (paper-only: scale not confirmed)" if m.get("real_value") else
                           "PARTIAL (paper-only: no confirmed scale)")
    assoc = sum(sum(p["associations_by_status"].values()) for p in pages)
    v["5C Text-Geometry"] = "NOT_EXERCISED (no associable text)" if assoc == 0 else "PASS (candidates; engineer review pending)"
    comps = rep.get("components") or []
    conf = [x for x in comps if x["state"] == "CONFIRMED"]
    v["5D Component Recognition"] = ("NOT_EXERCISED (0 candidates)" if not comps else
                                     "PASS" if conf and len(conf) == len(comps) else "PARTIAL (candidates; engineer review pending)")
    qs = rep.get("quantities") or []
    calc = [q for q in qs if q["status"] == "CALCULATED"]
    q_state = ("NOT_EXERCISED (no CONFIRMED component)" if not qs else "PASS" if len(calc) == len(qs) else
               "PARTIAL" if calc else "PARTIAL (all results REQUIRES_REVIEW/BLOCKED)")
    v["5E-1 Quantity Foundation"] = q_state
    v["5E-2 Quantity Rules"] = q_state
    mc = rep.get("manual_comparison") or {}
    if not mc.get("rows"):
        v["End-to-end Quantity"] = "NOT_VALIDATED (MANUAL_REFERENCE: NOT_AVAILABLE)"
    else:
        cnt = mc["counts"]
        v["End-to-end Quantity"] = "PASS" if cnt.get("CORRECT", 0) == len(mc["rows"]) else "FAIL" if cnt.get("WRONG") else "PARTIAL"
    trace_ok = all(q["provenance"]["component"]["id"] and q["provenance"]["measurements"] and q["provenance"]["geometry_ids"]
                   and q["provenance"]["drawing"]["page_no"] for q in calc)
    v["Traceability"] = "NOT_EXERCISED (no calculated quantity)" if not calc else "PASS" if trace_ok else "FAIL"
    v["Regression"] = "run scripts/check.sh (not part of this harness)"
    v["_page_kinds"] = dict(kinds)
    return v


def markdown(rep: dict) -> str:
    L = ["# Real drawing validation report", "",
         "> Generated by `tools/validate_real_drawing.py`. Contains data derived from the drawing – **do not commit**.", ""]
    f = rep["file"]
    pages = rep.get("pages") or []
    kinds = Counter(p["kind"] for p in pages)
    L += ["## A. File summary", "", "| Field | Value |", "|---|---|", f"| File | {f['name']} |", f"| Size | {f['size_bytes']:,} bytes |",
          f"| SHA-256 | `{f['sha256'][:16]}…` |", f"| Pages | {len(pages)} |",
          f"| Vector / scanned / mixed / other | {kinds.get('vector', 0)} / {kinds.get('scanned', 0)} / {kinds.get('mixed', 0)} / "
          f"{len(pages) - kinds.get('vector', 0) - kinds.get('scanned', 0) - kinds.get('mixed', 0)} |",
          f"| Processing time | {rep['timings_s'].get('total')} s ({rep['timings_s'].get('per_page', '–')} s/page) |",
          f"| Code commit | {rep['code_commit']} |",
          f"| Engineer decisions | {'yes – ' + str(rep['decisions']['reviewer']) if rep['decisions']['provided'] else 'none (candidates only)'} |",
          f"| Errors | {len(rep['errors'])} |", f"| Warnings | {len(rep['warnings'])} |", ""]
    for e in rep["errors"]:
        L.append(f"- ERROR: {e}")
    for w in rep["warnings"]:
        L.append(f"- WARNING: {w}")
    L += ["", "### Pages", "", "| Page | Kind | No. | Title | Rev | Views | Scale | Geometry | Items | Text types | Assoc. |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in pages:
        L.append(f"| {p['page_no']} | {p['kind']} | {p['drawing_number'] or '–'} | {p['title'] or '–'} | {p['revision'] or '–'} | "
                 f"{', '.join(p['view_types']) or '–'} | {p['scale_status']}{' 1:' + str(p['scale_ratio']) if p['scale_ratio'] else ''} | "
                 f"{p['geometry_status']} {p['geometry_by_kind'] or ''} | {p['items_by_kind']} | {p['text_blocks_by_type']} | "
                 f"{p['associations_by_status']} |")
    comps, qs, m = rep.get("components") or [], rep.get("quantities") or [], rep.get("measurements") or {}
    t = rep["timings_s"]
    L += ["", "## B. Stage summary", "", "| Stage | Output | Review | Blocked | Time (s) |", "|---|---|---|---|---|",
          f"| 5A–5D processing | {len(pages)} pages | – | – | {t.get('processing_5A_to_5D', '–')} |",
          f"| 5B measurement | {m.get('total', 0)} ({m.get('real_value', 0)} real / {m.get('paper_only', 0)} paper-only) | "
          f"{m.get('by_status', {}).get('computed', 0)} unconfirmed | {m.get('by_status', {}).get('rejected', 0)} rejected | – |",
          f"| 5C associations | {sum(sum(p['associations_by_status'].values()) for p in pages)} | "
          f"{sum(p['associations_by_status'].get(s, 0) for p in pages for s in ('CANDIDATE', 'REVIEW_REQUIRED', 'AMBIGUOUS', 'CONFLICT'))} | – | "
          f"{t.get('5C_rerun', '(in processing)')} |",
          f"| 5D components | {len(comps)} | {sum(1 for c in comps if c['state'] != 'CONFIRMED')} | – | {t.get('5D_rerun', '(in processing)')} |",
          f"| 5E quantities | {len(qs)} | {sum(1 for q in qs if q['status'] == 'REQUIRES_REVIEW')} | "
          f"{sum(1 for q in qs if q['status'] == 'BLOCKED')} | {t.get('5E_quantities', '–')} |", ""]
    if rep.get("quantity_summary"):
        L += [f"5E runner summary: `{ {k: v for k, v in rep['quantity_summary'].items() if k != 'result_ids'} }`", ""]
    L += ["## C. Component validation", "", "| Fingerprint | Page | Type | Description | Spec | State | Conf. | View | Measurements | Quantity | Review |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in comps:
        meas = "; ".join(f"{mm['kind']}={mm['value_real'] or mm['value_paper'] + ' (paper)'} {mm['real_unit'] or ''} [{mm['status']}]"
                         for mm in x["measurements"]) or "–"
        qty = "; ".join(f"{q['rule']}: {q['trace'] or '—'} [{q['status']}]" for q in x["quantities"]) or "–"
        L.append(f"| `{x['fingerprint']}` | {x['page']} | {x['type']} | {x['description'][:40]} | {x['specification'][:30]} | {x['state']} | "
                 f"{x['confidence']} {x['band']} | {x['view_context']} | {meas} | {qty} | {'YES' if x['review_required'] else 'no'} |")
    if not comps:
        L.append("| – | – | no component candidate | | | | | | | | |")
    L += ["", "## D. Quantity provenance", ""]
    for q in qs:
        p = q["provenance"]
        L += [f"- **{q.get('component_type')} · {q['rule_code'] or q['calculation_method']}** → {q['formula_trace'] or '—'} "
              f"**[{q['status']}]** {q['reason'] or ''}",
              f"  - component `{p['component']['id'][:8]}` ({p['component']['status']}) → measurements "
              + ", ".join(f"{mm['kind']}={mm['value_real']} {mm['real_unit'] or ''} ({mm['status']}, scale {mm['scale_source']})" for mm in p["measurements"])
              + f" → geometry {len(p['geometry_ids'])} → text {[t['original_text'] for t in p['texts']]} → associations {len(p['association_ids'])}"
              + f" → page {p['drawing']['page_no']}"]
    if not qs:
        L.append("No quantity result: no component is CONFIRMED (engineer decisions required). This is the expected behaviour, "
                 "not an engine failure.")
    mc = rep["manual_comparison"]
    L += ["", "## E. Manual QS comparison", "", f"Reference: **{mc['reference']}**", ""]
    if mc["rows"]:
        L += ["| Item | Key | Manual QS | PAACC | Difference | Status |", "|---|---|---:|---:|---:|---|"]
        L += [f"| {r['item']} | {r['key']} | {r['manual']} {r['unit']} | {r['paacc'] or '—'} | {r['difference'] or '—'} | {r['status']} |"
              for r in mc["rows"]]
    else:
        L += ["No accuracy is claimed. Components needing engineer confirmation:", ""]
        L += [f"- `{fp}`" for fp in mc.get("needs_engineer_confirmation", [])] or ["- (none)"]
    L += ["", "## REAL DRAWING VALIDATION RESULT", "", "| Stage | Result |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in rep["result"].items() if not k.startswith("_")]
    L += ["", "Verdict rules: NOT_EXERCISED / NOT_VALIDATED are never counted as PASS; End-to-end PASS requires a manual QS reference "
          "with every item CORRECT (|diff| ≤ max(0.01, 0.5 %)) and full provenance.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--decisions", type=Path)
    ap.add_argument("--manual-ref", type=Path)
    a = ap.parse_args(argv)
    root = _repo_root()
    if root and a.out.resolve().is_relative_to(root) and os.environ.get("PAACC_VALIDATE_ALLOW_IN_REPO") != "1":
        print(f"Refusing to write drawing-derived results inside the repository ({root}). Use a directory outside git.", file=sys.stderr)
        return 2
    if not a.pdf.is_file():
        print(f"PDF not found: {a.pdf}", file=sys.stderr)
        return 2
    rep = run(a.pdf, a.out, json.loads(a.decisions.read_text()) if a.decisions else None, a.manual_ref)
    print(f"Report: {a.out / (a.pdf.stem + '.validation.md')}")
    for k, v in rep["result"].items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
