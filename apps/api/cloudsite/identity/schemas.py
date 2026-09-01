from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class IdentityObservation:
    path: str
    name: str
    root_mapping_id: int | None
    size: int
    modified_at: datetime | None
    extension: str
    mime_type: str
    provider_object_id: str | None = None
    content_hash: str | None = None


@dataclass(slots=True)
class IdentityResolution:
    observation: IdentityObservation
    resource_id: str
    match_type: str
    fingerprint: str
    previous_path: str | None = None
    ambiguous_resource_ids: list[str] = field(default_factory=list)
