"""Tests for the EOB/MSN, declarations page, SBA Form 413/2202 domains added on top of
the existing cms1500/xactimate/loan pipeline, plus the nested-list review export logic."""
from claimflow.domains.base import all_domains
from claimflow.domains.base import get as get_domain
from claimflow.nodes.ingest import _classify_doc_type
from claimflow.review import diff_list_field, rerun_validation

# ── Classification ────────────────────────────────────────────────────────────


def test_eob_classifies_by_keyword():
    assert _classify_doc_type("This is an Explanation of Benefits. This is not a bill.") == "eob"


def test_medicare_summary_notice_classifies_distinctly():
    assert _classify_doc_type("Your Medicare Summary Notice (MSN) for this quarter") == "medicare_summary_notice"


def test_declarations_page_classifies():
    assert _classify_doc_type("Homeowners Policy Declarations Page — Coverage A Dwelling") == "declarations_page"


def test_sba_form_413_classifies():
    assert _classify_doc_type("Personal Financial Statement — SBA Form 413") == "sba_form_413"


def test_sba_form_2202_classifies():
    assert _classify_doc_type("SBA Form 2202 Schedule of Liabilities") == "sba_form_2202"


def test_classification_only_docs_route_to_supporting_subtype():
    assert _classify_doc_type("Prior Authorization required before this procedure") == "prior_authorization_letter"
    assert _classify_doc_type("UB-04 CMS-1450 uniform billing form") == "ub04_cms1450"
    assert _classify_doc_type("Roof inspection report attached") == "roof_inspection_report"
    assert _classify_doc_type("Fire Department Report #12345") == "fire_report"
    assert _classify_doc_type("Articles of Incorporation filed with the state") == "articles_of_incorporation"
    assert _classify_doc_type("Form W-2 Wage and Tax Statement") == "w2_1099_paystub"


def test_all_new_domains_registered():
    doc_types = {d.doc_type for d in all_domains()}
    assert {"eob", "medicare_summary_notice", "declarations_page", "sba_form_413", "sba_form_2202"} <= doc_types


# ── Schema instantiation ──────────────────────────────────────────────────────


def test_eob_schema_instantiation():
    from claimflow.domains.health import EOB
    eob = EOB(patient_name="DOE JOHN", is_bill=False, provider_charges=200.0, allowed_charges=150.0)
    assert eob.patient_name == "DOE JOHN"
    assert eob.is_bill is False


def test_declarations_page_schema_instantiation():
    from claimflow.domains.property import DeclarationsPage
    page = DeclarationsPage(insured_name="JOHN SMITH", coverage_a_dwelling=250000.0)
    assert page.insured_name == "JOHN SMITH"
    assert page.coverage_a_dwelling == 250000.0


def test_form_413_schema_instantiation():
    from claimflow.domains.loan import SBAForm413
    pfs = SBAForm413(applicant_name="JOHN SMITH", total_assets=100.0, total_liabilities=40.0, net_worth=60.0)
    assert pfs.net_worth == 60.0


def test_form_2202_schema_instantiation():
    from claimflow.domains.loan import Liability, SBAForm2202
    sched = SBAForm2202(liabilities=[Liability(creditor_name="Bank X", current_balance=500.0)])
    assert sched.liabilities[0].creditor_name == "Bank X"


# ── Validators ────────────────────────────────────────────────────────────────


def test_eob_flags_is_bill_true():
    domain = get_domain("eob")
    failures = domain.validate({"patient_name": "DOE JOHN", "is_bill": True})
    assert any(f["rule"] == "not_a_bill" for f in failures)


def test_eob_flags_provider_charges_below_allowed():
    domain = get_domain("eob")
    failures = domain.validate({
        "patient_name": "DOE JOHN", "is_bill": False,
        "provider_charges": 50.0, "allowed_charges": 100.0,
    })
    assert any(f["field"] == "provider_charges" for f in failures)


def test_eob_clean_record_no_failures():
    domain = get_domain("eob")
    failures = domain.validate({
        "patient_name": "DOE JOHN", "is_bill": False,
        "provider_charges": 200.0, "allowed_charges": 150.0,
        "plan_paid": 100.0, "patient_responsibility": 50.0,
    })
    assert failures == []


def test_declarations_page_flags_reversed_policy_period():
    domain = get_domain("declarations_page")
    failures = domain.validate({
        "insured_name": "JOHN SMITH",
        "policy_period_start": "01012027", "policy_period_end": "01012026",
    })
    assert any(f["rule"] == "date_window" for f in failures)


