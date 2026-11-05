"""Shared relational model. Every business row carries company_id (multi-tenant)."""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(20, 2)


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Python-side default gives microsecond precision (stable ordering on SQLite); server default kept for raw SQL.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    default=lambda: dt.datetime.now(dt.timezone.utc))


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
    # --- analysis (4B): detected values are candidates; *_status says whether a human confirmed them
    drawing_number: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[str | None] = mapped_column(String(16))
    title_fields: Mapped[dict | None] = mapped_column(JSON)
    disciplines: Mapped[list | None] = mapped_column(JSON)
    view_types: Mapped[list | None] = mapped_column(JSON)
    scale_candidates: Mapped[list | None] = mapped_column(JSON)
    scale_status: Mapped[str] = mapped_column(String(24), default="not_analyzed")
    scale_ratio: Mapped[int | None]  # set ONLY by human confirmation
    units_candidates: Mapped[list | None] = mapped_column(JSON)
    units_status: Mapped[str] = mapped_column(String(24), default="not_analyzed")
    units: Mapped[str | None] = mapped_column(String(8))  # set ONLY by human confirmation
    calibrated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    calibrated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # --- vector geometry (Phase 5A)
    geometry_status: Mapped[str] = mapped_column(String(24), default="not_extracted", server_default="not_extracted")
    geometry_stats: Mapped[dict | None] = mapped_column(JSON)
    page_frame: Mapped[dict | None] = mapped_column(JSON)  # rotation, boxes, PAGE->DISPLAY matrix


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


QtyNum = Numeric(20, 4)


class Boq(Base):
    """A versioned bill of quantities. Approved versions are immutable; changes need a new version."""
    __tablename__ = "boqs"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    version_no: Mapped[int] = mapped_column(default=1)
    previous_boq_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("boqs.id"))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|submitted|approved|returned
    rules: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    generation_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ai_tasks.id"))
    approval_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ai_tasks.id"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(String(2000), default="")


class BoqSource(Base):
    """Explicit BOQ <-> drawing <-> document version relationship."""
    __tablename__ = "boq_sources"
    company_id: Mapped[uuid.UUID] = fk("companies")
    boq_id: Mapped[uuid.UUID] = fk("boqs")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    document_version_id: Mapped[uuid.UUID] = fk("document_versions")


class BoqItem(Base):
    __tablename__ = "boq_items"
    company_id: Mapped[uuid.UUID] = fk("companies")
    boq_id: Mapped[uuid.UUID] = fk("boqs")
    item_no: Mapped[int]
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(1000))
    spec: Mapped[str] = mapped_column(String(500), default="")
    module: Mapped[str | None] = mapped_column(String(64))  # None = stated quantity (schedule table / engineer)
    inputs: Mapped[dict] = mapped_column(JSON)  # name -> {value, origin, source_item_id, ...}
    unit_system: Mapped[str | None] = mapped_column(String(8))
    stated_unit: Mapped[str | None] = mapped_column(String(16))
    waste_override: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    waste_factor: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    quantity: Mapped[Decimal | None] = mapped_column(QtyNum)
    unit: Mapped[str | None] = mapped_column(String(16))
    formula_text: Mapped[str] = mapped_column(String(2000), default="")
    excel_expr: Mapped[str | None] = mapped_column(String(1000))
    calc_inputs: Mapped[dict | None] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String(16))  # extracted | ai_inferred | engineer | mixed
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|accepted|rejected
    source_flags: Mapped[list | None] = mapped_column(JSON)
    flags: Mapped[list | None] = mapped_column(JSON)
    duplicates: Mapped[list | None] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(String(4000), default="")
    drawing_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("drawings.id"))
    page_no: Mapped[int | None]
    bbox: Mapped[list | None] = mapped_column(JSON)
    source_item_ids: Mapped[list | None] = mapped_column(JSON)
    mark: Mapped[str | None] = mapped_column(String(32))
    section_key: Mapped[str | None] = mapped_column(String(64))
    group_path: Mapped[list | None] = mapped_column(JSON)  # source hierarchy, e.g. [{"code": "4", "title": "..."}, {"code": "4.1", ...}]
    version: Mapped[int] = mapped_column(default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class BoqItemRevision(Base):
    """Append-only history of every change to a BOQ item."""
    __tablename__ = "boq_item_revisions"
    company_id: Mapped[uuid.UUID] = fk("companies")
    boq_id: Mapped[uuid.UUID] = fk("boqs")
    item_id: Mapped[uuid.UUID] = fk("boq_items")
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(32))
    snapshot: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(2000), default="")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class BoqExport(Base):
    """Every generated Excel file: linked to project, BOQ and the exact BOQ version/status exported."""
    __tablename__ = "boq_exports"
    company_id: Mapped[uuid.UUID] = fk("companies")
    boq_id: Mapped[uuid.UUID] = fk("boqs")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    boq_version_no: Mapped[int]
    boq_status: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(255))
    item_count: Mapped[int]
    layout: Mapped[str] = mapped_column(String(32), default="paacc", server_default="paacc")  # paacc | company_kl
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))


