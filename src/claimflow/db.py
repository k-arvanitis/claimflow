"""SQLite-backed job status + audit log, shared by api/main.py and streamlit_app.py.
NOT encrypted at rest — see TODO.md."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from claimflow.config import settings


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)  # queued|processing|completed|failed
    result_json: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )
    policy_evidence_entries: Mapped[list["PolicyEvidence"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )


class AuditLogEntry(Base):
    """package_id is intentionally NOT a ForeignKey: audit history must survive
    package deletion, so it's a plain indexed string reference, not a cascade target."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor: Mapped[str] = mapped_column(String)  # e.g. "api", "reviewer"
    action: Mapped[str] = mapped_column(String)  # e.g. "upload", "extract", "validate", "review_edit"
    detail_json: Mapped[str | None] = mapped_column(Text, default=None)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("package_id", "path", name="uq_document_package_path"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    has_text_layer: Mapped[bool] = mapped_column(Boolean)
    scan_quality: Mapped[float | None] = mapped_column(Float, default=None)
    classification_reason: Mapped[str | None] = mapped_column(Text, default=None)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="documents")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    schema_name: Mapped[str] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String)  # pass|review|error
    overall_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    document: Mapped["Document"] = relationship(back_populates="extraction_runs")
    extracted_fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )
    validation_failures: Mapped[list["ValidationFailure"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String)
    parent_field: Mapped[str | None] = mapped_column(String, default=None, index=True)
    value_json: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float] = mapped_column(Float)
    grounded: Mapped[bool] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean)
    field_status: Mapped[str] = mapped_column(String, index=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, default=None)

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="extracted_fields")


class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    superseded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="validation_failures")


class PolicyEvidence(Base):
    __tablename__ = "policy_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="policy_evidence_entries")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String)  # approved|flagged|escalated
    review_reasons_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    package: Mapped["Package"] = relationship(back_populates="decisions")


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)  # approve|edit|reject
    original_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_before_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_after_json: Mapped[str | None] = mapped_column(Text, default=None)
    reviewer: Mapped[str] = mapped_column(String, default="reviewer")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    extraction_run: Mapped["ExtractionRun"] = relationship(back_populates="review_actions")