def test_declarations_page_flags_date_of_loss_outside_period():
    domain = get_domain("declarations_page")
    failures = domain.validate({
        "insured_name": "JOHN SMITH",
        "policy_period_start": "01012026", "policy_period_end": "12312026",
        "date_of_loss": "01012028",
    })
    assert any(f["field"] == "date_of_loss" for f in failures)


def test_declarations_page_flags_address_mismatch():
    domain = get_domain("declarations_page")
    failures = domain.validate({
        "insured_name": "JOHN SMITH",
        "policy_period_start": "01012026", "policy_period_end": "12312026",
        "insured_address": "100 Main St, Springfield",
        "property_address": "999 Totally Different Ave, Shelbyville",
    })
    assert any(f["rule"] == "address_consistency" for f in failures)


def test_form_413_flags_net_worth_arithmetic_mismatch():
    domain = get_domain("sba_form_413")
    failures = domain.validate({"total_assets": 100.0, "total_liabilities": 40.0, "net_worth": 999.0})
    assert any(f["rule"] == "arithmetic" for f in failures)


def test_form_413_clean_net_worth_no_failures():
    domain = get_domain("sba_form_413")
    failures = domain.validate({"total_assets": 100.0, "total_liabilities": 40.0, "net_worth": 60.0})
    assert failures == []


def test_form_2202_flags_liability_sum_mismatch():
    domain = get_domain("sba_form_2202")
    failures = domain.validate({
        "liabilities": [{"creditor_name": "Bank X", "current_balance": 500.0}],
        "total_current_balance": 9999.0,
    })
    assert any(f["rule"] == "arithmetic" for f in failures)


def test_form_2202_flags_balance_exceeding_original():
    domain = get_domain("sba_form_2202")
    failures = domain.validate({
        "liabilities": [{
            "creditor_name": "Bank X", "original_amount": 100.0,
            "current_balance": 500.0, "current_or_delinquent": "current",
        }],
    })
    assert any(f["rule"] == "amount_consistency" for f in failures)


# ── Nested/list review export ─────────────────────────────────────────────────


def test_diff_list_field_scalar_list_approve_and_edit():
    original = ["A", "B"]
    edited = ["A", "B2"]
    result = diff_list_field(
        "diagnosis_codes", original, edited,
        {"diagnosis_codes": {"confidence": 0.9, "evidence": None}},
    )
    assert result["type"] == "list"
    assert result["rows"][0]["action"] == "approve"
    assert result["rows"][1]["action"] == "edit"
    assert result["rows"][1]["final_value"] == "B2"


def test_diff_list_field_scalar_list_reject_and_add():
    # A same-length edit ("B" -> "C") counts as "edit"; reject/add need a length change.
    shrink = diff_list_field("diagnosis_codes", ["A", "B"], ["A"], {})
    assert shrink["rows"][1]["action"] == "reject"
    assert shrink["rows"][1]["final_value"] is None

    grow = diff_list_field("diagnosis_codes", ["A"], ["A", "B"], {})
    assert grow["rows"][1]["action"] == "add"


def test_diff_list_field_table_rows():
    original = [{"cpt_code": "99213", "charges": 150.0}]
    edited = [{"cpt_code": "99214", "charges": 150.0}]
    result = diff_list_field(
        "service_lines", original, edited,
        {"service_lines": {"confidence": 0.8}},
    )
    assert result["type"] == "table"
    assert result["rows"][0]["row_id"] == "service_lines_1"
    assert result["rows"][0]["action"] == "edit"


def test_diff_list_field_table_rows_use_per_row_confidence():
    original = [{"cpt_code": "99213"}, {"cpt_code": "99214"}]
    edited = [{"cpt_code": "99213"}, {"cpt_code": "99214"}]
    fields_meta = {
        "service_lines": {"confidence": 0.5},
        "service_lines[0]": {"confidence": 0.95},
        # no per-row entry for index 1 -> falls back to parent's aggregate confidence
    }
    result = diff_list_field("service_lines", original, edited, fields_meta)
    assert result["rows"][0]["confidence"] == 0.95
    assert result["rows"][1]["confidence"] == 0.5


def test_rerun_validation_uses_real_domain_validator():
    failures = rerun_validation("sba_form_413", {"total_assets": 100.0, "total_liabilities": 40.0, "net_worth": 999.0})
    assert any(f["rule"] == "arithmetic" for f in failures)


def test_rerun_validation_unknown_domain_returns_empty():
    assert rerun_validation("not_a_real_domain", {}) == []
