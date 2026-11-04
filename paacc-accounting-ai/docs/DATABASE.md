# Database (PostgreSQL)
`db/schema.sql` is the early draft. The source of truth is now `backend/app/models.py` (SQLAlchemy); schema SQL will be generated via Alembic. See `docs/PHASE1_DESIGN.md`.
partners, contracts, payments, construction_projects, documents, tax_rule_sources (official source + verified_by + effective dates; required before any rule is used),
ai_runs (provider, model, prompt hash, output, status), audit_logs.
