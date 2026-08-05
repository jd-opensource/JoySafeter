import httpx
import pytest

from app.joysafeter_shared.llm.openai_stream import _status_error_event, _transport_error_event

pytestmark = pytest.mark.no_db


def test_openai_stream_status_error_event_is_structured():
    assert _status_error_event(503, "upstream overloaded") == {
        "type": "error",
        "code": "UPSTREAM_UNAVAILABLE",
        "message": "upstream overloaded",
        "data": None,
        "source": "upstream",
        "retryable": True,
        "status": 503,
    }


def test_openai_stream_transport_error_event_is_structured():
    assert _transport_error_event(httpx.ReadTimeout("timed out")) == {
        "type": "error",
        "code": "UPSTREAM_CONNECTION_FAILED",
        "message": "transport error: timed out",
        "data": None,
        "source": "upstream",
        "retryable": True,
        "status": None,
    }


def test_async_error_payload_uses_catalog_semantic_class():
    from app.joysafeter_shared.common.stream_errors import async_error_payload

    payload = async_error_payload(code="SESSION_NOT_FOUND", message="x")
    assert payload["type"] == "error"
    assert payload["code"] == "SESSION_NOT_FOUND"
    # SESSION_NOT_FOUND is a NotFoundError (DomainError) in the catalog, so its source
    # is "api" -- not the bare-AppError default "internal" the old path produced.
    assert payload["source"] == "api"


def test_async_error_payload_falls_back_for_unregistered_code():
    from app.joysafeter_shared.common.stream_errors import async_error_payload

    payload = async_error_payload(code="__NOT_IN_CATALOG__", message="x", source="runtime")
    assert payload["code"] == "__NOT_IN_CATALOG__"
    assert payload["source"] == "runtime"
