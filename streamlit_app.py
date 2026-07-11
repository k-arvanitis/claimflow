"""ClaimFlow review UI — upload a document package and inspect the pipeline result."""
import json
import shutil
import tempfile
import uuid
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st

from claimflow import db
from claimflow.graph import build_graph
from claimflow.nodes.ingest import ocr_page
from claimflow.review import diff_list_field as _diff_list_field
from claimflow.review import rerun_validation as _rerun_validation
from claimflow.tracing import get_callback

db.init_db()

st.set_page_config(page_title="ClaimFlow", page_icon="📋", layout="wide")
st.title("ClaimFlow — Document Intelligence Review")

_DECISION_COLOR = {"approved": "green", "flagged": "orange", "escalated": "red"}
_DOMAIN_LABEL = {"cms1500": "Health Insurance (CMS-1500)", "xactimate": "Property Insurance (Xactimate)", "loan": "SBA Loan Application"}


@st.cache_resource
def get_graph():
    return build_graph()


def _run(pkg_dir: str) -> dict:
    return get_graph().invoke(
        {"package_dir": pkg_dir, "domain": None},
        config={"callbacks": get_callback(), "configurable": {"thread_id": str(uuid.uuid4())}},
    )


def _render_page(pdf_path: str, page_no: int, bbox: list[float] | None) -> bytes | None:
    """Render a PDF page as PNG bytes, drawing a red box around the evidence if bbox is known."""
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_no - 1]
        if bbox:
            page.draw_rect(fitz.Rect(bbox), color=(1, 0, 0), width=2)
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    except Exception:
        return None


def _page_text(pdf_path: str, page_no: int) -> str:
    """Text for one page — native text layer if present, else on-demand OCR (same fallback ingest uses)."""
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_no - 1]
        text = page.get_text()
        if len(text.strip()) >= 50:
            return text
        return ocr_page(doc, page_no - 1) or "(no text recovered from this page)"
    except Exception:
        return "(could not read page)"


# ── Sidebar: input mode ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("Input")
    mode = st.radio("Source", ["Upload files", "Local package directory"])

    if mode == "Upload files":
        uploads = st.file_uploader(
            "Documents (PDF, DOCX, images)",
            type=["pdf", "docx", "png", "jpg", "jpeg", "webp", "tiff", "bmp"],
            accept_multiple_files=True,
        )
        run_button = st.button("Process", disabled=not uploads, type="primary")
    else:
        pkg_path = st.text_input("Package directory path")
        run_button = st.button("Process", disabled=not pkg_path, type="primary")

# ── Run ───────────────────────────────────────────────────────────────────────
# The uploaded package dir is kept alive in session state (not deleted after the
# run) so evidence pages can be re-rendered with bbox overlays below.
if "result" not in st.session_state:
    st.session_state["result"] = None
    st.session_state["pkg_dir"] = None
    st.session_state["pkg_tmp"] = None
    st.session_state["review"] = {}
    st.session_state["package_id"] = None

if run_button:
    if st.session_state["pkg_tmp"]:
        shutil.rmtree(st.session_state["pkg_tmp"], ignore_errors=True)

    package_id = str(uuid.uuid4())
    st.session_state["package_id"] = package_id
    session = db.SessionLocal()
    try:
        db.create_package(session, package_id)

        with st.spinner("Running pipeline…"):
            if mode == "Upload files":
                tmp = tempfile.mkdtemp()
                pkg_dir = Path(tmp) / "package"
                pkg_dir.mkdir()
                for f in uploads:
                    (pkg_dir / f.name).write_bytes(f.read())
                st.session_state["pkg_tmp"] = tmp
                st.session_state["pkg_dir"] = str(pkg_dir)
                db.log_audit(session, package_id, "reviewer", "upload", {"filenames": [f.name for f in uploads]})
            else:
                st.session_state["pkg_tmp"] = None
                st.session_state["pkg_dir"] = pkg_path
                db.log_audit(session, package_id, "reviewer", "upload", {"package_dir": pkg_path})

            db.log_audit(session, package_id, "reviewer", "extract")
            result = _run(st.session_state["pkg_dir"])
            st.session_state["result"] = result
            st.session_state["review"] = {}
            db.log_audit(session, package_id, "reviewer", "validate", {
                "validation_failures": result.get("validation_failures", []),
                "decision": result.get("decision"),
            })
            db.update_package_status(session, package_id, "completed", result={
                "decision": result.get("decision"),
                "domain": result.get("domain"),
                "validation_failures": result.get("validation_failures", []),
            })
    finally:
        session.close()

result = st.session_state["result"]

