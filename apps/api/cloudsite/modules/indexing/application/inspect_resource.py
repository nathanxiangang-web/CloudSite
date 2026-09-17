from __future__ import annotations

from ..domain.inspection import InspectionRequest, InspectionResult
from ..infrastructure.provider_adapter import ProviderAdapter


class InspectResourceService:
    """Inspect a single resource via a capability-driven provider adapter.

    The adapter advertises supports_inspect; if the provider cannot inspect
    resources the service raises NotImplementedError rather than silently
    returning stale or empty data.
    """

    def __init__(self, adapter: ProviderAdapter) -> None:
        self._adapter = adapter

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        caps = self._adapter.capabilities
        if not caps.supports_inspect:
            raise NotImplementedError(
                f'Provider {self._adapter.provider_id} does not support inspect'
            )
        if request.provider_id != self._adapter.provider_id:
            return InspectionResult(
                resource_id=request.resource_id,
                provider_id=request.provider_id,
                path='',
                name='',
                success=False,
                error_code='provider_mismatch',
                error_message=(
                    f'Request provider {request.provider_id} does not match '
                    f'adapter {self._adapter.provider_id}'
                ),
            )
        return await self._adapter.inspect(request)


__all__ = ['InspectResourceService']