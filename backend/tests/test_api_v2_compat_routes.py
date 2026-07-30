from fastapi import FastAPI

from app.joysafeter_api.app import register_api_routes


def test_legacy_api_v2_auth_routes_are_mounted() -> None:
    app = FastAPI()

    register_api_routes(app)

    paths = set(app.openapi()["paths"])
    assert "/api/v2/auth/me" in paths
    assert "/api/v2/auth/oauth/providers" in paths