class GeometryPrimitive(Base):
    """One vector primitive of a drawing page (Phase 5A). Coordinates: DISPLAY space, PDF points, top-left origin,
    stored as exact decimal strings; bbox floats only for spatial filtering. Never deleted when duplicated."""
    __tablename__ = "geometry_primitives"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # line|polyline|polygon|rect|fill_region|curve|circle
    points: Mapped[list] = mapped_column(JSON)  # [["x","y"], ...]
    closed: Mapped[bool] = mapped_column(default=False)
    x0: Mapped[float]
    y0: Mapped[float]
    x1: Mapped[float]
    y1: Mapped[float]
    length_pt: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    area_pt2: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    stroke_width: Mapped[float | None]
    stroke_color: Mapped[str | None] = mapped_column(String(9))
    fill_color: Mapped[str | None] = mapped_column(String(9))
    layer: Mapped[str | None] = mapped_column(String(255))
    path_index: Mapped[int] = mapped_column(default=0)
    item_index: Mapped[int] = mapped_column(default=0)
    derived_from: Mapped[str | None] = mapped_column(String(32))
    approximate: Mapped[bool] = mapped_column(default=False)
    flags: Mapped[list | None] = mapped_column(JSON)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("geometry_primitives.id"))
    overlaps: Mapped[list | None] = mapped_column(JSON)  # ids of collinear overlapping primitives
    extra: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="extracted")  # extracted|confirmed|rejected|ambiguous
    review_note: Mapped[str] = mapped_column(String(2000), default="")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ScaleRegion(Base):
    """Phase 5B: a page area with its own scale (e.g. a 1:20 detail on a 1:100 plan). Only 'confirmed' is used."""
    __tablename__ = "scale_regions"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int]
    x0: Mapped[float]
    y0: Mapped[float]
    x1: Mapped[float]
    y1: Mapped[float]
    scale_ratio: Mapped[int]
    label: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # candidate | confirmed | rejected
    note: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Measurement(Base):
    """Phase 5B: one deterministic measurement over geometry primitives (Decimal; real value only on confirmed scale)."""
    __tablename__ = "measurements"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int]
    kind: Mapped[str] = mapped_column(String(24))  # length|perimeter|area|count|distance|spacing|chainage_interval
    geometry_ids: Mapped[list] = mapped_column(JSON)
    value_paper: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    paper_unit: Mapped[str] = mapped_column(String(8))
    value_real: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    real_unit: Mapped[str | None] = mapped_column(String(8))
    scale_ratio: Mapped[int | None]
    scale_source: Mapped[str | None] = mapped_column(String(64))
    formula: Mapped[str] = mapped_column(String(2000), default="")
    details: Mapped[dict | None] = mapped_column(JSON)
    method: Mapped[str] = mapped_column(String(32), default="geometry-5B.1")
    status: Mapped[str] = mapped_column(String(16), default="computed")  # computed | confirmed | rejected
    note: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class DrawingTextBlock(Base):
    """Phase 5C: one text line of a page as an association subject. original_text is never modified."""
    __tablename__ = "drawing_text_blocks"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int] = mapped_column(index=True)
    extracted_item_id: Mapped[uuid.UUID] = fk("extracted_items")
    original_text: Mapped[str] = mapped_column(String(4000))
    normalized_text: Mapped[str] = mapped_column(String(4000))
    x0: Mapped[float]
    y0: Mapped[float]
    x1: Mapped[float]
    y1: Mapped[float]
    center_x: Mapped[float]
    center_y: Mapped[float]
    rotation: Mapped[float] = mapped_column(default=0.0)  # degrees in DISPLAY space, 0 = left-to-right
    font_size: Mapped[float | None]
    font_name: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16))  # text | ocr
    confidence: Mapped[float | None]
    text_type: Mapped[str] = mapped_column(String(24), index=True)
    values: Mapped[dict | None] = mapped_column(JSON)
    flags: Mapped[list | None] = mapped_column(JSON)
    encoding: Mapped[dict | None] = mapped_column(JSON)
    repeat_count: Mapped[int] = mapped_column(default=1)  # same normalised text on the page
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class TextGeometryAssociation(Base):
    """Phase 5C: a candidate/decided link text block -> geometry primitive. Only CONFIRMED may flow downstream."""
    __tablename__ = "text_geometry_associations"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int] = mapped_column(index=True)
    text_block_id: Mapped[uuid.UUID] = fk("drawing_text_blocks")
    geometry_id: Mapped[uuid.UUID] = fk("geometry_primitives")
    association_type: Mapped[str] = mapped_column(String(24))
    rank: Mapped[int] = mapped_column(default=1)
    distance: Mapped[float | None]
    angle_difference: Mapped[float | None]
    overlap_ratio: Mapped[float | None]
    orientation_match: Mapped[bool] = mapped_column(default=False)
    semantic_match: Mapped[float | None]
    relation: Mapped[str | None] = mapped_column(String(16))
    components: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(20), index=True)  # CANDIDATE|REVIEW_REQUIRED|CONFIRMED|REJECTED|AMBIGUOUS|CONFLICT
    reason: Mapped[str] = mapped_column(String(2000), default="")
    origin: Mapped[str] = mapped_column(String(16), default="rule")  # rule | engineer | ai_inferred
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("text_geometry_associations.id"))
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"))
    text_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))  # metres, from the text
    measured_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))  # metres, from geometry + confirmed scale
    difference: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    history: Mapped[list | None] = mapped_column(JSON)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- Phase 5D: component recognition
