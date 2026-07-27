# Re-export from canonical location for backward compatibility
from claimflow.domains.health import _SPEC, CMS1500, ServiceLine

CMS1500_SPEC = _SPEC

__all__ = ["CMS1500", "CMS1500_SPEC", "ServiceLine"]
