# Import all domain modules to trigger register() side effects
from claimflow.domains import health, loan, property  # noqa: F401
from claimflow.domains.base import Domain, all_domains, get, register

__all__ = ["Domain", "register", "get", "all_domains"]
