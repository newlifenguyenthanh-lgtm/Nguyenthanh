"""Compares a golden_run result with an independently verified expected file (schema paacc-golden/1).

    python -m tools.golden_compare --expected <expected.json> --run <run.json> [--out report.json]

Classification per expected value: CORRECT, PARTIALLY_CORRECT, INCORRECT, MISSING, AMBIGUOUS,
REQUIRES_ENGINEER_CONFIRMATION (as expected outcome), plus FALSE_POSITIVE for extracted values that
match nothing expected. Percentages are computed ONLY over verified denominators; categories without
verified expectations report counts but no percentage.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

CORRECT, PARTIAL, INCORRECT, MISSING = "CORRECT", "PARTIALLY_CORRECT", "INCORRECT", "MISSING"


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFD", (s or "").replace("đ", "d").replace("Đ", "D").replace("×", "x"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    return re.sub(r"[^A-Z0-9.,=+()/:-]", "", s)


def dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v).replace(",", "."))
    except InvalidOperation:
        return None


def qkey(v) -> str:
    d = dec(v)
    return "" if d is None else str(d.quantize(Decimal("0.0001")))


def same_values(a: list, b: list) -> bool:
    return len(a) == len(b) and all(dec(x) == dec(y) for x, y in zip(a, b))


def pct(counter: Counter, total: int) -> float | None:
    return round(100 * counter[CORRECT] / total, 1) if total else None


def compare(expected: dict, run: dict) -> dict:
    items = run.get("items", [])
    pages = {p["page_no"]: p for p in run.get("drawing", {}).get("pages", [])}
    out: dict = {"document": expected["document"]["file"], "code_commit": run.get("code_commit")}

    # ---- metadata (per page, per field)
    meta_rows, mc = [], Counter()
    for ep in expected.get("pages", []):
        p = pages.get(ep["page_no"], {})
        for field in ("drawing_number", "title", "revision"):
            exp, got = ep.get(field), p.get(field)
            st = CORRECT if norm(exp) == norm(got) else (MISSING if exp and not got else INCORRECT)
            mc[st] += 1
            meta_rows.append({"page": ep["page_no"], "field": field, "expected": exp, "got": got, "status": st})
        exp_scale = ep.get("scale_ratio")
        ratios = sorted({c["ratio"] for c in (p.get("scale_candidates") or [])})
        st = CORRECT if (exp_scale is None and not ratios) or (exp_scale is not None and ratios == [exp_scale]) else \
            (MISSING if exp_scale and not ratios else INCORRECT)
        mc[st] += 1
        meta_rows.append({"page": ep["page_no"], "field": "scale", "expected": exp_scale, "got": ratios, "status": st})
        units = sorted({c["unit"] for c in (p.get("units_candidates") or [])})
        exp_u = ep.get("units")
        st = CORRECT if (exp_u is None and not units) or units == [exp_u] else (MISSING if exp_u and not units else INCORRECT)
        mc[st] += 1
        meta_rows.append({"page": ep["page_no"], "field": "units", "expected": exp_u, "got": units, "status": st})
        st = CORRECT if p.get("kind") == ep.get("kind") else INCORRECT
        mc[st] += 1
        meta_rows.append({"page": ep["page_no"], "field": "page_kind", "expected": ep.get("kind"), "got": p.get("kind"), "status": st})
    out["metadata"] = {"rows": meta_rows, "counts": dict(mc), "total": len(meta_rows), "accuracy_pct": pct(mc, len(meta_rows))}

    # ---- dimensions
    dims = [i for i in items if i["kind"] == "dimension"]
    pool = {i["id"]: i for i in dims}
    dim_rows, dc = [], Counter()
    # pass 0: false-positive traps (exact) - so a trap token is never consumed by a partial match
    fp_traps = []
    for e in expected.get("not_dimensions", []):
        hit = [i for i in pool.values() if i["page_no"] == e["page"] and norm(i["text"]) == norm(e["raw"])]
        fp_traps.append({**e, "status": INCORRECT if hit else CORRECT})
        for h in hit:
            pool.pop(h["id"])
    exp_dims = expected.get("dimensions", [])
    matched: dict[int, tuple] = {}
    for n, e in enumerate(exp_dims):  # pass 1: exact text matches
        got = next((i for i in pool.values() if i["page_no"] == e["page"] and norm(i["text"]) == norm(e["raw"])), None)
        if got:
            matched[n] = (pool.pop(got["id"]), False)
    for n, e in enumerate(exp_dims):  # pass 2: longest partial overlap
        if n in matched:
            continue
        t = norm(e["raw"])
        cands = [i for i in pool.values() if i["page_no"] == e["page"] and norm(i["text"]) and (norm(i["text"]) in t or t in norm(i["text"]))]
        if cands:
            got = max(cands, key=lambda i: len(norm(i["text"])))
            matched[n] = (pool.pop(got["id"]), True)
    for n, e in enumerate(exp_dims):
        got, partial = matched.get(n, (None, False))
        flags = (got or {}).get("data", {}).get("flags") or []
        status = e.get("status", "verified")
        if got is None:
            st = MISSING
        elif status == "ambiguous":
            st = CORRECT if "ambiguous_number" in flags else INCORRECT
        elif status == "requires_engineer":
            st = CORRECT if flags else INCORRECT
        else:
            vals_ok = same_values(got["data"].get("values") or [got["data"].get("diameter")], e["values"])
            unit_ok = (got["data"].get("unit") or None) == e.get("unit")
            kind_ok = e.get("kind") in (None, got["data"].get("type"))
            st = CORRECT if vals_ok and unit_ok and kind_ok and not partial else PARTIAL if vals_ok or partial else INCORRECT
        dc[st] += 1
        dim_rows.append({"page": e["page"], "raw": e["raw"], "expected_status": status, "expected": e.get("values"),
                         "expected_unit": e.get("unit"), "expected_kind": e.get("kind"), "got_text": (got or {}).get("text"),
                         "got": (got or {}).get("data", {}).get("values"), "got_unit": (got or {}).get("data", {}).get("unit"),
                         "got_type": (got or {}).get("data", {}).get("type"), "flags": flags, "status": st})
    out["dimensions"] = {"rows": dim_rows, "counts": dict(dc), "total": len(dim_rows), "accuracy_pct": pct(dc, len(dim_rows)),
                         "false_positive_traps": fp_traps,
                         "false_positives": [{"page": i["page_no"], "text": i["text"], "type": i["data"].get("type")} for i in pool.values()]}

    # ---- materials / specifications
    specs = [i for i in items if i["kind"] == "spec"]
    mat_rows, sc = [], Counter()
    used = set()
    for e in expected.get("materials", []):
        hit = next((i for i in specs if i["id"] not in used and i["page_no"] == e["page"] and norm(e["raw"]) in norm(i["text"])), None)
        if hit:
            used.add(hit["id"])
        st = MISSING if not hit else CORRECT if hit["data"].get("category") == e["category"] else PARTIAL
        sc[st] += 1
        mat_rows.append({**e, "got": (hit or {}).get("data"), "status": st})
    out["materials"] = {"rows": mat_rows, "counts": dict(sc), "total": len(mat_rows), "accuracy_pct": pct(sc, len(mat_rows)),
                        "false_positives": [{"page": i["page_no"], "text": i["text"], "category": i["data"].get("category")}
                                            for i in specs if i["id"] not in used]}

    # ---- BOQ mapping (generated draft, before any human review)
    boq_items = list((run.get("boq_generated") or {}).get("items", []))
    remaining = {i["id"]: i for i in boq_items}
    boq_rows, bc, group_ok = [], Counter(), Counter()
    for e in expected.get("boq_rows", []):
        pg = [i for i in remaining.values() if i["page_no"] == e["page"]]
        full = [i for i in pg if norm(i["description"]) == norm(e["description"])]
        qty = [i for i in pg if dec(i["quantity"]) == dec(e["quantity"]) and (i["unit"] or "").strip() == e["unit"]]
        exact = [i for i in full if i in qty]
        got = (exact or qty or full or [None])[0]
        if got is None:
            st = MISSING
        elif got in exact:
            st = CORRECT
        elif got in qty:
            st = PARTIAL  # quantity + unit right, description lost
        else:
            st = INCORRECT  # description right, quantity/unit wrong
        if got:
            remaining.pop(got["id"])
            gp = got.get("group_path") or []
            if e.get("group"):
                group_ok[CORRECT if gp and gp[-1].get("code") == e["group"] else INCORRECT] += 1
        bc[st] += 1
        boq_rows.append({"page": e["page"], "description": e["description"], "unit": e["unit"], "quantity": e["quantity"],
                         "got_description": (got or {}).get("description"), "got_quantity": (got or {}).get("quantity"),
                         "got_unit": (got or {}).get("unit"), "got_category": (got or {}).get("category"), "status": st})
    out["boq"] = {"rows": boq_rows, "counts": dict(bc), "total": len(boq_rows), "accuracy_pct": pct(bc, len(boq_rows)),
                  "false_positives": [{"description": i["description"], "quantity": i["quantity"], "unit": i["unit"],
                                       "module": i["module"], "flags": [f["code"] for f in i["flags"]]} for i in remaining.values()],
                  "group_context": {"counts": dict(group_ok), "total": sum(group_ok.values()),
                                    "accuracy_pct": pct(group_ok, sum(group_ok.values()))}}

    # ---- duplicate / overlap handling
    dup_rows, uc = [], Counter()
    by_desc = {}
    for i in boq_items:
        by_desc.setdefault((i["page_no"], norm(i["description"]), qkey(i["quantity"])), i)
    for case in expected.get("duplicates", []):
        it = by_desc.get((case["page"], norm(case["description"]), qkey(case["quantity"])))
        codes = [f["code"] for f in (it or {}).get("flags", [])]
        if it is None:
            st = MISSING
        elif case["expect"] == "flag_component_of_parent":
            st = CORRECT if "component_of_parent" in codes else INCORRECT
        elif case["expect"] == "no_duplicate_flag":
            st = CORRECT if "possible_duplicate" not in codes else INCORRECT
        else:
            st = CORRECT if case["expect"] in codes else INCORRECT
        uc[st] += 1
        dup_rows.append({**case, "got_flags": codes, "status": st})
    out["duplicates"] = {"rows": dup_rows, "counts": dict(uc), "total": len(dup_rows), "accuracy_pct": pct(uc, len(dup_rows))}

    # ---- vector geometry (Phase 5A): vector axis runs vs independently derived raster runs
    if expected.get("geometry"):
        from tools.raster_lines import match_axis_lines
        gc, geo_rows = Counter(), []
        for ep in expected["geometry"]["pages"]:
            runs = [{"axis": r["axis"], "pos": float(r["pos"]), "start": float(r["start"]), "end": float(r["end"])}
                    for r in (run.get("geometry_axis_runs") or {}).get(str(ep["page_no"]), run.get("geometry_axis_runs", {}).get(ep["page_no"], []))]
            exp_runs = [r for r in ep["axis_lines"] if not r.get("excluded")]
            m = match_axis_lines(runs, exp_runs, ep.get("tol_pos", 1.0), ep.get("tol_end", 2.0))
            gc[CORRECT] += m["matched"]
            gc[MISSING] += len(m["raster_only"])
            geo_rows.append({"page": ep["page_no"], "expected": len(exp_runs), "matched": m["matched"],
                             "missing": m["raster_only"], "vector_only": m["vector_only"]})
        total = sum(r["expected"] for r in geo_rows)
        out["geometry"] = {"rows": geo_rows, "counts": dict(gc), "total": total, "accuracy_pct": pct(gc, total),
                           "false_positives": [v for r in geo_rows for v in r["vector_only"]]}
    # ---- text <-> geometry association (Phase 5C): invariants checkable on ANY real document
    #      every text that must never be associated (table / title block / scale / revision / page number / unknown)
    #      has zero associations, and nothing is ever auto-confirmed.
    if expected.get("associations") is not None and run.get("text_blocks") is not None:
        from app.association.engine import EXCLUDED_TYPES
        ac, rows, fps = Counter(), [], []
        for page, blocks in run["text_blocks"].items():
            assoc = run.get("associations", {}).get(page, [])
            linked = {a["text_block_id"] for a in assoc}
            for b in blocks:
                if b["text_type"] in EXCLUDED_TYPES or {"in_table", "in_title_block", "page_number"} & set(b["flags"]):
                    ok = b["id"] not in linked
                    ac[CORRECT if ok else INCORRECT] += 1
                    if not ok:
                        fps.append({"page": page, "text_type": b["text_type"]})
            rows.append({"page": page, "text_blocks": len(blocks), "associations": len(assoc),
                         "auto_confirmed": sum(1 for a in assoc if a["status"] == "CONFIRMED"),
                         "by_status": dict(Counter(a["status"] for a in assoc))})
        total = sum(ac.values())
        mx = expected["associations"].get("max_candidates")
        out["associations"] = {"rows": rows, "counts": dict(ac), "total": total, "accuracy_pct": pct(ac, total),
                               "false_positives": fps, "auto_confirmed": sum(r["auto_confirmed"] for r in rows),
                               "candidates": sum(r["associations"] for r in rows),
                               "candidates_within_expected": mx is None or sum(r["associations"] for r in rows) <= mx}
    out["pipeline_steps"] = run.get("steps")
    out["summary"] = {k: {"correct": out[k]["counts"].get(CORRECT, 0), "total": out[k]["total"], "accuracy_pct": out[k]["accuracy_pct"]}
                      for k in ("metadata", "dimensions", "materials", "boq", "duplicates", "geometry", "associations") if k in out}
    out["summary"]["dimension_false_positives"] = len(out["dimensions"]["false_positives"])
    out["summary"]["boq_false_positive_items"] = len(out["boq"]["false_positives"])
    out["summary"]["group_context"] = out["boq"]["group_context"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True, type=Path)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    res = compare(json.loads(a.expected.read_text()), json.loads(a.run.read_text()))
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
