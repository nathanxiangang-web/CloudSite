from __future__ import annotations

import dataclasses
import json
from enum import Enum


CAPABILITY_SCHEMA_VERSION = 1


class CapabilityState(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    capability_schema_version: int = CAPABILITY_SCHEMA_VERSION
    supports_list: CapabilityState = CapabilityState.YES
    supports_range: CapabilityState = CapabilityState.UNKNOWN
    supports_direct_download: CapabilityState = CapabilityState.YES
    supports_direct_preview: CapabilityState = CapabilityState.YES
    supports_native_thumbnail: CapabilityState = CapabilityState.UNKNOWN
    supports_stable_object_id: CapabilityState = CapabilityState.NO
    supports_content_hash: CapabilityState = CapabilityState.UNKNOWN
    supports_delta: CapabilityState = CapabilityState.NO
    supports_change_cursor: CapabilityState = CapabilityState.NO
    supports_webhook: CapabilityState = CapabilityState.NO
    supports_change_journal: CapabilityState = CapabilityState.NO

    def to_json(self) -> str:
        payload = {
            field.name: (
                value.value if isinstance(value, CapabilityState) else value
            )
            for field in dataclasses.fields(self)
            for value in (getattr(self, field.name),)
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> "ProviderCapabilities":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        defaults = {field.name: field.default for field in dataclasses.fields(cls)}
        kwargs: dict[str, object] = {}
        for key, value in data.items():
            if key not in defaults:
                continue
            if isinstance(defaults[key], CapabilityState):
                try:
                    kwargs[key] = CapabilityState(value)
                except ValueError:
                    kwargs[key] = CapabilityState.UNKNOWN
            else:
                kwargs[key] = value
        return cls(**kwargs)  # type: ignore[arg-type]

    def summary(self) -> dict[str, str]:
        return {
            field.name: (
                value.value if isinstance(value, CapabilityState) else str(value)
            )
            for field in dataclasses.fields(self)
            for value in (getattr(self, field.name),)
        }


__all__ = [
    "CAPABILITY_SCHEMA_VERSION",
    "CapabilityState",
    "ProviderCapabilities",
]