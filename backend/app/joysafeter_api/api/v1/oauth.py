"""Compatibility OAuth routes.

The canonical JoySafeter OAuth implementation lives in API v2 under
``/api/v2/auth/oauth``.  This router keeps the old ``/api/v1/auth/oauth``
paths available for existing clients and provider callback URLs.
"""

from fastapi import APIRouter

from app.joysafeter_api.api.v2.oauth import router as v2_oauth_router

router = APIRouter(tags=["OAuth"])
router.include_router(v2_oauth_router, prefix="/v1/auth/oauth")
