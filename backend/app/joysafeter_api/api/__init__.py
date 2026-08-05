"""
API route aggregation.

All live endpoints are served under ``/api/v1`` and live in
``./v1/``. The codebase previously split a legacy v1 surface and a
managed v2 surface; the v1 cleanup waves retired the legacy surface
and the managed surface was then remounted as /api/v1 (and its
package directory renamed from ``v2`` to ``v1``). The FastAPI app
wires up the surviving router via
``app.joysafeter_api.api.v1.router.joysafeter_router``.
"""
