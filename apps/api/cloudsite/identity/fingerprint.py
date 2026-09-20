"""Compatibility facade for the pre-2.0 identity fingerprint path.

New code must import from cloudsite.modules.identity.contracts.public.
"""

from ..modules.identity.domain.fingerprint import (
    _normalized_time,
    folder_identity_fingerprint,
    identity_fingerprint,
)

__all__ = [
    "folder_identity_fingerprint",
    "identity_fingerprint",
]
