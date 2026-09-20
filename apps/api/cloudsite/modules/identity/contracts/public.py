"""Public contract for the Identity business module.

Only stable, persistence-free identity types and fingerprint rules are exposed
in M4a. Persistence-backed resolution/migration services remain behind the
legacy compatibility facade until repository ports are introduced in M4b.
"""

from ..application.root_cleanup import cascade_delete_root_identities
from ..domain.fingerprint import folder_identity_fingerprint, identity_fingerprint
from ..domain.models import (
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
    "cascade_delete_root_identities",
    "folder_identity_fingerprint",
    "identity_fingerprint",
]
