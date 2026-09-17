"""shim：已迁移至 modules.submissions.application.submission_service。"""
from ..modules.submissions.application.submission_service import (
    submission_dict,
    validate_optional_http_url,
)

__all__ = ["submission_dict", "validate_optional_http_url"]