def _make_engine():
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """Applies Alembic migrations. NOT the schema source of truth by itself —
    the migrations under alembic/versions/ are; this just runs them.
    Tests bypass this and call Base.metadata.create_all() directly against a
    throwaway per-test DB (see tests/conftest.py) for speed/isolation."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")


def create_package(session: Session, package_id: str) -> Package:
    pkg = Package(id=package_id, status="queued")
    session.add(pkg)
    session.commit()
    return pkg


def update_package_status(
    session: Session, package_id: str, status: str, result: dict | None = None, error: str | None = None
) -> None:
    pkg = session.get(Package, package_id)
    pkg.status = status
    if result is not None:
        pkg.result_json = json.dumps(result)
    if error is not None:
        pkg.error = error
    session.commit()


def transition_package_status(
    session: Session,
    package_id: str,
    status: str,
    *,
    reason: str | None = None,
    error: str | None = None,
    result: dict | None = None,
) -> None:
    """The only status-writing path processing code should use — logs one
    audit entry per transition so the full lifecycle is reconstructable."""
    pkg = session.get(Package, package_id)
    previous_status = pkg.status
    update_package_status(session, package_id, status, result=result, error=error)
    log_audit(
        session, package_id, "api", "status_transition",
        {"from": previous_status, "to": status, "reason": reason},
    )


def recover_stale_processing_packages(session: Session) -> list[str]:
    """Called once at app startup. A package can only be "processing" if a
    background task is actively running it — if the app just started, no such
    task exists, so any package found in this state was orphaned by a prior
    crash/restart. Mark it as a retryable failure rather than leaving it stuck."""
    stuck = session.query(Package).filter_by(status="processing").all()
    recovered_ids = []
    for pkg in stuck:
        transition_package_status(
            session, pkg.id, "processing_error",
            reason="restart_recovery", error="process interrupted by application restart",
        )
        recovered_ids.append(pkg.id)
    return recovered_ids


_RETRYABLE_STATUSES = (
    "queued", "review_ready", "completed", "processing_error", "validation_error", "retrieval_error",
)


def try_start_processing(session: Session, package_id: str) -> bool:
    """Atomic compare-and-swap: only transitions package_id to "processing" if
    it isn't already processing. Returns False if the package doesn't exist,
    or another call already won the race and is currently processing it."""
    package = session.get(Package, package_id)
    if package is None:
        return False
    previous_status = package.status
    result = session.execute(
        Package.__table__.update()
        .where(Package.id == package_id, Package.status.in_(_RETRYABLE_STATUSES))
        .values(status="processing")
    )
    session.commit()
    if result.rowcount == 0:
        return False
    log_audit(session, package_id, "api", "status_transition", {"from": previous_status, "to": "processing", "reason": "process started"})
    return True


def log_audit(session: Session, package_id: str, actor: str, action: str, detail: dict | None = None) -> None:
    session.add(AuditLogEntry(
        package_id=package_id, actor=actor, action=action,
        detail_json=json.dumps(detail) if detail is not None else None,
    ))
    session.commit()


def create_document(session: Session, package_id: str, doc: dict) -> Document:
    """Idempotent on (package_id, path): reprocessing a package updates the
    existing Document row instead of inserting a duplicate (uq_document_package_path)."""
    row = (
        session.query(Document)
        .filter_by(package_id=package_id, path=doc["path"])
        .one_or_none()
    )
    if row is None:
        row = Document(id=str(uuid.uuid4()), package_id=package_id, path=doc["path"], manually_overridden=False)
        session.add(row)

    row.doc_type = doc["doc_type"]
    row.has_text_layer = doc["has_text_layer"]
    row.scan_quality = doc.get("scan_quality")
    row.classification_reason = doc.get("classification_reason")
    row.manually_overridden = doc.get("manually_overridden", row.manually_overridden)
    session.commit()
    return row


def create_extraction_run(
    session: Session, document_id: str, schema_name: str, status: str, overall_confidence: float
) -> ExtractionRun:
    prior_attempts = session.query(ExtractionRun).filter_by(document_id=document_id).count()
    row = ExtractionRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        schema_name=schema_name,
        attempt=prior_attempts + 1,
        status=status,
        overall_confidence=overall_confidence,
    )
    session.add(row)
    session.commit()
    return row


def create_extracted_fields(session: Session, extraction_run_id: str, fields: list[dict]) -> list[ExtractedField]:
    rows = [
        ExtractedField(
            extraction_run_id=extraction_run_id,
            name=f["name"],
            parent_field=f.get("parent_field"),
            value_json=json.dumps(f["value"]),
            confidence=f["confidence"],
            grounded=f["grounded"],
            valid=f["valid"],
            field_status=f["field_status"],
            evidence_json=json.dumps(f["evidence"]) if f.get("evidence") is not None else None,
        )
        for f in fields
    ]
    session.add_all(rows)
    session.commit()
    return rows


def create_validation_failures(
    session: Session, extraction_run_id: str, failures: list[dict]
) -> list[ValidationFailure]:
    rows = [
        ValidationFailure(extraction_run_id=extraction_run_id, field=f["field"], rule=f["rule"], reason=f["reason"])
        for f in failures
    ]
    session.add_all(rows)
    session.commit()
    return rows


def create_policy_evidence(session: Session, package_id: str, answers: list[dict]) -> list[PolicyEvidence]:
    rows = [
        PolicyEvidence(
            package_id=package_id, question=a["question"], answer=a["answer"],
            citations_json=json.dumps(a["citations"]),
        )
        for a in answers
    ]
    session.add_all(rows)
    session.commit()
    return rows


def create_decision(session: Session, package_id: str, decision: str, review_reasons: list[str]) -> Decision:
    row = Decision(package_id=package_id, decision=decision, review_reasons_json=json.dumps(review_reasons))
    session.add(row)
    session.commit()
    return row


def record_review_action(
    session: Session,
    extraction_run_id: str,
    field_name: str,
    action: str,
    *,
    original_value=None,
    corrected_value=None,
    validation_before: list | None = None,
    validation_after: list | None = None,
    reviewer: str = "reviewer",
    note: str | None = None,
) -> ReviewAction:
    corrected_value_json = json.dumps(corrected_value) if corrected_value is not None else None
    existing = (
        session.query(ReviewAction)
        .filter_by(extraction_run_id=extraction_run_id, field_name=field_name)
        .order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
        .first()
    )
    if (
        existing is not None
        and existing.action == action
        and existing.corrected_value_json == corrected_value_json
        and existing.reviewer == reviewer
        and existing.note == note
    ):
        return existing

    row = ReviewAction(
        extraction_run_id=extraction_run_id,
        field_name=field_name,
        action=action,
        original_value_json=json.dumps(original_value) if original_value is not None else None,
        corrected_value_json=corrected_value_json,
        validation_before_json=json.dumps(validation_before) if validation_before is not None else None,
        validation_after_json=json.dumps(validation_after) if validation_after is not None else None,
        reviewer=reviewer,
        note=note,
    )
    session.add(row)
    session.commit()
    return row


def persist_extraction_result(session: Session, package_id: str, result: dict) -> None:
    """Fan a ClaimState-shaped result dict out into normalized rows.

    Additive alongside `update_package_status`'s `result_json` blob — this does not
    replace the existing GET /packages/{id} contract, it makes the same data queryable.
    """
    documents = result.get("documents") or []
    if not documents:
        return

    domain = result.get("domain")
    doc_rows = [create_document(session, package_id, doc) for doc in documents]

    claim_doc_row = next((d for d, src in zip(doc_rows, documents) if src["doc_type"] == domain), None)
    if claim_doc_row is None:
        return

    run = create_extraction_run(
        session, claim_doc_row.id, domain or "unknown",
        result.get("extraction_status") or "error",
        result.get("extraction_overall_confidence") or 0.0,
    )

    if result.get("extraction_fields"):
        create_extracted_fields(session, run.id, result["extraction_fields"])
    if result.get("validation_failures"):
        create_validation_failures(session, run.id, result["validation_failures"])
    if result.get("policy_answers"):
        create_policy_evidence(session, package_id, result["policy_answers"])
    if result.get("decision"):
        create_decision(session, package_id, result["decision"], result.get("review_reasons") or [])


def list_packages(session: Session) -> list[Package]:
    return list(session.query(Package).order_by(Package.created_at.desc()).all())


MAX_PAGE_SIZE = 100


def list_packages_filtered(
    session: Session,
    *,
    status: str | None = None,
    domain: str | None = None,
    decision: str | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    validation_rule: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    sort: str = "-created_at",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Package], int]:
    """Filters/sorts/paginates packages. Cheap column filters (status, date range,
    search) run in SQL first; domain/decision/confidence/validation_rule — which
    live on each package's LATEST ExtractionRun/Decision, not on Package itself —
    are applied in Python over that narrowed candidate set.

    ponytail: this fetches the full narrowed candidate set into Python before the
    run/decision-level filters and pagination slice. Fine at portfolio scale
    (hundreds of packages); would need real SQL joins/window functions if package
    counts grew to production scale.
    """
    query = session.query(Package)
    if status is not None:
        query = query.filter(Package.status == status)
    if date_from is not None:
        query = query.filter(Package.created_at >= date_from)
    if date_to is not None:
        query = query.filter(Package.created_at <= date_to)
    if search:
        query = query.filter(Package.id.ilike(f"%{search}%"))

    candidates = query.all()

    def _matches(pkg: Package) -> bool:
        if domain is not None or confidence_min is not None or confidence_max is not None or validation_rule is not None:
            run = latest_extraction_run_for_package(session, pkg.id)
            if run is None:
                return False
            if domain is not None and run.schema_name != domain:
                return False
            if confidence_min is not None and run.overall_confidence < confidence_min:
                return False
            if confidence_max is not None and run.overall_confidence > confidence_max:
                return False
            if validation_rule is not None:
                failures = list_validation_failures_for_run(session, run.id, current_only=True)
                if not any(f.rule == validation_rule for f in failures):
                    return False
        if decision is not None:
            latest = latest_decision_for_package(session, pkg.id)
            if latest is None or latest.decision != decision:
                return False
        return True

    filtered = [pkg for pkg in candidates if _matches(pkg)]

    descending = sort.startswith("-")
    filtered.sort(key=lambda p: p.created_at, reverse=descending)

    total = len(filtered)
    page = max(page, 1)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    start = (page - 1) * page_size
    return filtered[start : start + page_size], total


def get_package(session: Session, package_id: str) -> Package | None:
    return session.get(Package, package_id)


def delete_package(session: Session, package_id: str) -> bool:
    pkg = session.get(Package, package_id)
    if pkg is None:
        return False
    session.delete(pkg)
    session.commit()
    return True


def list_documents(session: Session, package_id: str) -> list[Document]:
    return list(session.query(Document).filter_by(package_id=package_id).order_by(Document.created_at).all())


def get_document(session: Session, document_id: str) -> Document | None:
    return session.get(Document, document_id)


def get_extracted_field(session: Session, field_id: int) -> ExtractedField | None:
    return session.get(ExtractedField, field_id)


def list_extracted_fields_for_run(session: Session, extraction_run_id: str) -> list[ExtractedField]:
    return list(session.query(ExtractedField).filter_by(extraction_run_id=extraction_run_id).all())


def list_validation_failures_for_run(
    session: Session, extraction_run_id: str, current_only: bool = False
) -> list[ValidationFailure]:
    query = session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id)
    if current_only:
        query = query.filter_by(superseded=False)
    return list(query.all())


def supersede_validation_failures(session: Session, extraction_run_id: str) -> None:
    """Marks a run's current validation failures as historical (audit trail) —
    never deletes them — so a rerun's new failures become the only "current" set."""
    session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id, superseded=False).update(
        {"superseded": True}
    )
    session.commit()


