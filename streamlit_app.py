"""ClaimFlow review UI — upload a document package and inspect the pipeline result."""
import json
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from claimflow.graph import build_graph
from claimflow.tracing import get_callback

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
        config={"callbacks": get_callback()},
    )


# ── Sidebar: input mode ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("Input")
    mode = st.radio("Source", ["Upload files", "Local package directory"])

    if mode == "Upload files":
        uploads = st.file_uploader("PDF files", type="pdf", accept_multiple_files=True)
        run_button = st.button("Process", disabled=not uploads, type="primary")
    else:
        pkg_path = st.text_input("Package directory path")
        run_button = st.button("Process", disabled=not pkg_path, type="primary")

# ── Run ───────────────────────────────────────────────────────────────────────
result = None

if run_button:
    with st.spinner("Running pipeline…"):
        if mode == "Upload files":
            tmp = tempfile.mkdtemp()
            pkg_dir = Path(tmp) / "package"
            pkg_dir.mkdir()
            for f in uploads:
                (pkg_dir / f.name).write_bytes(f.read())
            try:
                result = _run(str(pkg_dir))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            result = _run(pkg_path)

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

    if result.get("error"):
        st.error(f"Pipeline error: {result['error']}")

    # Review reasons
    reasons = result.get("review_reasons") or []
    if reasons:
        st.subheader("Review Reasons")
        for r in reasons:
            st.warning(r)

    # Validation failures
    failures = result.get("validation_failures") or []
    if failures:
        st.subheader(f"Validation Failures ({len(failures)})")
        for f in failures:
            st.error(f"**{f['field']}** [{f['rule']}] — {f['reason']}")

    # Extraction data
    extraction = result.get("extraction_data")
    if extraction:
        st.subheader("Extracted Fields")
        fields_meta = {m["name"]: m for m in (result.get("extraction_fields") or [])}
        rows = []
        for k, v in extraction.items():
            if isinstance(v, (list, dict)):
                continue
            meta = fields_meta.get(k, {})
            conf = meta.get("confidence")
            rows.append({"Field": k, "Value": str(v), "Confidence": f"{conf:.0%}" if conf is not None else "—"})

        if rows:
            st.dataframe(rows, use_container_width=True)

        # Complex fields
        for k, v in extraction.items():
            if isinstance(v, list) and v:
                st.markdown(f"**{k}**")
                st.json(v)

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
        st.json({k: v for k, v in result.items() if k not in ("extraction_fields",)})
