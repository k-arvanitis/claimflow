import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db
from claimflow.review import merge_reviewed_values


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/review.db")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_field(session, value=("DOE JOHN",)):
    session.add(db.Package(id="pkg1", status="review_ready"))
    session.add(
        db.Document(
            id="doc1",
            package_id="pkg1",
            path="a.pdf",
            doc_type="cms1500",
            has_text_layer=True,
        )
    )
    session.add(
        db.ExtractionRun(
            id="run1",
            document_id="doc1",
            schema_name="cms1500",
            status="review",
            overall_confidence=0.8,
        )
    )
    field = db.ExtractedField(
        extraction_run_id="run1",
        name="patient_name",
        value_json=json.dumps(value[0]),
        confidence=0.8,
        grounded=True,
        valid=True,
        field_status="review",
    )
    session.add(field)
    session.commit()
    return field


def test_review_action_never_overwrites_machine_value(session):
    field = _seed_field(session)
    original_value_json = field.value_json

    db.record_review_action(
        session,
        "run1",
        "patient_name",
        "edit",
        original_value="DOE JOHN",
        corrected_value="DOE JON",
        reviewer="alice",
    )

    refreshed = session.get(db.ExtractedField, field.id)
    assert refreshed.value_json == original_value_json


def test_repeated_identical_review_action_does_not_duplicate(session):
    _seed_field(session)

    first = db.record_review_action(
        session,
        "run1",
        "patient_name",
        "edit",
        original_value="DOE JOHN",
        corrected_value="DOE JON",
        reviewer="alice",
        note="typo fix",
    )
    second = db.record_review_action(
        session,
        "run1",
        "patient_name",
        "edit",
        original_value="DOE JOHN",
        corrected_value="DOE JON",
        reviewer="alice",
        note="typo fix",
    )

    assert first.id == second.id
    assert (
        session.query(db.ReviewAction)
        .filter_by(extraction_run_id="run1", field_name="patient_name")
        .count()
        == 1
    )


def test_distinct_review_action_creates_new_row(session):
    _seed_field(session)

    first = db.record_review_action(
        session,
        "run1",
        "patient_name",
        "edit",
        corrected_value="DOE JON",
        reviewer="alice",
    )
    second = db.record_review_action(
        session,
        "run1",
        "patient_name",
        "edit",
        corrected_value="DOE JONATHAN",
        reviewer="alice",
    )

    assert first.id != second.id
    assert (
        session.query(db.ReviewAction)
        .filter_by(extraction_run_id="run1", field_name="patient_name")
        .count()
        == 2
    )


def test_rerun_persists_new_failures_and_supersedes_old(session):
    _seed_field(session)
    session.add(
        db.ValidationFailure(
            extraction_run_id="run1",
            field="patient_dob",
            rule="mandatory",
            reason="missing",
        )
    )
    session.commit()

    db.supersede_validation_failures(session, "run1")
    db.create_validation_failures(
        session,
        "run1",
        [{"field": "patient_name", "rule": "mandatory", "reason": "still wrong"}],
    )

    all_failures = db.list_validation_failures_for_run(session, "run1")
    current = db.list_validation_failures_for_run(session, "run1", current_only=True)

    assert len(all_failures) == 2  # old one retained, not deleted
    assert len(current) == 1
    assert current[0].field == "patient_name"
    assert all(f.superseded for f in all_failures if f.field == "patient_dob")


def test_severity_and_policy_required_survive_db_round_trip(session):
    _seed_field(session)

    db.create_validation_failures(
        session,
        "run1",
        [
            {
                "field": "x",
                "rule": "arithmetic",
                "reason": "y",
                "severity": "warning",
                "policy_required": True,
            }
        ],
    )

    current = db.list_validation_failures_for_run(session, "run1", current_only=True)

    assert len(current) == 1
    assert current[0].severity == "warning"
    assert current[0].policy_required is True


def test_merge_reviewed_values_applies_scalar_and_nested_actions_once():
    machine = {
        "total_charge": 100.0,
        "service_lines": [{"code": "A"}, {"code": "B"}, {"code": "C"}],
    }
    actions = {
        "total_charge": {"action": "edit", "corrected_value": 95.5},
        "service_lines[0]": {"action": "reject", "corrected_value": None},
        "service_lines[1]": {"action": "edit", "corrected_value": {"code": "B2"}},
    }

    merged = merge_reviewed_values(
        machine,
        actions,
        {"service_lines[0]": None, "service_lines[1]": {"code": "B2"}},
    )

    assert merged == {
        "total_charge": 95.5,
        "service_lines": [{"code": "B2"}, {"code": "C"}],
    }
    assert machine["service_lines"][0] == {"code": "A"}
