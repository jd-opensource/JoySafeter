from app.everos.memory.search import SearchMethod, SearchRequest


def test_search_request_defaults_to_keyword_method():
    req = SearchRequest(
        user_id="user-1",
        app_id="joysafeter",
        project_id="project-1",
        query="python",
    )

    assert req.method == SearchMethod.KEYWORD
