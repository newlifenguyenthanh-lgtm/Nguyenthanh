# PAACC Construction AI

(Folder name `paacc-accounting-ai/` kept from the first iteration; accounting is now Module 08.)
Construction-company platform for Vietnamese businesses: drawings, takeoff, estimation, contracts, payments,
inventory, site management, accounting – with a 3D virtual office as the navigation and monitoring layer.

| Layer | Stack | Status |
|---|---|---|
| Backend | Python FastAPI + SQLAlchemy + Alembic | auth/RBAC, audit, projects, partners, contracts, documents, virtual office, AI tasks, takeoff engine |
| Frontend | React + TypeScript + React Router | Vietnamese UI: 3D virtual office, 2D dashboard, projects, documents, contracts (read-only), audit log |
| 3D | three.js + React Three Fiber + drei | lazy-loaded isometric office, real backend status (see `docs/VIRTUAL_OFFICE.md`) |
| Database | PostgreSQL (SQLite for tests/dev) | migrations `0001`, `0002` |
| AI | Provider-agnostic agents (Claude / OpenAI / local) | 18-agent registry, offline `echo` provider; real adapters not yet |

**Policy:** no tax rule (rates, thresholds, deadlines, circular references) is implemented until it is
verified against an official source and recorded in `tax_rule_sources`. Agents for tax domains are registered
but return `not_implemented`. No real company data or secrets belong in this repo.

Docs: `docs/PHASE1_DESIGN.md` (architecture & roadmap status), `docs/VIRTUAL_OFFICE.md`, `docs/DATABASE.md`.

## Run
```bash
cd backend
pip install -e ".[dev]"
pytest
export PAACC_JWT_SECRET=<long-random>  PAACC_ADMIN_PW=<password>
alembic upgrade head
python -m app.cli create-admin --company "Tên công ty" --email you@example.com --password-env PAACC_ADMIN_PW
uvicorn app.main:app --reload
# frontend (separate terminal)
cd ../frontend && npm install && npm run dev
```
