import httpx

from cloudsite.main import app


async def test_http_errors_always_use_structured_detail():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/not-a-route")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "HTTP_404"
    assert isinstance(response.json()["detail"]["message"], str)


async def test_validation_errors_use_stable_code_without_internal_details():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/auth/login", json={})
    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "VALIDATION_ERROR", "message": "请求参数格式不正确"}
    }