def latest_extraction_run_for_package(session: Session, package_id: str) -> ExtractionRun | None:
    return (
        session.query(ExtractionRun)
        .join(Document, ExtractionRun.document_id == Document.id)
        .filter(Document.package_id == package_id)
        .order_by(ExtractionRun.created_at.desc())
        .first()
    )


def list_policy_evidence_for_package(session: Session, package_id: str) -> list[PolicyEvidence]:
    return list(session.query(PolicyEvidence).filter_by(package_id=package_id).all())


def latest_decision_for_package(session: Session, package_id: str) -> Decision | None:
    return (
        session.query(Decision)
        .filter_by(package_id=package_id)
        .order_by(Decision.created_at.desc())
        .first()
    )


def list_decisions_for_package(session: Session, package_id: str) -> list[Decision]:
    return list(session.query(Decision).filter_by(package_id=package_id).order_by(Decision.created_at).all())


def list_audit_events_for_package(session: Session, package_id: str) -> list[AuditLogEntry]:
    return list(
        session.query(AuditLogEntry).filter_by(package_id=package_id).order_by(AuditLogEntry.timestamp).all()
    )


def list_flagged_packages(session: Session) -> list[Package]:
    latest_by_package: dict[str, Decision] = {}
    for decision in session.query(Decision).order_by(Decision.created_at).all():
        latest_by_package[decision.package_id] = decision

    flagged_ids = [
        pid for pid, decision in latest_by_package.items() if decision.decision in ("flagged", "escalated")
    ]
    if not flagged_ids:
        return []
    return list(session.query(Package).filter(Package.id.in_(flagged_ids)).all())
