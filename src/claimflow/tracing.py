"""Optional Langfuse tracing for LangGraph runs.

Usage:
    from claimflow.tracing import get_callback
    result = app.invoke(state, config={"callbacks": get_callback()})
"""
from __future__ import annotations

from claimflow.config import settings


def get_callback() -> list:
    """Return a list containing the Langfuse callback handler, or empty if disabled."""
    if not settings.langfuse_enabled:
        return []
    try:
        from langfuse.callback import CallbackHandler
        return [CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )]
    except Exception:
        return []
