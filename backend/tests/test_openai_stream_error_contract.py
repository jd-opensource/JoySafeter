import httpx

from app.joysafeter_shared.llm.openai_stream import _status_error_event, _transport_error_event


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
