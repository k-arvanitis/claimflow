import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from claimflow import db, review
from claimflow.config import settings
from claimflow.graph import build_graph
from claimflow.pages import render_page
from claimflow.schemas.documents import DocumentReclassifyRequest, DocumentReclassifyResponse, DocumentSummary
from claimflow.schemas.enums import PackageStatus
from claimflow.schemas.errors import AppError, ErrorBody, ErrorEnvelope
from claimflow.schemas.packages import (
    PackageCreateResponse,
    PackageDeleteResponse,
    PackageDetailResponse,
    PackageStatusResponse,
    PackageSummary,
)
from claimflow.schemas.reporting import (
    AuditEventItem,
    ExportResponse,
    ExtractionFieldExport,
    PolicyAnswerExport,
    PolicyEvidenceItem,
)
from claimflow.schemas.review_read import (
    FieldEvidenceResponse,
    PackageReviewResponse,
    ReviewFieldSummary,
    ReviewValidationFailure,
)
from claimflow.schemas.review_write import (
    DecisionRequest,
    DecisionResponse,
    FieldReviewRequest,
    FieldReviewResponse,
    ValidationFailureItem,
    ValidationRerunRequest,
    ValidationRerunResponse,
)
from claimflow.tracing import get_callback

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = build_graph()
    db.init_db()
    session = db.SessionLocal()
    try:
        recovered = db.recover_stale_processing_packages(session)
        if recovered:
            logger.warning("Recovered %d stale processing package(s) on startup: %s", len(recovered), recovered)
    finally:
        session.close()
    logger.info("ClaimFlow graph initialised")
    yield
    logger.info("ClaimFlow shutting down")


app = FastAPI(title="ClaimFlow", version="0.1.0", lifespan=lifespan)

ERROR_RESPONSES = {404: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}}


@app.exception_handler(AppError)
async def _app_error_handler(request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorBody(code=exc.code, message=exc.detail, details=exc.details)
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorBody(code="HTTP_ERROR", message=str(exc.detail), details=None)
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorEnvelope(
            error=ErrorBody(code="VALIDATION_ERROR", message="Request validation failed", details=exc.errors())
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def _generic_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorEnvelope(
            error=ErrorBody(code="INTERNAL_ERROR", message="Internal server error", details=None)
        ).model_dump(),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


def _classify_exception(graph, config) -> str:
    """An uncaught exception can only happen inside retrieve_node (external
    Qdrant/LLM calls) or an unexpected crash elsewhere — ingest_node and
    extract_node catch their own errors and return them as state instead of
    raising. Inspect the checkpointer's last-known state for this run to see
    which node was reached, and classify accordingly.

    `validation_failures` presence alone doesn't imply retrieve ran: per
    `_should_retrieve` in graph.py, the graph only routes validate -> retrieve
    when validation_failures is non-empty; an empty list means validate
    completed and correctly skipped straight to review. So we must check
    validation_failures truthiness, not just whether policy_answers is
    missing, to avoid misclassifying a post-validate crash (e.g. inside
    review_node) as a retrieval_error when retrieve was never even scheduled.
    """
    try:
        state = graph.get_state(config)
        values = state.values or {}
    except Exception:
        return "processing_error"

    validation_failures = values.get("validation_failures")
    if validation_failures is None:
        # validate never returned a result.
        if values.get("extraction_data") is not None:
            return "validation_error"
        return "processing_error"

    if validation_failures and "policy_answers" not in values:
        # _should_retrieve would have routed here to "retrieve"; it never completed.
        return "retrieval_error"

    return "processing_error"


def _run_claim(graph, package_id: str, pkg_dir: Path, doc_type_overrides: dict[str, str] | None = None) -> None:
    session = db.SessionLocal()
    thread_id = str(uuid.uuid4())
    config = {"callbacks": get_callback(), "configurable": {"thread_id": thread_id}}
    try:
        state = {"package_dir": str(pkg_dir), "domain": None, "doc_type_overrides": doc_type_overrides or {}}
        result = graph.invoke(state, config=config)

        response = {
            "decision": result.get("decision"),
            "extraction_data": result.get("extraction_data"),
            "domain": result.get("domain"),
            "documents": result.get("documents", []),
            "ocr_log": result.get("ocr_log", []),
            "extraction_overall_confidence": result.get("extraction_overall_confidence"),
            "extraction_fields": result.get("extraction_fields", []),
            "validation_failures": result.get("validation_failures", []),
            "policy_answers": result.get("policy_answers", []),
            "review_reasons": result.get("review_reasons", []),
            "error": result.get("error"),
        }
        db.log_audit(session, package_id, "api", "validate", {"validation_failures": response["validation_failures"]})

        if response["error"]:
            final_status = "processing_error"
        elif response["decision"] == "approved":
            final_status = "completed"
        else:
            final_status = "review_ready"

        db.transition_package_status(
            session, package_id, final_status, reason=f"graph completed, decision={response['decision']}", result=response,
        )
        db.persist_extraction_result(session, package_id, result)
    except Exception as exc:
        logger.error("Background claim processing failed: %s", exc, exc_info=True)
        failure_status = _classify_exception(graph, config)
        db.transition_package_status(session, package_id, failure_status, reason=str(exc), error=str(exc))
    finally:
        session.close()


@app.post(
    "/packages",
    response_model=PackageCreateResponse,
    tags=["packages"],
    summary="Upload documents and create a new claim package",
    responses=ERROR_RESPONSES,
)
async def create_package(files: list[UploadFile], background_tasks: BackgroundTasks):
    package_id = str(uuid.uuid4())
    pkg_dir = Path(settings.storage_dir) / package_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = pkg_dir / Path(f.filename).name
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)

    session = db.SessionLocal()
    try:
        db.create_package(session, package_id)
        db.log_audit(session, package_id, "api", "upload", {"filenames": [f.filename for f in files]})
        db.transition_package_status(session, package_id, "queued", reason="upload complete")
    finally:
        session.close()

    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.QUEUED)


