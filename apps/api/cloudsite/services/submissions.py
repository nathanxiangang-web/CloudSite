"""Backward-compatible Submissions helper shim."""

from fastapi import HTTPException

from ..modules.submissions.application.submission_service import (
    SubmissionValidationError,
    submission_dict,
    validate_optional_http_url as _validate_optional_http_url,
)


def validate_optional_http_url(value: str, field_name: str) -> str:
    try:
        return _validate_optional_http_url(value, field_name)
    except SubmissionValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


__all__ = ["submission_dict", "validate_optional_http_url"]
