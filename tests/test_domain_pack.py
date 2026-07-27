from claimflow.domains.base import Domain, all_domains, get, register


def test_domain_pack_fields_have_safe_defaults():
    register(
        Domain(
            doc_type="_test_pack",
            keywords={"testword"},
            spec=None,
            validate=lambda data: [],
        )
    )
    pack = get("_test_pack")
    assert pack.display_name == ""
    assert pack.retrieval_mode == "llm_synthesis"
    assert pack.question_templates == {}
    assert pack.extraction_hook is None
    assert pack.extract_fn is None
    assert pack.confidence_threshold is None
    assert pack.escalation_threshold is None
    assert pack.reviewer_guidance == ""


def test_all_domains_includes_every_registered_pack():
    names = {d.doc_type for d in all_domains()}
    assert {"cms1500", "xactimate", "loan", "eob", "sba_form_413"} <= names


def test_cms1500_pack_is_the_official_source_domain():
    pack = get("cms1500")
    assert pack.display_name == "CMS-1500 Health Claim"
    assert pack.policy_collection == "health"
    assert pack.retrieval_mode == "official_deterministic"


def test_xactimate_and_loan_use_llm_synthesis():
    assert get("xactimate").retrieval_mode == "llm_synthesis"
    assert get("xactimate").policy_collection == "property"
    assert get("loan").retrieval_mode == "llm_synthesis"
    assert get("loan").policy_collection == "loan"


def test_cms1500_question_templates_cover_known_validation_rules():
    templates = get("cms1500").question_templates
    assert templates["icd10_lookup"].format(reason="x") == (
        "What CMS-1500 policy applies when Item 21 contains an unrecognized ICD-10-CM diagnosis code? x"
    )
    assert set(templates.keys()) == {"icd10_lookup", "cpt_lookup", "arithmetic"}
