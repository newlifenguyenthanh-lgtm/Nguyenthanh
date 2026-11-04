# PAACC Accounting AI

Modular accounting AI platform for Vietnamese businesses.
Scope: general accounting, VAT, CIT, PIT, construction accounting, contracts, payments, finance, audit.

| Layer | Stack | Status |
|---|---|---|
| Backend | Python FastAPI | minimal skeleton + tests |
| Frontend | React + TypeScript | placeholder only |
| Database | PostgreSQL | draft schema in `db/schema.sql` (not yet wired) |
| AI | Provider-agnostic agents (Claude / OpenAI / local) | interfaces + offline `echo` provider |

**Policy:** no tax rule (rates, thresholds, deadlines, circular references) is implemented until it is
verified against an official source and recorded in `tax_rule_sources`. Agents for tax domains are registered
but return `not_implemented`. No real company data or secrets belong in this repo.

Docs: `docs/ARCHITECTURE.md`, `docs/DATABASE.md`.

## Run
```bash
cd backend
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```
