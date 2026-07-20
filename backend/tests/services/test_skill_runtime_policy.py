"""Unit tests for ``skill_runtime_policy.is_skill_usable``.

The runtime gate is the only piece of code that sits between a skill row
and a sandbox bundle, so it earns dedicated coverage. These tests use
``SimpleNamespace`` skill fakes instead of ORM rows — the gate reads
seven attributes (``name``, ``description``, ``content``, ``tags``,
``license``, ``files``, ``lifecycle_status``, ``security_status``,
``security_scan_hash``) and nothing else, so a fake matches the shape
exactly with no DB plumbing.

What we verify:

  - approved + scanned + drift-free  -> usable
  - lifecycle gate (4 non-approved states)
  - security gate (3 non-allowlisted statuses)
  - drift detection (hash mismatch, missing hash)
  - drift is hashed over the canonical fields (changing content/tags/
    license/files trips drift even with the right lifecycle+security)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_skill_security import (
    build_scan_files,
    is_skill_usable,
    target_hash,
)


def _hash_for(*, name="t", description="d", content="c", tags=None, license=None, files=None):
    """Compute the canonical scan hash the gate compares against."""
    tags = tags or []
    files = files or []
    canon_files = build_scan_files(
        name=name,
        description=description,
        content=content,
        tags=tags,
        license=license,
        files=files,
    )
    return target_hash(
        name=name,
        description=description,
        content=content,
        tags=tags,
        license=license,
        files=canon_files,
    )


def _skill(
    *,
    name="t",
    description="d",
    content="c",
    tags=None,
    license=None,
    files=None,
    lifecycle="approved",
    security="passed",
    sec_hash=None,
):
    if sec_hash is None:
        sec_hash = _hash_for(
            name=name,
            description=description,
            content=content,
            tags=tags,
            license=license,
            files=files,
        )
    return SimpleNamespace(
        name=name,
        description=description,
        content=content,
        tags=tags or [],
        license=license,
        files=files or [],
        lifecycle_status=lifecycle,
        security_status=security,
        security_scan_hash=sec_hash,
    )


# ── happy path ─────────────────────────────────────────────────


def test_approved_and_scanned_skill_is_usable():
    ok, reason = is_skill_usable(_skill())
    assert ok is True
    assert reason is None


# ── lifecycle gate ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "lifecycle",
    ["draft", "pending_review", "rejected", "archived"],
)
def test_non_approved_lifecycle_blocks(lifecycle):
    ok, reason = is_skill_usable(_skill(lifecycle=lifecycle))
    assert ok is False
    assert reason == "skill_not_approved"


# ── security gate ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "security",
    ["not_scanned", "blocked", "failed"],
)
def test_non_allowlisted_security_blocks(security):
    ok, reason = is_skill_usable(_skill(security=security))
    assert ok is False
    assert reason == f"security_{security}"


def test_warning_security_is_still_usable():
    """``warning`` is the second allowed status — non-critical findings
    don't kick a skill out of the runtime, just out of "passed"."""
    ok, reason = is_skill_usable(_skill(security="warning"))
    assert ok is True
    assert reason is None


# ── drift gate ─────────────────────────────────────────────────


def test_missing_scan_hash_blocks():
    ok, reason = is_skill_usable(_skill(sec_hash=""))
    assert ok is False
    assert reason == "no_security_scan_hash"


def test_hash_mismatch_blocks():
    ok, reason = is_skill_usable(_skill(sec_hash="not_the_real_hash"))
    assert ok is False
    assert reason == "content_changed_after_scan"


def test_drift_detected_when_content_changes_after_scan():
    """The skill was scanned with content='c' but currently has content='c2'."""
    sec_hash_for_c = _hash_for(content="c")
    skill = _skill(content="c2", sec_hash=sec_hash_for_c)
    ok, reason = is_skill_usable(skill)
    assert ok is False
    assert reason == "content_changed_after_scan"


def test_drift_detected_when_tags_change_after_scan():
    sec_hash_for_a = _hash_for(tags=["a"])
    skill = _skill(tags=["a", "b"], sec_hash=sec_hash_for_a)
    ok, reason = is_skill_usable(skill)
    assert ok is False
    assert reason == "content_changed_after_scan"


def test_drift_detected_when_license_changes_after_scan():
    sec_hash_mit = _hash_for(license="MIT")
    skill = _skill(license="Apache-2.0", sec_hash=sec_hash_mit)
    ok, reason = is_skill_usable(skill)
    assert ok is False
    assert reason == "content_changed_after_scan"


def test_drift_detected_when_a_skill_file_changes():
    """Adding a file (non-system, non-legal) trips drift because
    ``build_scan_files`` carries it into the hash."""
    file_a = _file_obj(path="foo.py", file_name="foo.py", content="print('a')")
    file_b = _file_obj(path="bar.py", file_name="bar.py", content="print('b')")
    base_hash = _hash_for(
        files=[{"path": "foo.py", "file_name": "foo.py", "file_type": "text", "content": "print('a')"}]
    )
    skill = _skill(files=[file_a, file_b], sec_hash=base_hash)
    ok, reason = is_skill_usable(skill)
    assert ok is False
    assert reason == "content_changed_after_scan"


# ── helpers ─────────────────────────────────────────────────────


def _file_obj(*, path, file_name, content, file_type="text"):
    """SkillFile-shaped object for the ``files`` payload the gate reads.

    The gate's ``_files_payload`` projection reads attributes by name,
    so a ``SimpleNamespace`` with the same attributes works without
    requiring the ORM model.
    """
    return SimpleNamespace(
        path=path,
        file_name=file_name,
        file_type=file_type,
        content=content,
        storage_type="database",
        storage_key=None,
        size=len(content),
    )
