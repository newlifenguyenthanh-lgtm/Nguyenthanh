"""Runs the full Phase 4 pipeline on real PDFs through the real API and records every intermediate result.

    python -m tools.golden_run --input <dir with PDFs> --out <results dir> [--label baseline]

Uses an isolated temporary SQLite database and storage directory; nothing is written to the
configured database. Input files are read, never modified. Results contain confidential data
derived from the documents - keep the output directory OUT of the repository.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(input_dir: Path, out_dir: Path, label: str) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="paacc-golden-"))
    os.environ.update(PAACC_DATABASE_URL=f"sqlite:///{tmp}/golden.db", PAACC_STORAGE_DIR=str(tmp / "store"),
                      PAACC_JWT_SECRET="golden-run-local-secret-0123456789")
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
        create_admin(s, "Golden run", "admin@golden.local", "golden-admin-pw")
        create_user(s, "admin@golden.local", "qs@golden.local", "qs_engineer", "golden-qs-pw1")
        create_user(s, "admin@golden.local", "dir@golden.local", "director", "golden-dir-pw1")
    c = TestClient(app)
    B = "/api/v1"

    def login(email, pw):
        return {"Authorization": "Bearer " + c.post(f"{B}/auth/login", json={"email": email, "password": pw}).json()["access_token"]}

    qs, director = login("qs@golden.local", "golden-qs-pw1"), login("dir@golden.local", "golden-dir-pw1")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    summary = {"label": label, "code_commit": commit, "documents": []}
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(input_dir.glob("*.pdf")):
        data = pdf.read_bytes()
        rec: dict = {"file": pdf.name, "sha256": hashlib.sha256(data).hexdigest(), "steps": {}}
        doc = c.post(f"{B}/documents", data={"title": pdf.stem, "kind": "drawing"},
                     files={"file": (pdf.name, data, "application/pdf")}, headers=qs).json()
        d = c.post(f"{B}/drawings", json={"document_id": doc["id"]}, headers=qs).json()
        rec["steps"]["process"] = {"status": d["status"], "error": d.get("error_message")}
        if d["status"] == "processed":
            full = c.get(f"{B}/drawings/{d['id']}", headers=qs).json()
            rec["drawing"] = full
            rec["items"] = c.get(f"{B}/drawings/{d['id']}/items?limit=5000", headers=qs).json()
            rec["geometry_summary"] = c.get(f"{B}/drawings/{d['id']}/geometry/summary", headers=qs).json()
            rec["geometry_axis_runs"] = {p["page_no"]: c.get(f"{B}/drawings/{d['id']}/geometry/axis-runs?page={p['page_no']}", headers=qs).json()
                                         for p in rec["geometry_summary"]["pages"]}
            boq_r = c.post(f"{B}/boqs", json={"title": pdf.stem, "drawing_ids": [d["id"]]}, headers=qs)
            rec["steps"]["boq_generate"] = boq_r.status_code
            if boq_r.status_code == 201:
                boq = boq_r.json()
                rec["boq_generated"] = boq
                # approval simulation: accept every computable item WITH a note (needed for duplicates), reject the rest
                for it in boq["items"]:
                    ok = it["quantity"] is not None and not it["has_blocking"]
                    c.post(f"{B}/boqs/{boq['id']}/items/{it['id']}/review",
                           json={"decision": "accept" if ok else "reject",
                                 "note": "golden-run: accepted for pipeline simulation only" if ok else "golden-run: blocked"}, headers=qs)
                sub = c.post(f"{B}/boqs/{boq['id']}/submit", json={"note": "golden-run"}, headers=qs)
                rec["steps"]["submit"] = {"status": sub.status_code, "detail": sub.json().get("detail") if sub.status_code != 200 else None}
                if sub.status_code == 200:
                    dec = c.post(f"{B}/boqs/{boq['id']}/decision", json={"decision": "approve", "note": "golden-run"}, headers=director)
                    rec["steps"]["approve"] = dec.status_code
                for layout in ("paacc", "company_kl"):
                    exp = c.post(f"{B}/boqs/{boq['id']}/exports?layout={layout}", headers=qs)
                    rec["steps"][f"export_{layout}"] = exp.status_code
                    if exp.status_code == 201:
                        x = c.get(f"{B}/boq-exports/{exp.json()['id']}/download", headers=qs)
                        (out_dir / f"{pdf.stem}.{label}.{layout}.xlsx").write_bytes(x.content)
                        rec[f"export_{layout}"] = exp.json()
                rec["boq_final"] = c.get(f"{B}/boqs/{boq['id']}", headers=qs).json()
        (out_dir / f"{pdf.stem}.{label}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str))
        summary["documents"].append({"file": pdf.name, "steps": rec["steps"]})
    (out_dir / f"summary.{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="run")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.input, a.out, a.label), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
