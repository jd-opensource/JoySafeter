import datetime as dt

import pytest
from sqlalchemy import Column, DateTime, String, create_engine, select
from sqlalchemy.orm import Session, declarative_base

from app.joysafeter_domain.pagination import (
    apply_created_at_desc_cursor,
    apply_ordered_cursor,
)

pytestmark = pytest.mark.no_db

Base = declarative_base()


class PageRow(Base):
    __tablename__ = "page_rows"

    id = Column(String, primary_key=True)
    path = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_created_at_cursor_uses_id_tie_breaker_for_same_timestamp() -> None:
    session = _session()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    old = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    session.add_all(
        [
            PageRow(id="a", path="/a", created_at=now),
            PageRow(id="b", path="/b", created_at=now),
            PageRow(id="c", path="/c", created_at=now),
            PageRow(id="old", path="/old", created_at=old),
        ]
    )
    session.commit()

    first_page = session.execute(apply_created_at_desc_cursor(select(PageRow), PageRow, None).limit(2)).scalars().all()
    assert [row.id for row in first_page] == ["c", "b"]

    second_page = (
        session.execute(apply_created_at_desc_cursor(select(PageRow), PageRow, first_page[-1].id).limit(2))
        .scalars()
        .all()
    )
    assert [row.id for row in second_page] == ["a", "old"]


def test_ordered_cursor_tracks_non_time_sort_field() -> None:
    session = _session()
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    session.add_all(
        [
            PageRow(id="1", path="/a", created_at=now),
            PageRow(id="2", path="/b", created_at=now),
            PageRow(id="3", path="/c", created_at=now),
        ]
    )
    session.commit()

    first_page = (
        session.execute(apply_ordered_cursor(select(PageRow), PageRow, None, PageRow.path, descending=False).limit(2))
        .scalars()
        .all()
    )
    assert [row.path for row in first_page] == ["/a", "/b"]

    second_page = (
        session.execute(
            apply_ordered_cursor(
                select(PageRow),
                PageRow,
                first_page[-1].id,
                PageRow.path,
                descending=False,
            ).limit(2)
        )
        .scalars()
        .all()
    )
    assert [row.path for row in second_page] == ["/c"]
