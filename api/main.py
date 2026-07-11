import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from claimflow import db
from claimflow.config import settings
from claimflow.graph import build_graph
from claimflow.pages import render_page
from claimflow.tracing import get_callback

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = build_graph()
    db.init_db()
    logger.info("ClaimFlow graph initialised")
    yield
    logger.info("ClaimFlow shutting down")


app = FastAPI(title="ClaimFlow", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def _generic_handler(request, exc):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    return {"status": "ok"}


def _run_claim(graph, package_id: str, pkg_dir: Path) -> None:
    session = db.SessionLocal()
    try:
        db.update_package_status(session, package_id, "processing")
        db.log_audit(session, package_id, "api", "extract")

        thread_id = str(uuid.uuid4())
        state = {"package_dir": str(pkg_dir), "domain": None}
        config = {
            "callbacks": get_callback(),
            "configurable": {"thread_id": thread_id},
        }
        result = graph.invoke(state, config=config)

        response = {
            "decision": result.get("decision"),
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
        db.update_package_status(session, package_id, "failed" if response["error"] else "completed", result=response)
        if not response["error"]:
            db.persist_extraction_result(session, package_id, result)
    except Exception as exc:
        logger.error("Background claim processing failed: %s", exc, exc_info=True)
        db.update_package_status(session, package_id, "failed", error=str(exc))
    finally:
        session.close()


@app.post("/packages")
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
    finally:
        session.close()

    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return {"package_id": package_id, "status": "queued"}


@app.get("/packages")
async def list_packages():
    session = db.SessionLocal()
    try:
        return [
            {"package_id": pkg.id, "status": pkg.status, "created_at": pkg.created_at.isoformat()}
            for pkg in db.list_packages(session)
        ]
    finally:
        session.close()


@app.get("/packages/{package_id}")
async def get_package(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="Package not found")
        return {
            "package_id": pkg.id,
            "status": pkg.status,
            "result": json.loads(pkg.result_json) if pkg.result_json else None,
            "error": pkg.error,
        }
    finally:
        session.close()


@app.delete("/packages/{package_id}")
async def delete_package(package_id: str):
    session = db.SessionLocal()
    try:
        deleted = db.delete_package(session, package_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Package not found")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    shutil.rmtree(pkg_dir, ignore_errors=True)
    return {"package_id": package_id, "status": "deleted"}


@app.post("/packages/{package_id}/process")
async def process_package(package_id: str, background_tasks: BackgroundTasks):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="Package not found")
    finally:
        session.close()

    pkg_dir = Path(settings.storage_dir) / package_id
    background_tasks.add_task(_run_claim, app.state.graph, package_id, pkg_dir)
    return {"package_id": package_id, "status": "queued"}


@app.get("/packages/{package_id}/status")
async def get_package_status(package_id: str):
    session = db.SessionLocal()
    try:
        pkg = db.get_package(session, package_id)
        if pkg is None:
            raise HTTPException(status_code=404, detail="Package not found")
        return {"package_id": pkg.id, "status": pkg.status}
    finally:
        session.close()


@app.get("/packages/{package_id}/documents")
async def list_package_documents(package_id: str):
    session = db.SessionLocal()
    try:
        return [
            {
                "document_id": doc.id, "path": doc.path, "doc_type": doc.doc_type,
                "has_text_layer": doc.has_text_layer, "scan_quality": doc.scan_quality,
            }
            for doc in db.list_documents(session, package_id)
        ]
    finally:
        session.close()


@app.get("/packages/{package_id}/documents/{document_id}")
async def get_package_document(package_id: str, document_id: str):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": doc.id, "path": doc.path, "doc_type": doc.doc_type,
            "has_text_layer": doc.has_text_layer, "scan_quality": doc.scan_quality,
        }
    finally:
        session.close()


@app.get("/packages/{package_id}/documents/{document_id}/pages/{page}")
async def get_document_page_image(package_id: str, document_id: str, page: int, bbox: str | None = None):
    session = db.SessionLocal()
    try:
        doc = db.get_document(session, document_id)
        if doc is None or doc.package_id != package_id:
            raise HTTPException(status_code=404, detail="Document not found")
    finally:
        session.close()

    parsed_bbox = [float(v) for v in bbox.split(",")] if bbox else None
    image_bytes = render_page(doc.path, page, parsed_bbox)
    if image_bytes is None:
        raise HTTPException(status_code=404, detail="Page could not be rendered")
    return Response(content=image_bytes, media_type="image/png")


@app.get("/packages/{package_id}/fields/{field_id}/evidence")
async def get_field_evidence(package_id: str, field_id: int):
    session = db.SessionLocal()
    try:
        field = db.get_extracted_field(session, field_id)
        if field is None:
            raise HTTPException(status_code=404, detail="Field not found")
        run = session.get(db.ExtractionRun, field.extraction_run_id)
        doc = session.get(db.Document, run.document_id) if run else None
        if doc is None or doc.package_id != package_id:
            raise HTTPException(status_code=404, detail="Field not found")
        return {
            "field_id": field.id,
            "name": field.name,
            "value": json.loads(field.value_json) if field.value_json else None,
            "confidence": field.confidence,
            "evidence": json.loads(field.evidence_json) if field.evidence_json else None,
        }
    finally:
        session.close()
