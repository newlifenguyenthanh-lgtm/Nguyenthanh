"""Persists rule-based analysis results for a processed drawing (Milestone 4B)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Drawing, DrawingPage, ExtractedItem
from app.pdf import analysis as A
from app.text.encoding import detect as detect_encoding


def _item(d: Drawing, f: A.Finding, kind: str | None = None) -> ExtractedItem:
    x0, y0, x1, y1 = f.line.bbox
    return ExtractedItem(company_id=d.company_id, drawing_id=d.id, page_no=f.line.page_no, kind=kind or f.kind,
                         text=f.raw[:4000], x0=x0, y0=y0, x1=x1, y1=y1, source="analysis", confidence=f.confidence,
                         data={**f.data, "from_item_id": f.line.id, "from_source": f.line.source, "flags": f.flags})


def _region(d: Drawing, page_no: int, bbox, region_type: str, ids: list[str], conf: float) -> ExtractedItem:
    return ExtractedItem(company_id=d.company_id, drawing_id=d.id, page_no=page_no, kind="region", text=region_type,
                         x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3], source="analysis", confidence=conf,
                         data={"region_type": region_type, "item_ids": ids})


def analyze_drawing(db: Session, d: Drawing, _extraction=None) -> None:
    db.flush()
    rows = list(db.scalars(select(ExtractedItem).where(ExtractedItem.drawing_id == d.id)))
    texts = [r for r in rows if r.kind == "text"]
    tables = [r for r in rows if r.kind == "table"]
    pages = {p.page_no: p for p in db.scalars(select(DrawingPage).where(DrawingPage.drawing_id == d.id))}
    all_lines: list[A.Line] = []
    all_dims: list[A.Finding] = []
    for page_no, page in sorted(pages.items()):
        legacy = {}
        for r in texts:  # 5A.1: legacy Vietnamese encodings - detection only, original text untouched
            if r.page_no == page_no:
                g = detect_encoding(r.text)
                if g.suspicious:
                    r.data = {**(r.data or {}), "encoding": g.as_dict()}
                    legacy[g.encoding] = legacy.get(g.encoding, 0) + 1
        if legacy:
            page.warnings = (page.warnings or []) + [f"legacy_encoding_suspected:{k}:{v}" for k, v in sorted(legacy.items())]
        lines = [A.Line(str(r.id), r.page_no, r.text, (r.x0, r.y0, r.x1, r.y1), r.source, r.confidence)
                 for r in texts if r.page_no == page_no]
        all_lines += lines
        page_tables = [t for t in tables if t.page_no == page_no]
        for t in page_tables:  # classify first: bare numbers inside a schedule are quantities, not dimensions
            t.data = {**(t.data or {}), **A.classify_table((t.data or {}).get("rows", []))}
        schedule_boxes = [(t.x0, t.y0, t.x1, t.y1) for t in page_tables if t.data.get("table_type") == "material_schedule"]
        for ln in lines:
            cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
            in_schedule = any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in schedule_boxes)
            for f in A.find_dimensions(ln):
                if in_schedule and f.data.get("type") == "bare_number":
                    continue
                if in_schedule:
                    f.data["in_schedule_table"] = True
                db.add(_item(d, f))
                if f.kind == "dimension":
                    all_dims.append(f)
            for f in A.find_specs(ln) + A.find_symbols(ln):
                db.add(_item(d, f))
        tb = A.title_block(lines)
        fields = tb["fields"]
        page.title_fields = fields
        page.drawing_number = fields.get("drawing_number", {}).get("value")
        page.title = fields.get("title", {}).get("value")
        page.revision = fields.get("revision", {}).get("value")
        page.scale_candidates = tb["scale_candidates"]
        page.scale_status = A.scale_status(tb["scale_candidates"], tb["nts_item_ids"])
        page.units_candidates = tb["unit_candidates"]
        page.units_status = A.units_status(tb["unit_candidates"])
        page.scale_ratio, page.units = None, None  # never auto-confirmed
        schedule = False
        for t in page_tables:
            schedule = schedule or t.data.get("table_type") == "material_schedule"
            if t.data.get("table_type") == "material_schedule":
                db.add(_region(d, page_no, (t.x0, t.y0, t.x1, t.y1), "schedule_table", [str(t.id)], 0.8))
        cls = A.classify(page.title, page.drawing_number, " ".join(ln.text for ln in lines), schedule)
        page.disciplines, page.view_types = cls["disciplines"], cls["view_types"]
        if fields:
            boxes = [f["bbox"] for f in fields.values()] + [
                next((list(ln.bbox) for ln in lines if ln.id == c["item_id"]), None) for c in tb["scale_candidates"] + tb["unit_candidates"] if c.get("labeled", True)]
            boxes = [b for b in boxes if b]
            bb = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
            db.add(_region(d, page_no, bb, "title_block", sorted({i for f in fields.values() for i in f["item_ids"]}), 0.8))
        for n in A.notes_regions(lines):
            db.add(_region(d, page_no, n["bbox"], "notes", n["item_ids"], 0.6))
    findings = A.duplicate_findings(all_lines, all_dims)
    numbers = [(p.page_no, p.drawing_number) for p in pages.values() if p.drawing_number]
    seen: dict[str, int] = {}
    for page_no, num in numbers:
        key = A.fold(num).replace(" ", "")
        if key in seen:
            findings.append({"type": "same_drawing_number_twice", "severity": "warning", "drawing_number": num, "pages": [seen[key], page_no]})
        seen[key] = page_no
    findings += related_revisions(db, d, pages.values())
    if d.duplicate_of_drawing_id:
        findings.append({"type": "duplicate_file", "severity": "warning", "drawing_id": str(d.duplicate_of_drawing_id)})
    d.findings = findings


def related_revisions(db: Session, d: Drawing, pages) -> list[dict]:
    """Same drawing number found in other processed drawings of the company -> revision relationship."""
    out = []
    for p in pages:
        if not p.drawing_number:
            continue
        others = db.execute(select(DrawingPage, Drawing).join(Drawing, Drawing.id == DrawingPage.drawing_id).where(
            DrawingPage.company_id == d.company_id, DrawingPage.drawing_number == p.drawing_number,
            DrawingPage.drawing_id != d.id, Drawing.status == "processed")).all()
        for op, od in others:
            mine, theirs = A.revision_rank(p.revision), A.revision_rank(op.revision)
            if od.sha256 == d.sha256:
                rel = "identical_file"
            elif p.revision and p.revision == op.revision:
                rel = "conflict_same_revision_different_content"
            elif mine is not None and theirs is not None and type(mine[0]) is type(theirs[0]) and mine[0] == theirs[0]:
                rel = "newer_than" if mine > theirs else "older_than"
            else:
                rel = "different_revision_unordered"
            out.append({"type": "revision", "severity": "warning" if rel.startswith("conflict") else "info",
                        "relation": rel, "page_no": p.page_no, "drawing_number": p.drawing_number,
                        "this_revision": p.revision, "other_revision": op.revision,
                        "other_drawing_id": str(od.id), "other_page_no": op.page_no})
    return out