@app.get(
    "/packages",
    response_model=list[PackageSummary],
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
async def list_packages():
    session = db.SessionLocal()
    try:
        return [
            PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at)
            for pkg in db.list_packages(session)
        ]
    finally:
        session.close()


@app.get(
    "/packages/{package_id}",
    response_model=PackageDetailResponse,
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
async def get_package(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        return PackageDetailResponse(
            package_id=pkg.id,
            status=pkg.status,
            result=json.loads(pkg.result_json) if pkg.result_json else None,
            error=pkg.error,
        )
    finally:
        session.close()


@app.delete(
    "/packages/{package_id}",
    response_model=PackageDeleteResponse,
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
async def delete_package(package_id: str):
    session = db.SessionLocal()
    try:
        deleted = db.delete_package(session, package_id)
        if not deleted:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    shutil.rmtree(pkg_dir, ignore_errors=True)
    return PackageDeleteResponse(package_id=package_id, status="deleted")


@app.post(
    "/packages/{package_id}/process",
    response_model=PackageCreateResponse,
    tags=["packages"],
    summary="Re-run extraction and validation for an existing package",
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def process_package(package_id: str, background_tasks: BackgroundTasks):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        overrides = {
            Path(doc.path).name: doc.doc_type
            for doc in db.list_documents(session, package_id)
            if doc.manually_overridden
        }
        started = db.try_start_processing(session, package_id)
        if not started:
            raise AppError(409, "PROCESSING_IN_PROGRESS", "Package is already being processed")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir, overrides)
    return PackageCreateResponse(package_id=package_id, status=PackageStatus.PROCESSING)


@app.get(
    "/packages/{package_id}/status",
    response_model=PackageStatusResponse,
    tags=["packages"],
    responses=ERROR_RESPONSES,
)
async def get_package_status(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        return PackageStatusResponse(package_id=pkg.id, status=pkg.status)
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/documents",
    response_model=list[DocumentSummary],
    tags=["documents"],
    responses=ERROR_RESPONSES,
)
async def list_package_documents(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            DocumentSummary(
                document_id=doc.id, path=doc.path, doc_type=doc.doc_type,
                has_text_layer=doc.has_text_layer, scan_quality=doc.scan_quality,
                classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
            )
            for doc in db.list_documents(session, package_id)
        ]
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/documents/{document_id}",
    response_model=DocumentSummary,
    tags=["documents"],
    responses=ERROR_RESPONSES,
)
async def get_package_document(package_id: str, document_id: str):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
        return DocumentSummary(
            document_id=doc.id, path=doc.path, doc_type=doc.doc_type,
            has_text_layer=doc.has_text_layer, scan_quality=doc.scan_quality,
            classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
        )
    finally:
        session.close()


@app.post(
    "/packages/{package_id}/documents/{document_id}/reclassify",
    response_model=DocumentReclassifyResponse,
    tags=["documents"],
    responses=ERROR_RESPONSES,
)
async def reclassify_document(package_id: str, document_id: str, body: DocumentReclassifyRequest):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")

        doc.doc_type = body.doc_type.value
        doc.classification_reason = "manual override"
        doc.manually_overridden = True
        session.commit()

        db.log_audit(
            session, package_id, body.reviewer, "reclassify",
            {"document_id": document_id, "doc_type": doc.doc_type},
        )
        return DocumentReclassifyResponse(
            document_id=doc.id, doc_type=doc.doc_type,
            classification_reason=doc.classification_reason, manually_overridden=doc.manually_overridden,
        )
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/documents/{document_id}/pages/{page}",
    tags=["documents"],
    responses=ERROR_RESPONSES,
)
async def get_document_page_image(package_id: str, document_id: str, page: int, bbox: str | None = None):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "DOCUMENT_NOT_FOUND", "Document does not exist")
    finally:
        session.close()

    parsed_bbox = [float(v) for v in bbox.split(",")] if bbox else None
    image_bytes = render_page(doc.path, page, parsed_bbox)
    if image_bytes is None:
        raise AppError(404, "PAGE_RENDER_FAILED", "Page could not be rendered")
    return Response(content=image_bytes, media_type="image/png")


