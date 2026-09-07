import hashlib
from datetime import datetime, timezone
from typing import Any


def _normalized_time(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def identity_fingerprint(
    *,
    size: int,
    modified_at: datetime | None,
    extension: str,
    mime_type: str,
) -> str:
    """Build the conservative v1 identity hint without path or filename."""
    payload = "|".join(
        (
            "v1",
            str(max(0, int(size))),
            _normalized_time(modified_at),
            str(extension or "").lower().lstrip("."),
            str(mime_type or "application/octet-stream").lower(),
        )
    )
    return hashlib.blake2s(payload.encode("utf-8")).hexdigest()


def folder_identity_fingerprint(entries: list[dict[str, Any]]) -> str:
    """Folder identity fingerprint based on child names, types, and count."""
    canonical = []
    for item in entries:
        name = str(item.get("name") or "")
        is_dir = bool(item.get("is_dir"))
        canonical.append(f"v1|{name}|{'dir' if is_dir else 'file'}")
    payload = "\n".join(sorted(canonical)).encode("utf-8")
    return hashlib.blake2s(payload).hexdigest()
