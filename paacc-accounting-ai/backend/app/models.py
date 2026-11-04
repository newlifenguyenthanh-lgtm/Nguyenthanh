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


class Department(Base):
    __tablename__ = "departments"
    company_id: Mapped[uuid.UUID] = fk("companies")
    code: Mapped[str] = mapped_column(String(64))
    name_vi: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(default=0)
    color: Mapped[str] = mapped_column(String(16), default="#4f7cac")
    layout: Mapped[dict] = mapped_column(JSON)  # {"x","z","w","d"} in scene units


class DepartmentMember(Base):
    __tablename__ = "department_members"
    company_id: Mapped[uuid.UUID] = fk("companies")
    department_id: Mapped[uuid.UUID] = fk("departments")
    user_id: Mapped[uuid.UUID] = fk("users")
    job_title: Mapped[str] = mapped_column(String(255), default="")


class AITask(Base):
    __tablename__ = "ai_tasks"
    company_id: Mapped[uuid.UUID] = fk("companies")
    agent_key: Mapped[str] = mapped_column(String(64), index=True)
    department_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    requires_approval: Mapped[bool] = mapped_column(default=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"))
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    output_summary: Mapped[str] = mapped_column(String(2000), default="")
    error_message: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Drawing(Base):
    """One processing run of one immutable document version (explicit document/version link)."""
    __tablename__ = "drawings"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    document_id: Mapped[uuid.UUID] = fk("documents")
    document_version_id: Mapped[uuid.UUID] = fk("document_versions")
    version_no: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|processing|processed|failed
    page_count: Mapped[int] = mapped_column(default=0)
    pdf_metadata: Mapped[dict | None] = mapped_column(JSON)
    findings: Mapped[list | None] = mapped_column(JSON)
    duplicate_of_drawing_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("drawings.id"))
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(String(2000), default="")
    ai_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ai_tasks.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class DrawingPage(Base):
    __tablename__ = "drawing_pages"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int]
    width_pt: Mapped[float]
    height_pt: Mapped[float]
    rotation: Mapped[int] = mapped_column(default=0)
    kind: Mapped[str] = mapped_column(String(16))  # vector|scanned|mixed|vector_no_text|empty
    text_chars: Mapped[int] = mapped_column(default=0)
    image_coverage: Mapped[float] = mapped_column(default=0)
    vector_paths: Mapped[int] = mapped_column(default=0)
    ocr_used: Mapped[bool] = mapped_column(default=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(128))
    ocr_mean_confidence: Mapped[float | None]
    warnings: Mapped[list | None] = mapped_column(JSON)


class ExtractedItem(Base):
    """A value read from the drawing. bbox in PDF points, displayed page space, origin top-left."""
    __tablename__ = "extracted_items"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # text|table|... (analysis adds more)
    text: Mapped[str] = mapped_column(String(4000))
    x0: Mapped[float]
    y0: Mapped[float]
    x1: Mapped[float]
    y1: Mapped[float]
    source: Mapped[str] = mapped_column(String(16))  # text | ocr | analysis
    confidence: Mapped[float | None]  # 0-1, None = exact embedded text
    data: Mapped[dict | None] = mapped_column(JSON)
