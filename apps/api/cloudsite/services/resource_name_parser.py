"""Compatibility facade for the Automation-owned deterministic resource parser.

New code imports the parser from ``cloudsite.modules.automation.domain``.
This module preserves the historical ``cloudsite.services.resource_name_parser``
surface while migration callers move to the Automation boundary.
"""

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
