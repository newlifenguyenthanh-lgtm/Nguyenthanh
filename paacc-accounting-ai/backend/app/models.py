"""Shared relational model. Every business row carries company_id (multi-tenant)."""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(20, 2)


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def fk(table: str):
    return mapped_column(Uuid, ForeignKey(f"{table}.id"), index=True)


class Company(Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(255))
    tax_code: Mapped[str | None] = mapped_column(String(32), unique=True)


class User(Base):
    __tablename__ = "users"
    company_id: Mapped[uuid.UUID] = fk("companies")
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(default=True)


class Project(Base):
    __tablename__ = "projects"
    company_id: Mapped[uuid.UUID] = fk("companies")
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="planning")
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)


class Partner(Base):
    """Customer (chủ đầu tư/tổng thầu), supplier, or subcontractor - one table, no duplication."""
    __tablename__ = "partners"
    company_id: Mapped[uuid.UUID] = fk("companies")
    name: Mapped[str] = mapped_column(String(255))
    tax_code: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))  # customer | supplier | subcontractor


class Contract(Base):
    __tablename__ = "contracts"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID] = fk("projects")
    partner_id: Mapped[uuid.UUID] = fk("partners")
    number: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), default="")
    direction: Mapped[str] = mapped_column(String(16))  # outbound (đầu ra) | inbound (đầu vào)
    original_value: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(16), default="draft")


class ContractAppendix(Base):
    __tablename__ = "contract_appendices"
    company_id: Mapped[uuid.UUID] = fk("companies")
    contract_id: Mapped[uuid.UUID] = fk("contracts")
    number: Mapped[str] = mapped_column(String(64))
    delta_value: Mapped[Decimal] = mapped_column(Money)  # may be negative (giảm)
    reason: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | approved | rejected
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    company_id: Mapped[uuid.UUID] = fk("companies")
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict | None] = mapped_column(JSON)


class Document(Base):
    """Logical document; content lives in immutable DocumentVersion rows."""
    __tablename__ = "documents"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="other")  # drawing | boq | quote | contract | email | other
    current_version: Mapped[int] = mapped_column(default=1)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    company_id: Mapped[uuid.UUID] = fk("companies")
    document_id: Mapped[uuid.UUID] = fk("documents")
    version_no: Mapped[int]
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
