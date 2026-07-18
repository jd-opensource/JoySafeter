"""Session user.message content must be length-bounded like the task prompt.

`_validate_message_content` concatenates a user.message (plain string or text
blocks) into the text that becomes an agent task prompt via the internal service
path — which bypasses the JoySafeterCreateTaskRequest schema cap. Without its own
bound, an oversized session message still bloats a DB row and the Redis SSE
fan-out. It must be capped at the same MAX_PROMPT_CHARS and rejected with a
structured 422.
"""

import pytest

from app.joysafeter_api.api.v1.sessions import _validate_message_content
from app.joysafeter_domain.schemas.joysafeter_task import MAX_PROMPT_CHARS
from app.joysafeter_shared.common.app_errors import AppError

pytestmark = pytest.mark.no_db


def test_string_content_at_cap_is_accepted():
    text = "x" * MAX_PROMPT_CHARS
    assert _validate_message_content(text) == text


def test_string_content_over_cap_is_rejected():
    with pytest.raises(AppError) as exc_info:
        _validate_message_content("x" * (MAX_PROMPT_CHARS + 1))
    assert exc_info.value.code == "SESSION_CONTENT_TOO_LARGE"


def test_block_list_total_over_cap_is_rejected():
    half = MAX_PROMPT_CHARS // 2 + 1
    blocks = [{"type": "text", "text": "x" * half}, {"type": "text", "text": "x" * half}]
    with pytest.raises(AppError) as exc_info:
        _validate_message_content(blocks)
    assert exc_info.value.code == "SESSION_CONTENT_TOO_LARGE"


def test_normal_content_is_unaffected():
    assert _validate_message_content("scan the target") == "scan the target"
    assert _validate_message_content([{"type": "text", "text": "hello"}]) == "hello"
