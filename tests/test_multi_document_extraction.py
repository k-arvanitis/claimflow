"""
Multi-document extraction: a package's non-primary documents (e.g. an EOB
alongside the primary CMS-1500) get their own extraction and validation when
they have a registered domain pack, instead of only being classified.
"""

from unittest.mock import MagicMock, patch

from doc_intel.schemas.base import ExtractionResult

from claimflow.nodes.extract import _extract_secondary_documents
from claimflow.nodes.validate import _validate_secondary_extractions
from claimflow.state import ClaimState


def _fake_result(data: dict, status: str = "pass") -> ExtractionResult:
    return ExtractionResult(
        schema_name="eob",
        data=data,
        fields=[],
        overall_confidence=0.9,
        status=status,
        flagged_fields=[],
        source_meta={},
    )


def _state_with_documents(documents: list[dict]) -> ClaimState:
    return {  # type: ignore[typeddict-item]
        "package_dir": "/tmp",
        "domain": "cms1500",
        "documents": documents,
    }


def test_secondary_document_with_registered_domain_gets_extracted():
    fake_domain = MagicMock()
    fake_domain.doc_type = "eob"
    fake_domain.extract_fn = MagicMock(
        return_value=_fake_result({"patient_name": "DOE JOHN"})
    )
    fake_domain.extraction_hook = None

    state = _state_with_documents(
        [
            {"path": "/tmp/claim.pdf", "doc_type": "cms1500"},
            {"path": "/tmp/eob.pdf", "doc_type": "eob"},
        ]
    )

    with patch("claimflow.nodes.extract.get_domain", return_value=fake_domain):
        results = _extract_secondary_documents(state, primary_domain_key="cms1500")

    assert len(results) == 1
    assert results[0]["doc_type"] == "eob"
    assert results[0]["status"] == "pass"
    assert results[0]["data"] == {"patient_name": "DOE JOHN"}
    fake_domain.extract_fn.assert_called_once()


def test_secondary_document_without_registered_domain_is_skipped():
    state = _state_with_documents(
        [
            {"path": "/tmp/claim.pdf", "doc_type": "cms1500"},
            {"path": "/tmp/note.pdf", "doc_type": "clinical_note"},
        ]
    )

    with patch("claimflow.nodes.extract.get_domain", return_value=None):
        results = _extract_secondary_documents(state, primary_domain_key="cms1500")

    assert results == []


def test_secondary_extraction_failure_is_isolated_per_document():
    fake_domain = MagicMock()
    fake_domain.doc_type = "eob"
    fake_domain.extract_fn = MagicMock(side_effect=RuntimeError("OCR backend down"))
    fake_domain.extraction_hook = None

    state = _state_with_documents(
        [
            {"path": "/tmp/claim.pdf", "doc_type": "cms1500"},
            {"path": "/tmp/eob.pdf", "doc_type": "eob"},
        ]
    )

    with patch("claimflow.nodes.extract.get_domain", return_value=fake_domain):
        results = _extract_secondary_documents(state, primary_domain_key="cms1500")

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert "OCR backend down" in results[0]["error"]


def test_secondary_validation_failures_are_tagged_with_doc_type():
    fake_domain = MagicMock()
    fake_domain.validate = MagicMock(
        return_value=[
            {
                "field": "patient_name",
                "rule": "mandatory",
                "reason": "patient_name is required but missing or empty",
                "severity": "error",
                "policy_required": False,
            }
        ]
    )

    state: ClaimState = {  # type: ignore[typeddict-item]
        "secondary_extractions": [
            {
                "doc_type": "eob",
                "filename": "eob.pdf",
                "data": {"patient_name": None},
                "status": "pass",
            }
        ]
    }

    with patch("claimflow.nodes.validate.get_domain", return_value=fake_domain):
        failures = _validate_secondary_extractions(state)

    assert len(failures) == 1
    assert failures[0]["field"] == "eob: patient_name"


def test_failed_secondary_extraction_is_not_validated():
    state: ClaimState = {  # type: ignore[typeddict-item]
        "secondary_extractions": [
            {"doc_type": "eob", "filename": "eob.pdf", "data": None, "status": "error"}
        ]
    }

    with patch("claimflow.nodes.validate.get_domain") as get_domain:
        failures = _validate_secondary_extractions(state)

    get_domain.assert_not_called()
    assert failures == []
