"""Typed Resources query failures without HTTP concerns."""


class ResourceNotFoundError(LookupError):
    """Resource is absent or not active."""


class ResourceNotAvailableError(LookupError):
    """Resource exists but is outside the injected publication scope."""


class FolderNotFoundError(LookupError):
    """Folder is absent, inactive, or outside the injected publication scope."""


__all__ = [
    "FolderNotFoundError",
    "ResourceNotAvailableError",
    "ResourceNotFoundError",
]
