-- PAACC draft schema (PostgreSQL 14+). Structural only; contains no tax rules.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE companies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL, tax_code text UNIQUE,
  base_currency char(3) NOT NULL DEFAULT 'VND',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  email text NOT NULL UNIQUE, password_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin','accountant','auditor','viewer')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  code text NOT NULL, name text NOT NULL,
  parent_id uuid REFERENCES accounts(id),
  type text NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense','other')),
  UNIQUE (company_id, code)
);
CREATE TABLE partners (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  name text NOT NULL, tax_code text, kind text NOT NULL CHECK (kind IN ('customer','supplier','employee','other'))
);
CREATE TABLE construction_projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  code text NOT NULL, name text NOT NULL, status text NOT NULL DEFAULT 'active',
  UNIQUE (company_id, code)
);
CREATE TABLE contracts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  partner_id uuid REFERENCES partners(id),
  project_id uuid REFERENCES construction_projects(id),
  number text NOT NULL, title text, value numeric(20,2), currency char(3) DEFAULT 'VND',
  signed_on date, status text NOT NULL DEFAULT 'draft',
  UNIQUE (company_id, number)
);
CREATE TABLE journal_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  entry_date date NOT NULL, description text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
  source text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','ai_proposed','import')),
  created_by uuid REFERENCES users(id), approved_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE journal_lines (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id uuid NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  account_id uuid NOT NULL REFERENCES accounts(id),
  partner_id uuid REFERENCES partners(id),
  project_id uuid REFERENCES construction_projects(id),
  debit  numeric(20,2) NOT NULL DEFAULT 0 CHECK (debit  >= 0),
  credit numeric(20,2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
  CHECK ((debit = 0) <> (credit = 0))
);
-- Balance (sum debit = sum credit) is enforced on posting in the service layer
-- (app/domain/journal.py) and should be backed by a deferred constraint trigger.
CREATE TABLE payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  contract_id uuid REFERENCES contracts(id), partner_id uuid REFERENCES partners(id),
  direction text NOT NULL CHECK (direction IN ('in','out')),
  amount numeric(20,2) NOT NULL CHECK (amount > 0), currency char(3) NOT NULL DEFAULT 'VND',
  paid_on date, journal_entry_id uuid REFERENCES journal_entries(id)
);
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  kind text NOT NULL, storage_uri text NOT NULL, sha256 char(64) NOT NULL,
  uploaded_at timestamptz NOT NULL DEFAULT now()
);
-- Tax rules must cite an official source and a human verifier before use.
CREATE TABLE tax_rule_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  domain text NOT NULL CHECK (domain IN ('vat','cit','pit','accounting','other')),
  rule_key text NOT NULL, rule_value jsonb NOT NULL,
  legal_reference text NOT NULL, source_url text NOT NULL,
  effective_from date NOT NULL, effective_to date,
  verified_by uuid NOT NULL REFERENCES users(id), verified_at timestamptz NOT NULL,
  UNIQUE (domain, rule_key, effective_from)
);
CREATE TABLE ai_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  agent text NOT NULL, provider text NOT NULL, model text,
  prompt_sha256 char(64) NOT NULL, output jsonb, status text NOT NULL,
  created_by uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_logs (
  id bigserial PRIMARY KEY,
  company_id uuid REFERENCES companies(id), user_id uuid REFERENCES users(id),
  action text NOT NULL, entity text, entity_id uuid, detail jsonb,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON journal_lines (entry_id);
CREATE INDEX ON journal_entries (company_id, entry_date);
