"""Map a failed EntityId validation to the canonical ``{FIELD}_INVALID`` error.

A prefixed-id field (in a request body or a path param) that fails pydantic
validation surfaces here; we recover the offending ``EntityId`` subclass and
build the project's frozen 400 contract, replacing the per-function helpers.
"""

from typing import Optional

from app.joysafeter_shared import ids as _ids
from app.joysafeter_shared.common.app_errors import AppError, InvalidRequestError


def _id_cls_from_error(err: dict) -> Optional[type[_ids.EntityId]]:
    ctx = err.get("ctx") or {}
    id_cls = ctx.get("id_cls")
    if isinstance(id_cls, type) and issubclass(id_cls, _ids.EntityId):
        return id_cls
    msg = str(ctx.get("error") or err.get("msg") or "")
    marker = "__entity_id__:"
    if marker in msg:
        name = msg.split(marker, 1)[1].strip().split()[0]
        candidate = getattr(_ids, name, None)
        if isinstance(candidate, type) and issubclass(candidate, _ids.EntityId):
            return candidate
    return None


def app_error_for_id_validation(err: dict) -> Optional[AppError]:
    id_cls = _id_cls_from_error(err)
    if id_cls is None:
        return None
    field = str(err["loc"][-1])
    raw = err.get("input")
    return InvalidRequestError(
        code=f"{field.upper()}_INVALID",
        message=f"Invalid {field}: {raw}",
        data={"field": field, field: raw, "expected_prefix": id_cls.prefix},
        user_action="fix_input",
    )