# ── Display ───────────────────────────────────────────────────────────────────
if result:
    decision = result.get("decision") or "unknown"
    color = _DECISION_COLOR.get(decision, "grey")
    domain_key = result.get("domain") or "unknown"
    domain_label = _DOMAIN_LABEL.get(domain_key, domain_key)
    confidence = result.get("extraction_overall_confidence")

    # Header row
    col1, col2, col3 = st.columns(3)
    col1.metric("Decision", decision.upper())
    col2.metric("Domain", domain_label)
    col3.metric("Confidence", f"{confidence:.0%}" if confidence is not None else "—")

    st.markdown(f"**Status:** :{color}[{decision.upper()}]")
    st.caption("Human review is triggered only for low-confidence, contradictory, or high-risk fields.")

    if result.get("error"):
        st.error(f"Pipeline error: {result['error']}")

    # Documents — classification + OCR proof
    documents = result.get("documents") or []
    if documents:
        st.subheader(f"Documents ({len(documents)})")
        doc_rows = [
            {
                "File": Path(d["path"]).name,
                "Classified as": d["doc_type"],
                "Text layer": "born-digital" if d["has_text_layer"] else "OCR fallback used",
                "Scan quality (heuristic)": f"{d['scan_quality']:.0%}" if d.get("scan_quality") is not None else "—",
            }
            for d in documents
        ]
        st.dataframe(doc_rows, use_container_width=True)

    ocr_log = result.get("ocr_log") or []
    if ocr_log:
        with st.expander(f"OCR fallback log ({len(ocr_log)})"):
            for line in ocr_log:
                if "low-quality scan" in line:
                    st.warning(line)
                else:
                    st.caption(line)

    # Review reasons
    reasons = result.get("review_reasons") or []
    if reasons:
        st.subheader("Review Reasons")
        for r in reasons:
            st.warning(r)

    # Validation failures — deterministic domain rules
    failures = result.get("validation_failures") or []
    failures_by_field: dict[str, list] = {}
    for f in failures:
        failures_by_field.setdefault(f["field"], []).append(f)

    if failures:
        st.subheader(f"Validation Failures ({len(failures)})")
        for f in failures:
            st.error(f"**{f['field']}** [{f['rule']}] — {f['reason']}")
    elif result.get("extraction_data"):
        st.success("All deterministic validation rules passed.")

    # Extraction data + interactive review queue
    extraction = result.get("extraction_data")
    extraction_fields = result.get("extraction_fields") or []
    if extraction:
        fields_meta = {m["name"]: m for m in extraction_fields}
        simple_fields = {k: v for k, v in extraction.items() if not isinstance(v, (list, dict))}

        st.subheader("Extracted Fields — Review Queue")
        review = st.session_state["review"]

        for k, v in simple_fields.items():
            meta = fields_meta.get(k, {})
            conf = meta.get("confidence")
            evidence = meta.get("evidence")
            source = f"p.{evidence['page']}: “{evidence['text'][:80]}”" if evidence else "—"
            field_failures = failures_by_field.get(k, [])

            if k not in review:
                review[k] = {"action": "approve", "corrected_value": str(v)}

            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 3])
                c1.markdown(f"**{k}**")
                c1.caption(f"Confidence: {conf:.0%}" if conf is not None else "Confidence: —")
                c1.caption(f"Source: {source}")

                if field_failures:
                    for ff in field_failures:
                        c1.caption(f"⚠️ Suggested correction — {ff['reason']}")

                action = c2.radio(
                    "Action", ["approve", "edit", "reject"],
                    horizontal=True, key=f"action_{k}",
                    index=["approve", "edit", "reject"].index(review[k]["action"]),
                )
                review[k]["action"] = action

                if action == "edit":
                    review[k]["corrected_value"] = c3.text_input(
                        "Corrected value", value=review[k]["corrected_value"], key=f"value_{k}",
                    )
                else:
                    c3.markdown(f"Value: `{v}`")

        # Nested/list/table fields (diagnosis_codes, service_lines, line_items, ...) —
        # editable per-row: edit cells, add rows, delete rows to reject them.
        list_fields = {k: v for k, v in extraction.items() if isinstance(v, list) and v}
        list_review: dict[str, dict] = {}
        for k, v in list_fields.items():
            is_scalar_list = not isinstance(v[0], dict)
            st.markdown(f"**{k}**")
            editor_rows = [{"value": item} for item in v] if is_scalar_list else v
            edited_rows = st.data_editor(
                editor_rows, num_rows="dynamic", use_container_width=True, key=f"editor_{k}",
            )
            edited_values = [r["value"] for r in edited_rows] if is_scalar_list else list(edited_rows)
            note = st.text_input(f"Review note for {k} (optional)", key=f"note_{k}") or None
            list_review[k] = {"edited": edited_values, "diff": _diff_list_field(k, v, edited_values, fields_meta, note)}

        # Export — reviewed record, ready for downstream handoff
        export_record = {
            "decision": decision,
            "domain": domain_key,
            "fields": {
                **{
                    k: {
                        "original_value": simple_fields[k],
                        "action": review[k]["action"],
                        "final_value": review[k]["corrected_value"] if review[k]["action"] == "edit" else simple_fields[k],
                        "confidence": fields_meta.get(k, {}).get("confidence"),
                    }
                    for k in simple_fields
                },
                **{k: lr["diff"] for k, lr in list_review.items()},
            },
        }
        approved = sum(1 for r in review.values() if r["action"] == "approve")
        edited = sum(1 for r in review.values() if r["action"] == "edit")
        rejected = sum(1 for r in review.values() if r["action"] == "reject")
        st.caption(f"Review status: {approved} approved · {edited} edited · {rejected} rejected")

        package_id = st.session_state.get("package_id")

        if st.button("Re-run validation on reviewed values"):
            merged = dict(extraction)
            for k in simple_fields:
                merged[k] = review[k]["corrected_value"] if review[k]["action"] == "edit" else simple_fields[k]
            for k, lr in list_review.items():
                merged[k] = lr["edited"]
            new_failures = _rerun_validation(domain_key, merged)
            if package_id:
                session = db.SessionLocal()
                try:
                    db.log_audit(session, package_id, "reviewer", "review_edit", {
                        "field_actions": {k: r["action"] for k, r in review.items()},
                        "remaining_failures": new_failures,
                    })
                finally:
                    session.close()
            if new_failures:
                st.subheader(f"Re-validated: {len(new_failures)} failure(s) remain")
                for f in new_failures:
                    st.error(f"**{f['field']}** [{f['rule']}] — {f['reason']}")
            else:
                st.success("Re-validated: all deterministic rules pass on reviewed values.")
        if st.download_button(
            "Export reviewed record (JSON)",
            data=json.dumps(export_record, indent=2, default=str),
            file_name="claimflow_review.json",
            mime="application/json",
        ) and package_id:
            session = db.SessionLocal()
            try:
                db.log_audit(session, package_id, "reviewer", "export", {
                    "field_actions": {k: r["action"] for k, r in review.items()},
                })
            finally:
                session.close()

        # Side-by-side page viewer — visual proof a value traces back to a specific page
        claim_doc = next((d for d in documents if d["doc_type"] == domain_key), None)
        fields_with_evidence = [m for m in extraction_fields if m.get("evidence")]
        if claim_doc:
            st.subheader("Source Evidence — Page Viewer")

            jump_options = ["(none)"] + [m["name"] for m in fields_with_evidence]
            jump_to = st.selectbox("Jump to a field's evidence page", options=jump_options)

            page_key = "evidence_page"
            if jump_to != "(none)":
                meta = next(m for m in fields_with_evidence if m["name"] == jump_to)
                st.session_state[page_key] = meta["evidence"]["page"]
            current_page = st.session_state.get(page_key, 1)

            doc_for_page = fitz.open(claim_doc["path"])
            total_pages = len(doc_for_page)
            doc_for_page.close()

            nav1, nav2, nav3 = st.columns([1, 2, 1])
            if nav1.button("← Previous", disabled=current_page <= 1):
                current_page = max(1, current_page - 1)
            nav2.markdown(f"<div style='text-align:center'>Page {current_page} / {total_pages}</div>", unsafe_allow_html=True)
            if nav3.button("Next →", disabled=current_page >= total_pages):
                current_page = min(total_pages, current_page + 1)
            st.session_state[page_key] = current_page

            bbox = None
            if jump_to != "(none)":
                meta = next(m for m in fields_with_evidence if m["name"] == jump_to)
                if meta["evidence"]["page"] == current_page:
                    bbox = meta["evidence"].get("bbox")

            left, right = st.columns(2)
            img = _render_page(claim_doc["path"], current_page, bbox)
            with left:
                if img:
                    st.image(img, caption=f"Page {current_page}" + (" — evidence highlighted" if bbox else ""))
                else:
                    st.caption("Could not render this page.")
            with right:
                st.text_area("Extracted text", _page_text(claim_doc["path"], current_page), height=400, disabled=True)

    # Policy answers
    answers = result.get("policy_answers") or []
    if answers:
        st.subheader(f"Policy Q&A ({len(answers)} questions)")
        for qa in answers:
            with st.expander(qa["question"]):
                st.write(qa["answer"])
                if qa.get("citations"):
                    st.caption("Sources: " + ", ".join(qa["citations"]))

    # Raw result
    with st.expander("Raw result (JSON)"):
        st.json(result)
