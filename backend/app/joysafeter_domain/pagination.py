"""Shared keyset pagination helpers for domain list queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select


def apply_ordered_cursor(
    query: Any,
    model: Any,
    after_id: Any | None,
    order_column: Any,
    *,
    descending: bool,
) -> Any:
    """Apply stable keyset pagination for one ordered column plus ``id``."""

    if after_id is not None:
        cursor_value = select(order_column).where(model.id == after_id).scalar_subquery()
        if descending:
            query = query.where(
                or_(
                    order_column < cursor_value,
                    and_(order_column == cursor_value, model.id < after_id),
                )
            )
        else:
            query = query.where(
                or_(
                    order_column > cursor_value,
                    and_(order_column == cursor_value, model.id > after_id),
                )
            )
    return query.order_by(
        order_column.desc() if descending else order_column.asc(),
        model.id.desc() if descending else model.id.asc(),
    )


def apply_created_at_desc_cursor(query: Any, model: Any, after_id: Any | None) -> Any:
    """Apply stable ``created_at desc, id desc`` keyset pagination.

    List endpoints expose ``after_id`` as the cursor. The cursor row's
    ``created_at`` is the primary keyset boundary and ``id`` is the deterministic
    tie-breaker for rows created at the same timestamp.
    """

    return apply_ordered_cursor(query, model, after_id, model.created_at, descending=True)
