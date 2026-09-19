"""Compatibility facade for Automation-owned resource-name parser."""

from ..modules.automation.domain.resource_name_parser import (
    PARSER_VERSION,
    UNKNOWN,
    Evidence,
    ParseResult,
    parse_resource_name,
)

__all__ = [
    "PARSER_VERSION",
    "UNKNOWN",
    "Evidence",
    "ParseResult",
    "parse_resource_name",
]
