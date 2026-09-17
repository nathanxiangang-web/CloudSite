"""cloud-download routes: user cloud download task submit and list.

POST creates a CloudDownloadTask for the signed-in user; GET returns
only that user's recent tasks. Both require a valid user session; POST
also validates the request origin. The service helpers are reusable for
a future AI submission path under an explicit user identity.
"""
from fastapi import APIRouter, Request

from cloudsite.auth import require_user, validate_request_origin
from cloudsite.schemas import CloudDownloadTaskInput
from cloudsite.plugins.ai.services.cloud_download import list_user_cloud_download_tasks, submit_cloud_download

router = APIRouter()


@router.post("/api/cloud-download/tasks")
async def create_cloud_download_task(payload: CloudDownloadTaskInput, request: Request):
    from cloudsite.main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await submit_cloud_download(state, user.id, payload.url)
        await state.commit()
        return result


@router.get("/api/cloud-download/tasks")
async def list_cloud_download_tasks(request: Request):
    from cloudsite.main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await list_user_cloud_download_tasks(state, user.id)
        return result
