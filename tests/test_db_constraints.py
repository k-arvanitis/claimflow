import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from claimflow import db


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/constraints.db")
    db.Base.metadata.create_all(eng)
    return eng


def test_foreign_keys_are_enforced(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        db.Document(
            id="doc1",
            package_id="does-not-exist",
            path="a.pdf",
            doc_type="cms1500",
            has_text_layer=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_package_cascades_to_children_but_not_audit(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(db.Package(id="pkg1", status="completed"))
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
            status="pass",
            overall_confidence=0.9,
        )
    )
    session.add(
        db.ExtractedField(
            extraction_run_id="run1",
            name="f",
            confidence=0.9,
            grounded=True,
            valid=True,
            field_status="found",
        )
    )
    session.add(db.AuditLogEntry(package_id="pkg1", actor="api", action="upload"))
    session.commit()

    pkg = session.get(db.Package, "pkg1")
    session.delete(pkg)
    session.commit()

    assert session.get(db.Document, "doc1") is None
    assert session.get(db.ExtractionRun, "run1") is None
    assert session.query(db.ExtractedField).count() == 0
    assert session.query(db.AuditLogEntry).filter_by(package_id="pkg1").count() == 1


def test_duplicate_document_path_in_same_package_rejected(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(db.Package(id="pkg1", status="completed"))
    session.commit()
    session.add(
        db.Document(
            id="doc1",
            package_id="pkg1",
            path="a.pdf",
            doc_type="cms1500",
            has_text_layer=True,
        )
    )
    session.commit()
    session.add(
        db.Document(
            id="doc2",
            package_id="pkg1",
            path="a.pdf",
            doc_type="cms1500",
            has_text_layer=True,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
