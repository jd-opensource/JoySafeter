"""Content-Disposition must be built safely from a user-controlled filename.

The download endpoint interpolated ``record.filename`` straight into the
``Content-Disposition`` header. A filename containing a double-quote or CRLF
could break header quoting / inject header content, and a non-ASCII filename
makes the (latin-1) header value fail to encode → 500. The safe builder emits a
sanitized ASCII ``filename="..."`` fallback plus an RFC 5987 ``filename*`` with
percent-encoded UTF-8, so the header is always well-formed and latin-1 safe.
"""

import pytest

from app.joysafeter_api.api.v1.files import _safe_content_disposition

pytestmark = pytest.mark.no_db


def test_plain_filename_is_quoted_normally():
    cd = _safe_content_disposition("report.pdf")
    assert 'filename="report.pdf"' in cd
    assert cd.startswith("attachment;")


def test_double_quote_cannot_break_out_of_the_header():
    cd = _safe_content_disposition('a"b.txt')
    # The raw quote must not appear unescaped inside the fallback value.
    assert 'filename="a"b.txt"' not in cd
    # The real name is preserved percent-encoded in the RFC 5987 form.
    assert "filename*=UTF-8''" in cd
    assert "%22" in cd


def test_crlf_is_stripped_from_the_header():
    cd = _safe_content_disposition("evil\r\nSet-Cookie: pwn=1")
    assert "\r" not in cd
    assert "\n" not in cd


def test_non_ascii_filename_is_latin1_encodable():
    cd = _safe_content_disposition("报告.pdf")
    # ASGI header values are latin-1 encoded; the builder output must never raise.
    cd.encode("latin-1")
    assert "filename*=UTF-8''" in cd
    assert "%E6" in cd  # percent-encoded UTF-8 bytes of the CJK name


def test_empty_or_all_stripped_filename_falls_back():
    assert 'filename="download"' in _safe_content_disposition('"""')
