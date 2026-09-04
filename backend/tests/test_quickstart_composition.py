from types import SimpleNamespace

import pytest

from app.joysafeter_application.quickstart.composition import _CredentialModelConnectionReader
from app.joysafeter_shared.ids import CredentialId, ProjectId

pytestmark = pytest.mark.no_db


class _CredentialService:
    def __init__(self) -> None:
        self.calls = []
        self.first_cursor = CredentialId.new()

    async def list(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("after_id") is None:
            return (
                [
                    SimpleNamespace(
                        id=self.first_cursor,
                        provider="openai",
                        protocol="openai_responses",
                        is_default=True,
                        archived_at=None,
                    )
                ],
                True,
            )
        return (
            [
                SimpleNamespace(
                    id=CredentialId.new(),
                    provider="anthropic",
                    protocol="anthropic_messages",
                    is_default=False,
                    archived_at=None,
                )
            ],
            False,
        )


async def test_model_connection_reader_filters_kind_and_reads_every_page():
    credentials = _CredentialService()
    reader = _CredentialModelConnectionReader(credentials)
    project_id = ProjectId.new()

    connections = await reader.list_for_project(project_id)

    assert len(connections) == 2
    assert credentials.calls == [
        {
            "project_id": project_id,
            "kind": "model",
            "include_archived": False,
            "limit": 100,
            "after_id": None,
        },
        {
            "project_id": project_id,
            "kind": "model",
            "include_archived": False,
            "limit": 100,
            "after_id": credentials.first_cursor,
        },
    ]


@pytest.mark.parametrize("page", [([], True), ([SimpleNamespace(id=CredentialId.new())], True)])
async def test_model_connection_reader_rejects_invalid_pagination(page):
    class _InvalidCredentialService:
        async def list(self, **kwargs):
            if not page[0]:
                return page
            return page if kwargs.get("after_id") is None else page

    reader = _CredentialModelConnectionReader(_InvalidCredentialService())

    with pytest.raises(RuntimeError, match="pagination returned"):
        await reader.list_for_project(ProjectId.new())