@app.get(
    "/packages/{package_id}/fields/{field_id}/evidence",
    response_model=FieldEvidenceResponse,
    tags=["review"],
    responses=ERROR_RESPONSES,
)
async def get_field_evidence(package_id: str, field_id: int):
    session = db.SessionLocal()
    try:
        field = db.get_extracted_field(session, field_id)
        if field is None:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        run = session.get(db.ExtractionRun, field.extraction_run_id)
        doc = session.get(db.Document, run.document_id) if run else None
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        return FieldEvidenceResponse(
            field_id=field.id,
            name=field.name,
            value=json.loads(field.value_json) if field.value_json else None,
            confidence=field.confidence,
            evidence=json.loads(field.evidence_json) if field.evidence_json else None,
        )
    finally:
        session.close()


@app.get(
    "/reviews/queue",
    response_model=list[PackageSummary],
    tags=["review"],
    responses=ERROR_RESPONSES,
)
async def reviews_queue():
    session = db.SessionLocal()
    try:
        return [
            PackageSummary(package_id=pkg.id, status=pkg.status, created_at=pkg.created_at)
            for pkg in db.list_flagged_packages(session)
        ]
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/review",
    response_model=PackageReviewResponse,
    tags=["review"],
    summary="Get extracted fields and validation failures for reviewer queue",
    responses=ERROR_RESPONSES,
)
async def get_package_review(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")

        run = db.latest_extraction_run_for_package(session, package_id)
        fields = db.list_extracted_fields_for_run(session, run.id) if run else []
        failures = db.list_validation_failures_for_run(session, run.id) if run else []

        return PackageReviewResponse(
            package_id=package_id,
            status=pkg.status,
            fields=[
                ReviewFieldSummary(
                    field_id=f.id, name=f.name,
                    value=json.loads(f.value_json) if f.value_json else None,
                    confidence=f.confidence, field_status=f.field_status,
                )
                for f in fields
            ],
            validation_failures=[
                ReviewValidationFailure(field=vf.field, rule=vf.rule, reason=vf.reason) for vf in failures
            ],
        )
    finally:
        session.close()


@app.post(
    "/packages/{package_id}/fields/{field_id}/review",
    response_model=FieldReviewResponse,
    tags=["review"],
    summary="Record a reviewer's approval or correction for a single field",
    responses=ERROR_RESPONSES,
)
async def submit_field_review(package_id: str, field_id: int, body: FieldReviewRequest):
    session = db.SessionLocal()
    try:
        field = db.get_extracted_field(session, field_id)
        if field is None:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")
        run = session.get(db.ExtractionRun, field.extraction_run_id)
        doc = session.get(db.Document, run.document_id) if run else None
        if doc is None or doc.package_id != package_id:
            raise AppError(404, "FIELD_NOT_FOUND", "Field does not exist")

        failures_before = db.list_validation_failures_for_run(session, run.id)
        validation_before = [f.reason for f in failures_before if f.field == field.name]

        action = db.record_review_action(
            session, run.id, field.name, body.action.value,
            original_value=json.loads(field.value_json) if field.value_json else None,
            corrected_value=body.corrected_value,
            validation_before=validation_before,
            validation_after=body.validation_after,
            reviewer=body.reviewer,
            note=body.note,
        )
        db.log_audit(session, package_id, action.reviewer, "review_edit", {"field": field.name, "action": action.action})
        return FieldReviewResponse(
            field_id=field_id, action=action.action, reviewer=action.reviewer,
            corrected_value=json.loads(action.corrected_value_json) if action.corrected_value_json else None,
        )
    finally:
        session.close()


@app.post(
    "/packages/{package_id}/validation/re-run",
    response_model=ValidationRerunResponse,
    tags=["review"],
    responses=ERROR_RESPONSES,
)
async def rerun_package_validation(package_id: str, body: ValidationRerunRequest):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        result = json.loads(pkg.result_json) if pkg.result_json else {}
    finally:
        session.close()

    domain = result.get("domain")
    merged = dict(result.get("extraction_data") or {})
    merged.update(body.corrected_fields)
    failures = review.rerun_validation(domain, merged)
    return ValidationRerunResponse(
        validation_failures=[ValidationFailureItem(field=f["field"], rule=f["rule"], reason=f["reason"]) for f in failures]
    )


@app.post(
    "/packages/{package_id}/decision",
    response_model=DecisionResponse,
    tags=["review"],
    summary="Submit the final approve/deny decision for a package",
    responses=ERROR_RESPONSES,
)
async def submit_package_decision(package_id: str, body: DecisionRequest):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        decision = db.create_decision(session, package_id, body.decision.value, body.review_reasons)
        db.log_audit(session, package_id, "reviewer", "decision", {"decision": decision.decision})
        return DecisionResponse(package_id=package_id, decision=decision.decision)
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/policy-evidence",
    response_model=list[PolicyEvidenceItem],
    tags=["reporting"],
    responses=ERROR_RESPONSES,
)
async def get_policy_evidence(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            PolicyEvidenceItem(
                question=pe.question, answer=pe.answer,
                citations=json.loads(pe.citations_json),
            )
            for pe in db.list_policy_evidence_for_package(session, package_id)
        ]
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/audit",
    response_model=list[AuditEventItem],
    tags=["reporting"],
    responses=ERROR_RESPONSES,
)
async def get_audit_trail(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            AuditEventItem(
                actor=entry.actor, action=entry.action, timestamp=entry.timestamp,
                detail=json.loads(entry.detail_json) if entry.detail_json else None,
            )
            for entry in db.list_audit_events_for_package(session, package_id)
        ]
    finally:
        session.close()


@app.get(
    "/packages/{package_id}/export",
    response_model=ExportResponse,
    tags=["reporting"],
    summary="Export the full claim result: decision, fields, and policy evidence",
    responses=ERROR_RESPONSES,
)
async def export_package(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise AppError(404, "PACKAGE_NOT_FOUND", "Package does not exist")
        result = json.loads(pkg.result_json) if pkg.result_json else {}
        return ExportResponse(
            package_id=package_id,
            status=pkg.status,
            decision=result.get("decision"),
            domain=result.get("domain"),
            extraction_fields=[
                ExtractionFieldExport(**f) for f in result.get("extraction_fields", [])
            ],
            validation_failures=result.get("validation_failures", []),
            policy_answers=[
                PolicyAnswerExport(**a) for a in result.get("policy_answers", [])
            ],
        )
    finally:
        session.close()