class ComponentType(Base):
    """Extensible taxonomy (per company; seeded from app/components/catalog.json). rule = recognition rule DATA."""
    __tablename__ = "component_types"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_component_types_company_code"),)
    company_id: Mapped[uuid.UUID] = fk("companies")
    code: Mapped[str] = mapped_column(String(48), index=True)
    group_code: Mapped[str] = mapped_column(String(24))  # ATGT | HA_TANG | KET_CAU | THEP | GENERIC
    name_vi: Mapped[str] = mapped_column(String(255))
    parent_code: Mapped[str | None] = mapped_column(String(48))  # is-a (CORRUGATED_SHEET is a GUARDRAIL)
    family: Mapped[str] = mapped_column(String(48))
    member_type: Mapped[str | None] = mapped_column(String(48))  # FENCE -> FENCE_POST
    rule: Mapped[dict] = mapped_column(JSON)
    boq: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(16), default="catalog")  # catalog | company
    catalog_version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ComponentSymbolPattern(Base):
    __tablename__ = "component_symbol_patterns"
    company_id: Mapped[uuid.UUID] = fk("companies")
    component_type: Mapped[str | None] = mapped_column(String(48), index=True)  # None = generic (leader, arrow …)
    pattern_type: Mapped[str] = mapped_column(String(24))
    parameters: Mapped[dict] = mapped_column(JSON)
    tolerance: Mapped[dict] = mapped_column(JSON)
    confidence_weight: Mapped[float] = mapped_column(default=0.5)
    active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(16), default="catalog")


