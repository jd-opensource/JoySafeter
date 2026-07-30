from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.joysafeter_api.api.v1.middleware import ApiV1ResponseWrapperMiddleware


def test_api_v2_paginated_responses_are_wrapped_like_v1() -> None:
    app = FastAPI()
    app.add_middleware(ApiV1ResponseWrapperMiddleware)

    @app.get("/api/v2/secrets")
    async def list_secrets():
        return {
            "data": [{"id": "secret_1", "name": "local"}],
            "has_more": False,
            "first_id": "1",
            "last_id": "1",
        }

    response = TestClient(app).get("/api/v2/secrets")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": 200,
        "message": "OK",
        "data": [{"id": "secret_1", "name": "local"}],
        "has_more": False,
        "first_id": "1",
        "last_id": "1",
    }
