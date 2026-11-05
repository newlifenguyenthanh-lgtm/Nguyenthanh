# PAACC Construction AI

(Folder name `paacc-accounting-ai/` kept from the first iteration; accounting is now Module 08.)
Construction-company platform for Vietnamese businesses: drawings, takeoff, estimation, contracts, payments,
inventory, site management, accounting – with a 3D virtual office as the navigation and monitoring layer.

| Layer | Stack | Status |
|---|---|---|
| Backend | Python FastAPI + SQLAlchemy + Alembic | auth/RBAC, audit, projects, partners, contracts, documents, virtual office, AI tasks, PDF/OCR drawing analysis, draft BOQ, review/approval, Excel export |
| Frontend | React + TypeScript + React Router | Vietnamese UI: 3D virtual office, 2D dashboard, projects, documents, drawings inspector, BOQ review, contracts (read-only), audit log |
| 3D | three.js + React Three Fiber + drei | lazy-loaded isometric office, real backend status (see `docs/VIRTUAL_OFFICE.md`) |
| Database | PostgreSQL (SQLite for dev/tests) | migrations `0001`–`0006`; PostgreSQL integration tests |
| AI | Provider-agnostic agents (Claude / OpenAI / local) | 18-agent registry, offline `echo` provider; real adapters not yet |

**Policy:** no tax rule (rates, thresholds, deadlines, circular references) is implemented until it is
verified against an official source and recorded in `tax_rule_sources`. Agents for tax domains are registered
but return `not_implemented`. No real company data or secrets belong in this repo.

Docs: `docs/PHASE1_DESIGN.md` (architecture & roadmap status), `docs/PHASE4_DRAWINGS_TAKEOFF.md`, `docs/REAL_DRAWING_VALIDATION_REPORT.md`, `docs/BOQ_TEMPLATE_MAPPING.md`, `test-data/golden-dataset/README.md`, `docs/VIRTUAL_OFFICE.md`, `docs/DATABASE.md`.

## Run
```bash
cd backend
pip install -e ".[dev]"
pytest
export PAACC_JWT_SECRET=<long-random>  PAACC_ADMIN_PW=<password>
alembic upgrade head
python -m app.cli create-admin --company "Tên công ty" --email you@example.com --password-env PAACC_ADMIN_PW
python -m app.cli create-user --company-of you@example.com --email qs@example.com --role qs_engineer --password-env PAACC_USER_PW
uvicorn app.main:app --reload
# frontend (separate terminal)
cd ../frontend && npm install && npm run dev
```

System packages: `tesseract-ocr` + `tesseract-ocr-vie` (OCR for scanned drawings; without it scanned pages are
flagged `ocr_unavailable`), LibreOffice (only for the Excel formula-integrity test).

## Checks
```bash
scripts/check.sh   # backend tests, migration drift, frontend types/tests/build; stops on first failure
```
```bash
PAACC_TEST_PG_URL=postgresql+psycopg://user:pass@localhost:5432/paacc_test scripts/check.sh   # + PostgreSQL integration tests
```
