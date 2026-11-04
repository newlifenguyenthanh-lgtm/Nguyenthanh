# PAACC Construction AI – Phase 1 Design

Product: PAACC Construction AI (Công ty Phương Anh). This repo folder started as "PAACC Accounting AI";
accounting/tax is now Module 08 of the larger product. Folder name kept to avoid churn; rename is a later decision.

## Core principles
- Deterministic code computes all quantities and money (Decimal, never float, never LLM). LLMs only extract, classify, draft and explain.
- Every number carries provenance (source document, page, position, who/what produced it, version).
- Important actions (send quotation, post ledger, pay, change contract) require explicit human approval. Implemented first for contract appendices.
- Source files are immutable; edits create new versions. All changes are audit-logged. Multi-tenant via `company_id`.
- Tax rules: data with legal reference + effective date + human verifier. Nothing is hardcoded or guessed. (Tax tables not implemented.)

## Pipeline and shared keys
Drawing -> Takeoff (BOQ items) -> Estimation -> Quotation -> Contract -> Purchase order -> Goods receipt -> Issue -> Site work -> Acceptance -> Payment -> Profit report.
Linking keys: `project_id`, `contract_id`, `material_id`, `partner_id`, `document_id`, `boq_item_id`. One `partners` table (customer/supplier/subcontractor); one `materials` catalogue; no per-module copies.

## Modules -> main entities (planned tables)
| # | Module | Entities |
|---|---|---|
| 01 | PDF Drawing AI | documents, drawings, drawing_pages, takeoff_items (page, bbox, method, status draft/confirmed, version) |
| 02 | Quotation Intake | rfqs, supplier_quotes, quote_lines, price_history (source, received_date) |
| 03 | Estimation | estimates, estimate_lines, norms, waste_factors, price_scenarios |
| 04 | AutoCAD/MCP | cad_files, cad_layers, cad_entities, cad_takeoffs (units, scale, dedupe checks) |
| 05 | Contract & Payment | contracts*, appendices*, advances, acceptances, payment_requests, payments, deductions, retentions |
| 06 | Inventory | materials, warehouses, purchase_orders, goods_receipts, goods_issues, transfers, stock_movements |
| 07 | Site | wbs_items, schedules, daily_logs, labor, equipment, quality/safety records, variations |
| 08 | Accounting | accounts, journal_entries/lines, invoices, cashflow, tax_rule_sources (verified) |
| – | Platform | companies*, users*, roles, ai_tasks, approvals, audit_logs* |
(* implemented in Phase 2 foundation)

## Agents (14)
Supervisor routes and enforces approval gates; Document, PDF Drawing, CAD, Quantity Surveyor, Quotation, Estimation, Contract,
Payment, Inventory, Construction, Accounting, Audit (cross-checks other agents' outputs against deterministic recomputation), Reporting.
Contract: each agent reads/writes only its own module's tables via service functions; hand-off is through typed records
(e.g. confirmed takeoff_items -> Estimation), never free text. Each run writes an `ai_tasks` row (agent, model, inputs hash, output, status, approver).
Model routing: Haiku (simple), Sonnet (default), Opus (hard); Ollama for local/private. Behind the `LLMProvider` interface.

## Tech decisions
FastAPI + SQLAlchemy 2 (PostgreSQL in prod; SQLite only for tests/dev), JWT auth, scrypt password hashing, role->permission map.
Heavy jobs (PDF/OCR/CAD) via Celery+Redis later. CAD: DXF via `ezdxf` first (cross-platform, testable); DWG/AutoCAD live control via a Windows .NET plugin + MCP server later.
Frontend: React + TS (Vite), Vietnamese UI, next increment.

## Status vs roadmap
- Phase 1: this document. Phase 2: backend foundation done (auth, RBAC, audit, projects, partners, contracts+appendices with approval); Alembic migration `0001` added.
- Phase 3 (in progress): versioned, SHA-256 content-addressed document store with duplicate detection (done); React/TS Vietnamese shell with login, projects, documents (done, minimal). Not yet: project dashboard, document preview, contracts UI, S3 storage, virus scanning.
- Phases 3-12: not started.

## Known limitations / open questions
- Tests run on SQLite, which stores Decimal as float; money columns must be verified on PostgreSQL before production.
- Need from the company: sample drawings, BOQ/quote templates, chart of accounts in use, existing norms (định mức), role list.
