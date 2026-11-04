# Architecture

## Principles
1. Modular monolith first: one FastAPI service, strict internal module boundaries, split later if needed.
2. Deterministic accounting core (ledger, validation) is separate from AI. AI proposes; the ledger validates; humans approve.
3. No unverified tax rules. Rules live as versioned data with a mandatory official source and verifier; code never hardcodes rates.
4. Multi-tenant by `company_id` on every business table. No real data in the repo.
5. Every AI call and every posting is audit-logged.

## Modules (backend/app)
- `domain/` pure accounting logic (journal balance validation). No I/O.
- `ai/` provider abstraction: `LLMProvider` protocol; `EchoProvider` (offline/tests), stubs for Anthropic, OpenAI, local OpenAI-compatible endpoint.
- `agents/` agent base class + registry. One agent per domain: general_accounting, vat, cit, pit, construction, contracts, payments, finance, audit. Tax agents return `not_implemented` until rules are verified.
- `api/` HTTP routers (health, agents, journal validation).
- Planned: `repositories/` (SQLAlchemy + Alembic), `auth/` (JWT, RBAC), `documents/` (invoice/contract ingestion), `rules/` (versioned verified rule store).

## Agent flow
request -> router picks agent -> agent gathers context (ledger, rules with sources) -> provider.complete() -> structured proposal -> deterministic validation -> human approval -> posting + audit log.

## Provider compatibility
`LLMProvider.complete(messages, **opts) -> LLMResponse`. Claude and OpenAI via official SDKs; local models via any OpenAI-compatible server. Selected per request or by `PAACC_DEFAULT_AI_PROVIDER`.

## Frontend
React + TS, talks to REST API; pages: ledger, documents, agents chat, tax-rule registry, audit trail.

## Roadmap
1. (this) skeleton + journal validation + agent registry
2. SQLAlchemy models/Alembic from `db/schema.sql`, auth/RBAC
3. Chart of accounts import (verify against the applicable official regime first)
4. Real provider adapters, document ingestion
5. Verified tax rule modules, one domain at a time
