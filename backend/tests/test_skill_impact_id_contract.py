import uuid

import pytest

from app.joysafeter_domain.schemas.joysafeter_skill import SkillImpactSummary
from app.joysafeter_domain.services.joysafeter_skill_service import SkillService
from app.joysafeter_shared.ids import AgentId, AgentVersionId, SkillId, TaskId, TriggerId

pytestmark = pytest.mark.no_db


class _Result:
    def __init__(self, *, count: int | None = None, rows: list[dict[str, object]] | None = None) -> None:
        self._count = count
        self._rows = rows or []

    def scalar_one(self) -> int:
        assert self._count is not None
        return self._count

    def mappings(self) -> "_Result":
        return self

    def __iter__(self):
        return iter(self._rows)


class _ImpactDatabase:
    def __init__(self, ids: list[uuid.UUID]) -> None:
        responses: list[_Result] = []
        for value in ids:
            responses.extend(
                [
                    _Result(count=1),
                    _Result(rows=[{"id": value, "name": "reference", "version": None, "status": None}]),
                ]
            )
        self._responses = iter(responses)

    async def execute(self, _statement: object) -> _Result:
        return next(self._responses)


@pytest.mark.asyncio
async def test_skill_impact_hydrates_each_reference_id_before_response_serialization() -> None:
    raw_ids = [uuid.uuid4() for _ in range(4)]
    service = SkillService.__new__(SkillService)
    service.db = _ImpactDatabase(raw_ids)

    impact = await service._collect_skill_reference_impact(SkillId.new(), sample_limit=8)

    expected_types = (AgentId, AgentVersionId, TriggerId, TaskId)
    assert [type(reference["id"]) for reference in impact["references"]] == list(expected_types)
    serialized = SkillImpactSummary.model_validate(impact).model_dump(mode="json")
    assert [reference["id"] for reference in serialized["references"]] == [
        str(id_type.from_uuid(value)) for id_type, value in zip(expected_types, raw_ids, strict=True)
    ]
