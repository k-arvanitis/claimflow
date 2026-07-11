"""SQLite-backed job status + audit log, shared by api/main.py and streamlit_app.py.
NOT encrypted at rest — see TODO.md."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from claimflow.config import settings


class Base(DeclarativeBase):
    pass


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|processing|completed|failed
    result_json: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor: Mapped[str] = mapped_column(String)  # e.g. "api", "reviewer"
    action: Mapped[str] = mapped_column(String)  # e.g. "upload", "extract", "validate", "review_edit"
    detail_json: Mapped[str | None] = mapped_column(Text, default=None)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    path: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    has_text_layer: Mapped[bool] = mapped_column(Boolean)
    scan_quality: Mapped[float | None] = mapped_column(Float, default=None)
    classification_reason: Mapped[str | None] = mapped_column(Text, default=None)
    manually_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    schema_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # pass|review|error
    overall_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    name: Mapped[str] = mapped_column(String)
    value_json: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float] = mapped_column(Float)
    grounded: Mapped[bool] = mapped_column(Boolean)
    valid: Mapped[bool] = mapped_column(Boolean)
    field_status: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str | None] = mapped_column(Text, default=None)


class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PolicyEvidence(Base):
    __tablename__ = "policy_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    decision: Mapped[str] = mapped_column(String)  # approved|flagged|escalated
    review_reasons_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.id"))
    field_name: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)  # approve|edit|reject
    original_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_before_json: Mapped[str | None] = mapped_column(Text, default=None)
    validation_after_json: Mapped[str | None] = mapped_column(Text, default=None)
    reviewer: Mapped[str] = mapped_column(String, default="reviewer")
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


def _make_engine():
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


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


def log_audit(session: Session, package_id: str, actor: str, action: str, detail: dict | None = None) -> None:
    session.add(AuditLogEntry(
        package_id=package_id, actor=actor, action=action,
        detail_json=json.dumps(detail) if detail is not None else None,
    ))
    session.commit()


def create_document(session: Session, package_id: str, doc: dict) -> Document:
    row = Document(
        id=str(uuid.uuid4()),
        package_id=package_id,
        path=doc["path"],
        doc_type=doc["doc_type"],
        has_text_layer=doc["has_text_layer"],
        scan_quality=doc.get("scan_quality"),
        classification_reason=doc.get("classification_reason"),
        manually_overridden=doc.get("manually_overridden", False),
    )
    session.add(row)
    session.commit()
    return row


def create_extraction_run(
    session: Session, document_id: str, schema_name: str, status: str, overall_confidence: float
) -> ExtractionRun:
    row = ExtractionRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        schema_name=schema_name,
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
    row = ReviewAction(
        extraction_run_id=extraction_run_id,
        field_name=field_name,
        action=action,
        original_value_json=json.dumps(original_value) if original_value is not None else None,
        corrected_value_json=json.dumps(corrected_value) if corrected_value is not None else None,
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


def get_package(session: Session, package_id: str) -> Package | None:
    return session.get(Package, package_id)


def delete_package(session: Session, package_id: str) -> bool:
    pkg = session.get(Package, package_id)
    if pkg is None:
        return False

    # ORM-level session.delete() on fetched instances (not bulk .delete()) so that
    # instances already held by the caller (same identity-mapped objects) are marked
    # deleted-and-expunged rather than expired; expire_on_commit would otherwise try
    # to refresh them from rows that no longer exist and raise ObjectDeletedError.
    documents = session.query(Document).filter_by(package_id=package_id).all()
    if documents:
        document_ids = [d.id for d in documents]
        runs = session.query(ExtractionRun).filter(ExtractionRun.document_id.in_(document_ids)).all()
        if runs:
            run_ids = [r.id for r in runs]
            for field in session.query(ExtractedField).filter(ExtractedField.extraction_run_id.in_(run_ids)).all():
                session.delete(field)
            for failure in session.query(ValidationFailure).filter(
                ValidationFailure.extraction_run_id.in_(run_ids)
            ).all():
                session.delete(failure)
            for action in session.query(ReviewAction).filter(
                ReviewAction.extraction_run_id.in_(run_ids)
            ).all():
                session.delete(action)
            for run in runs:
                session.delete(run)
        for doc in documents:
            session.delete(doc)

    for evidence in session.query(PolicyEvidence).filter_by(package_id=package_id).all():
        session.delete(evidence)
    for decision in session.query(Decision).filter_by(package_id=package_id).all():
        session.delete(decision)
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


def list_validation_failures_for_run(session: Session, extraction_run_id: str) -> list[ValidationFailure]:
    return list(session.query(ValidationFailure).filter_by(extraction_run_id=extraction_run_id).all())


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