class ComponentRepeatGroup(Base):
    """A row of repeated symbols (posts …). Count/spacing are 5B measurements referenced here, never copied."""
    __tablename__ = "component_repeat_groups"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_no: Mapped[int]
    pattern_type: Mapped[str] = mapped_column(String(24))
    signature: Mapped[dict] = mapped_column(JSON)
    carrier_geometry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("geometry_primitives.id"))
    pattern_status: Mapped[str] = mapped_column(String(24))  # REGULAR | IRREGULAR_PATTERN | OCCLUDED
    count_measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"))
    spacing_measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"))
    start_x: Mapped[float]
    start_y: Mapped[float]
    end_x: Mapped[float]
    end_y: Mapped[float]
    gaps_pt: Mapped[list | None] = mapped_column(JSON)  # paper-space geometry feature, not a quantity
    occluders: Mapped[list | None] = mapped_column(JSON)


class DrawingComponent(Base):
    """Phase 5D: a recognised component CANDIDATE with evidence. Quantities live in `measurements` (referenced)."""
    __tablename__ = "drawing_components"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_id: Mapped[uuid.UUID] = fk("drawing_pages")
    page_no: Mapped[int] = mapped_column(index=True)
    component_type: Mapped[str] = mapped_column(String(48), index=True)
    component_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("component_types.id"))
    component_subtype: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(String(2000), default="")
    specification: Mapped[str] = mapped_column(String(1000), default="")
    material: Mapped[str] = mapped_column(String(255), default="")
    x0: Mapped[float]
    y0: Mapped[float]
    x1: Mapped[float]
    y1: Mapped[float]
    centroid_x: Mapped[float]
    centroid_y: Mapped[float]
    view_context: Mapped[str] = mapped_column(String(16), default="UNKNOWN")  # PLAN|ELEVATION|SECTION|DETAIL|TABLE|NOTE|UNKNOWN
    recognition_method: Mapped[str] = mapped_column(String(16), default="rule")  # rule | engineer | ai_inferred
    recognition_rule: Mapped[str] = mapped_column(String(128), default="")
    recognition_confidence: Mapped[float] = mapped_column(default=0.0)
    confidence_band: Mapped[str] = mapped_column(String(8), default="LOW")  # HIGH | MEDIUM | LOW (never = confirmed)
    text_score: Mapped[float | None]
    geometry_score: Mapped[float | None]
    measurement_score: Mapped[float | None]
    symbol_score: Mapped[float | None]
    spatial_score: Mapped[float | None]
    repetition_score: Mapped[float | None]
    semantic_score: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(20), index=True)
    ambiguity_reason: Mapped[str] = mapped_column(String(2000), default="")
    rejection_reason: Mapped[str] = mapped_column(String(2000), default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("drawing_components.id"))  # system (FENCE) of a member group
    representation_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("drawing_components.id"), index=True)
    repeat_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("component_repeat_groups.id"))
    dimensions: Mapped[dict | None] = mapped_column(JSON)  # STATED specification dims (D88.3 …), not quantities
    evidence: Mapped[dict | None] = mapped_column(JSON)  # reasons, relations, alternatives, comparisons
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ComponentSource(Base):
    """Provenance link component -> text / geometry / measurement / association (queryable, with real FKs)."""
    __tablename__ = "component_sources"
    company_id: Mapped[uuid.UUID] = fk("companies")
    component_id: Mapped[uuid.UUID] = fk("drawing_components")
    source_type: Mapped[str] = mapped_column(String(16))  # text | geometry | measurement | association
    role: Mapped[str] = mapped_column(String(32), default="")
    text_block_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("drawing_text_blocks.id"), index=True)
    geometry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("geometry_primitives.id"), index=True)
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"), index=True)
    association_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("text_geometry_associations.id"), index=True)


class ComponentRelation(Base):
    """PART_OF / REPEATED_ALONG / REPRESENTATION_OF / DETAILED_IN / REFERENCES between components."""
    __tablename__ = "component_relations"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    from_component_id: Mapped[uuid.UUID] = fk("drawing_components")
    to_component_id: Mapped[uuid.UUID] = fk("drawing_components")
    relation_type: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict | None] = mapped_column(JSON)


class ComponentBoqCandidate(Base):
    """5D -> 5E hand-over: DRAFT, NOT_APPROVED. Quantity = REFERENCE to a measurement; 5E decides."""
    __tablename__ = "component_boq_candidates"
    company_id: Mapped[uuid.UUID] = fk("companies")
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    component_id: Mapped[uuid.UUID] = fk("drawing_components")
    description_vi: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str] = mapped_column(String(16))
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"))
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT | WITHDRAWN
    approval_status: Mapped[str] = mapped_column(String(16), default="NOT_APPROVED")
    # 5E-1: a later phase may point the hand-over at a reviewed quantity result (nullable; unused until then)
    quantity_result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey(
        "quantity_results.id", name="fk_component_boq_candidates_quantity_result"))
    note: Mapped[str] = mapped_column(String(2000), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- Phase 5E-1: quantity engine foundation
class QuantityResult(Base):
    """One versioned, reproducible quantity of ONE confirmed component, derived from 5B measurement(s) by a named method.
    raw_value (unrounded) + precision + rounding_rule -> quantity_value. Superseded versions are kept."""
    __tablename__ = "quantity_results"
    company_id: Mapped[uuid.UUID] = fk("companies")
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    drawing_id: Mapped[uuid.UUID] = fk("drawings")
    page_id: Mapped[uuid.UUID] = fk("drawing_pages")
    component_id: Mapped[uuid.UUID] = fk("drawing_components")
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("measurements.id"), index=True)  # primary input
    input_measurement_ids: Mapped[list] = mapped_column(JSON)
    quantity_type: Mapped[str] = mapped_column(String(16), index=True)  # COUNT|LENGTH|AREA|VOLUME|WEIGHT|SPACING|PERIMETER
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    quantity_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(16))
    precision: Mapped[int] = mapped_column(default=3)
    rounding_rule: Mapped[str] = mapped_column(String(24), default="ROUND_HALF_UP")
    calculation_method: Mapped[str] = mapped_column(String(32))
    rule_code: Mapped[str | None] = mapped_column(String(64), index=True)  # 5E-2 rule registry entry (None = direct 5E-1 method)
    formula: Mapped[str] = mapped_column(String(500), default="")
    formula_trace: Mapped[str] = mapped_column(String(1000), default="", server_default="")  # e.g. "51 × 2.500 m = 127.500 m"
    parameters: Mapped[dict | None] = mapped_column(JSON)  # engineer-stated inputs WITH source (unit length / unit weight …)
    source_component: Mapped[dict] = mapped_column(JSON)  # snapshot at calculation time (type, status, spec)
    source_measurement: Mapped[list] = mapped_column(JSON)  # snapshot of each input measurement (kind, value, unit, status)
    status: Mapped[str] = mapped_column(String(20), index=True)  # DRAFT|CALCULATED|REQUIRES_REVIEW|CONFIRMED|REJECTED|BLOCKED
    reason: Mapped[str] = mapped_column(String(2000), default="")
    version: Mapped[int] = mapped_column(default=1)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("quantity_results.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
