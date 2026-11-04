# Database (PostgreSQL)
See `db/schema.sql`. Key tables: companies, users, accounts, journal_entries/lines (double-entry, amounts in NUMERIC(20,2), currency VND default),
partners, contracts, payments, construction_projects, documents, tax_rule_sources (official source + verified_by + effective dates; required before any rule is used),
ai_runs (provider, model, prompt hash, output, status), audit_logs.
