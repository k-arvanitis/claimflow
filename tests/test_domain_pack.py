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
