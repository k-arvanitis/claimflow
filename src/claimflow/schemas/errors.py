from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel


class AppError(HTTPException):
    """Raise this instead of bare HTTPException when a route needs a stable
    machine-readable `code` (e.g. "PACKAGE_NOT_FOUND") in the error envelope."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.details = details


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody
