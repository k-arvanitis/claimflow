from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claimflow import db


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    db.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_all_tables_created():
    session = _make_session()
    inspector_tables = db.Base.metadata.tables.keys()
    expected = {
        "packages", "audit_log", "documents", "extraction_runs",
        "extracted_fields", "validation_failures", "policy_evidence",
        "decisions", "review_actions",
    }
    assert expected.issubset(inspector_tables)
    session.close()
