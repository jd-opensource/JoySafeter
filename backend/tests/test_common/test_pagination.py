import pytest
from pydantic import ValidationError

from app.common.pagination import ConversationMessagesPaginationParams, PaginationParams


def test_conversation_messages_pagination_allows_page_size_200():
    params = ConversationMessagesPaginationParams(page=1, page_size=200)

    assert params.page == 1
    assert params.page_size == 200
    assert params.offset == 0
    assert params.limit == 200


def test_common_pagination_still_rejects_page_size_200():
    with pytest.raises(ValidationError):
        PaginationParams(page=1, page_size=200)
