import json

from starlette.requests import Request

from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.exceptions import app_error_handler


async def handled_app_error_payload(
    exc: AppError,
    *,
    status_code: int,
    path: str = "/api/v1/test",
) -> dict:
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    response = await app_error_handler(request, exc)
    assert response.status_code == status_code
    return json.loads(response.body)
