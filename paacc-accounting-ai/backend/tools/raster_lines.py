"""Independent raster cross-check for vector geometry (Phase 5A validation).

Renders a page to pixels and finds long horizontal/vertical dark runs. This channel never looks at the PDF's
vector operators, so agreement with the vector extractor is real evidence, not a circular check.
Positions are returned in DISPLAY points (same space as stored geometry).
"""
import numpy as np
import pymupdf


def raster_axis_lines(data: bytes, page_no: int, dpi: int = 288, min_len_pt: float = 15.0, dark: int = 200) -> dict:
    """dark=200 keeps anti-aliased hairlines (a 0.12 pt rule renders as grey ~190); min_len filters glyph strokes."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pix = doc[page_no - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    k = 72.0 / dpi
    min_px = int(min_len_pt / k)

    def runs(mask_rows):
        out = []
        for idx, row in enumerate(mask_rows):
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
            for s, e in zip(starts, ends):
                if e - s >= min_px:
                    out.append((idx, s, e))
        return out

    mask = img < dark
    h = runs(mask)            # rows -> horizontal lines
    v = runs(mask.T)          # columns -> vertical lines

    def cluster(rs, axis):
        rs.sort()
        groups, open_groups = [], []
        for pos, s, e in rs:  # merge adjacent pixel rows/cols of the same thick line (any open group may continue)
            open_groups = [g for g in open_groups if pos - g["last"] <= 1]
            g = next((g for g in open_groups if g["last"] < pos and s < g["e"] and e > g["s"]), None)
            if g:
                g["last"], g["s"], g["e"], g["rows"] = pos, min(g["s"], s), max(g["e"], e), g["rows"] + [pos]
            else:
                g = {"last": pos, "s": s, "e": e, "rows": [pos]}
                groups.append(g)
                open_groups.append(g)
        return [{"axis": axis, "pos": round((sum(g["rows"]) / len(g["rows"]) + 0.5) * k, 2),
                 "start": round(float(g["s"]) * k, 2), "end": round(float(g["e"]) * k, 2), "thickness_px": len(g["rows"])} for g in groups]

    def bridge(lines, gap_pt=1.5, pos_tol=0.5):
        """Same rule as the vector side (axis_runs): collinear pieces separated by <= 1.5 pt are one line."""
        out: list[dict] = []
        for ln in sorted(lines, key=lambda x: x["start"]):
            host = next((o for o in out if abs(o["pos"] - ln["pos"]) <= pos_tol
                         and ln["start"] - o["end"] <= gap_pt and o["start"] - ln["end"] <= gap_pt), None)
            if host is None:
                out.append(dict(ln))
                continue
            if ln["end"] - ln["start"] > host["end"] - host["start"]:
                host["pos"] = ln["pos"]  # position of the longer piece
            host["start"], host["end"] = min(host["start"], ln["start"]), max(host["end"], ln["end"])
        return sorted(out, key=lambda x: (x["pos"], x["start"]))

    return {"page_no": page_no, "dpi": dpi, "horizontal": bridge(cluster(h, "h")), "vertical": bridge(cluster(v, "v"))}


def match_axis_lines(vector: list[dict], raster: list[dict], tol_pos: float = 1.0, tol_end: float = 2.0) -> dict:
    """vector/raster: [{"axis","pos","start","end"}]. Greedy one-to-one matching by position and extent."""
    used, matched, unmatched_v = set(), [], []
    for vl in vector:
        best = None
        for j, rl in enumerate(raster):
            if j in used or rl["axis"] != vl["axis"]:
                continue
            if abs(rl["pos"] - vl["pos"]) <= tol_pos and abs(rl["start"] - vl["start"]) <= tol_end and abs(rl["end"] - vl["end"]) <= tol_end:
                best = j
                break
        if best is None:
            unmatched_v.append(vl)
        else:
            used.add(best)
            matched.append((vl, raster[best]))
    return {"matched": len(matched), "vector_only": unmatched_v, "raster_only": [r for j, r in enumerate(raster) if j not in used]}
