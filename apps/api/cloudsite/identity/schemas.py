"""Compatibility facade for the pre-2.0 identity DTO path.

New code must import from cloudsite.modules.identity.contracts.public.
"""

from ..modules.identity.contracts.public import (
    FolderIdentityObservation,
    FolderIdentityResolution,
    IdentityObservation,
    IdentityResolution,
)

__all__ = [
    "FolderIdentityObservation",
    "FolderIdentityResolution",
    "IdentityObservation",
    "IdentityResolution",
]
