# Import all domain modules to trigger register() side effects
from claimflow.domains import health, loan, property  # noqa: F401
from claimflow.domains.base import Domain, all_domains, get, register

__all__ = ["Domain", "register", "get", "all_domains"]


def _wire_extract_hooks() -> None:
    # extract.py imports claimflow.domains at module scope, so it can't be imported
    # here (or from health/loan/property) without a circular import. Wire the hooks
    # after both sides have finished loading instead.
    from claimflow.nodes import extract as _extract_node

    cms1500 = get("cms1500")
    if cms1500 is not None:
        cms1500.extract_fn = _extract_node._cms1500_extract_fn
    xactimate = get("xactimate")
    if xactimate is not None:
        xactimate.extract_fn = _extract_node._extract_xactimate_pages
    eob = get("eob")
    if eob is not None:
        eob.extraction_hook = _extract_node._correct_eob_payer
    sba_form_413 = get("sba_form_413")
    if sba_form_413 is not None:
        sba_form_413.extraction_hook = _extract_node._correct_sba_form_413_widgets


_wire_extract_hooks()
