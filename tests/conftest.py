import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Rebind claimflow.db's engine/SessionLocal to a fresh per-test SQLite file.

    Without this, tests that go through the real API (TestClient -> lifespan ->
    init_db()) share settings.db_path's real file across the whole test run —
    row counts bleed between tests and mutate the developer's actual dev DB.
    Found and worked around 3 times (case-by-case package_id/run_id scoping)
    before landing this fixture as the actual root-cause fix."""
    from claimflow import db

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine))
    db.Base.metadata.create_all(engine)


@pytest.fixture
def session_factory():
    """Returns the isolated per-test db.SessionLocal callable (see isolated_db above)."""
    from claimflow import db

    return db.SessionLocal


@pytest.fixture
def base_state():
    return {
        "package_dir": "/tmp",
        "domain": "cms1500",
        "documents": [],
        "extraction_data": None,
        "extraction_fields": None,
        "extraction_status": None,
        "extraction_overall_confidence": None,
        "validation_failures": [],
        "policy_answers": [],
        "decision": None,
        "review_reasons": [],
        "error": None,
    }


@pytest.fixture
def clean_claim():
    return {
        "insurance_id": "INS123",
        "patient_name": "DOE JOHN",
        "patient_dob": "01011980",
        "patient_sex": "M",
        "insured_name": "DOE JOHN",
        "billing_provider_npi": "1487293650",
        "billing_provider_name": "SMITH MD JANE",
        "billing_provider_address": "123 MAIN ST CITY ST 12345",
        "federal_tax_id": "123456789",
        "diagnosis_codes": ["J06.9"],
        "service_lines": [
            {
                "cpt_code": "99213",
                "date_of_service": "01012026",
                "charges": "150.00",
                "units": 1,
                "place_of_service": "11",
                "diagnosis_pointer": "A",
            }
        ],
        "total_charge": "150.00",
        "amount_paid": "0.00",
        "accept_assignment": True,
        "signature_on_file": True,
    }
