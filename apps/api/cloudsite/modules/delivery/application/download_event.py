import time

from ..infrastructure.models import DownloadEvent


async def _download_event(session, resource_id, result, code, started, source: str = "public"):
    session.add(DownloadEvent(resource_id=resource_id, result=result, error_code=code, duration_ms=int((time.perf_counter() - started) * 1000), source=source))
    await session.commit()


__all__ = ["_download_event"]