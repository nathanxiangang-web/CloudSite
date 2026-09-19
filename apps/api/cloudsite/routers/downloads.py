"""downloads 路由：302 下载跳转。"""

import time
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..download import DownloadError, resolve_download_entry, validate_resource_id
from ..download_rate_limit import (
    check_download_rate,
    get_effective_client_ip,
    rate_limit_payload,
)
from ..modules.providers.contracts.public import provider_runtime
from ..modules.resources.api.queries import resource_queries
from ..modules.resources.domain.errors import (
    ResourceInactiveError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
from ..modules.delivery.contracts.public import _download_event
from ..shares.service import enabled_root_ids

router = APIRouter()


def _download_error_redirect(code: str, resource_id: str) -> RedirectResponse:
    return RedirectResponse(
        f"/download-error?{urlencode({'code': code, 'resource': resource_id})}",
        status_code=302,
    )


@router.get("/d/{resource_id}")
async def download(resource_id: str, request: Request):
    from ..main import IndexSession, StateSession

    started = time.perf_counter()
    wants_json = "application/json" in request.headers.get("accept", "").lower()
    async with IndexSession() as index, StateSession() as state:
        if not validate_resource_id(resource_id):
            await _download_event(
                state,
                resource_id[:64],
                "failed",
                "DL-001",
                started,
            )
            return _download_error_redirect("DL-001", resource_id[:64])

        enabled_ids = await enabled_root_ids(state)
        try:
            resource = await resource_queries(index).download_resource(
                resource_id=resource_id,
                enabled_root_ids=enabled_ids,
            )
        except ResourceNotFoundError:
            await _download_event(
                state,
                resource_id,
                "failed",
                "DL-001",
                started,
            )
            return _download_error_redirect("DL-001", resource_id)
        except ResourceInactiveError:
            await _download_event(
                state,
                resource_id,
                "failed",
                "DL-007",
                started,
            )
            return _download_error_redirect("DL-007", resource_id)
        except ResourceNotAvailableError:
            await _download_event(
                state,
                resource_id,
                "failed",
                "RESOURCE_NOT_AVAILABLE",
                started,
            )
            return _download_error_redirect(
                "RESOURCE_NOT_AVAILABLE",
                resource_id,
            )

        rate = await check_download_rate(get_effective_client_ip(request))
        if not rate.allowed:
            await _download_event(
                state,
                resource_id,
                "failed",
                "DOWNLOAD_RATE_LIMITED",
                started,
            )
            return JSONResponse(
                rate_limit_payload(rate),
                status_code=429,
                headers={"Retry-After": str(rate.retry_after)},
            )

        runtime = provider_runtime(state)
        try:
            resolution = await resolve_download_entry(resource, runtime)
            await _download_event(state, resource_id, "success", None, started)
            from ..services.metrics import (
                EVENT_DOWNLOAD_REDIRECT,
                try_record_committed,
            )

            await try_record_committed(
                state,
                EVENT_DOWNLOAD_REDIRECT,
                {
                    "resource_id": resource_id,
                    "elapsed_ms": round(
                        (time.perf_counter() - started) * 1000
                    ),
                },
            )
            if wants_json:
                return {"url": resolution.url}
            return RedirectResponse(resolution.url, status_code=302)
        except DownloadError as exc:
            await _download_event(
                state,
                resource_id,
                "failed",
                exc.code,
                started,
            )
            return _download_error_redirect(exc.code, resource_id)
