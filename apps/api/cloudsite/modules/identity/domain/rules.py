"""Pure path and event rules for stable identity."""

from pathlib import PurePosixPath


def normalize_identity_path(value: str) -> str:
    parts = [part for part in str(value or "").replace("\\", "/").split("/") if part]
    return "/" + "/".join(parts) if parts else "/"


def classify_identity_event(
    previous_path: str | None,
    current_path: str,
    previous_status: str,
) -> str:
    if previous_path is None:
        return "created"
    if previous_path == current_path:
        return "reactivated" if previous_status != "active" else "observed"
    if PurePosixPath(previous_path).parent == PurePosixPath(current_path).parent:
        return "rename"
    return "move"


__all__ = ["classify_identity_event", "normalize_identity_path"]
