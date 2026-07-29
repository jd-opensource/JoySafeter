"""Periodic md tree scanner.

The watcher catches realtime events but misses:

- files created while the daemon was down,
- ``cp`` / external editors that move-replace and confuse inotify,
- WSL2 / network mounts where fsevents don't propagate.

The scanner closes those gaps by walking the memory root every
``scan_interval`` seconds (default 30s, configurable later), matching
paths against the kind registry, reading prior state, and running the
pure :func:`reconcile` function to emit the upsert plan.

Walking happens off the event loop via ``asyncio.to_thread`` since
``pathlib.Path.rglob`` is sync; the prior-state fetch + upsert calls
stay async on the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable
from pathlib import Path

from sqlmodel import select

from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import MarkdownReader, MemoryRoot
from app.everos.core.persistence.sqlite import session_scope
from app.everos.infra.persistence.sqlite import (
    MdChangeState,
    get_session_factory,
    md_change_state_repo,
)

from .handlers._common import content_sha256 as compute_content_sha256
from .handlers.user_profile import _dump_json as dump_profile_json
from .reconciler import PriorState, reconcile
from .registry import KIND_REGISTRY
from .types import ReconcileDecision, ScanInput

logger = get_logger(__name__)

PROJECTION_AUDITED_KINDS = {"agent_skill", "atomic_fact", "user_profile"}


class CascadeScanner:
    """Periodic walker — owns its asyncio task."""

    def __init__(
        self,
        memory_root: MemoryRoot,
        *,
        scan_interval_seconds: float = 30.0,
    ) -> None:
        self._memory_root = memory_root
        self._interval = scan_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="cascade-scanner")
        logger.info("cascade_scanner_started", interval=self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None
        logger.info("cascade_scanner_stopped")

    async def scan_once(self) -> list[ReconcileDecision]:
        """One scan + reconcile pass; returns the decisions that were
        upserted into :class:`MdChangeState`.

        Exposed so the CLI ``cascade sync`` command can trigger a sweep
        without owning a long-lived scanner task.
        """
        scan_inputs = await asyncio.to_thread(
            _collect_scan_inputs, self._memory_root.root
        )
        state = await _load_state_snapshot()
        stale_or_missing_projections = await _find_stale_or_missing_done_projections(
            scan_inputs,
            state,
            self._memory_root.root,
        )
        decisions = reconcile(
            scan_inputs,
            state,
            missing_projections=stale_or_missing_projections,
        )
        for decision in decisions:
            await md_change_state_repo.upsert(
                decision.md_path,
                kind=decision.kind,
                change_type=decision.change_type,
                mtime=decision.mtime,
            )
        if decisions:
            logger.info(
                "cascade_scanner_decisions",
                count=len(decisions),
                added=sum(1 for d in decisions if d.change_type == "added"),
                modified=sum(1 for d in decisions if d.change_type == "modified"),
                deleted=sum(1 for d in decisions if d.change_type == "deleted"),
            )
        return decisions

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except Exception as exc:  # noqa: BLE001 — never crash the daemon
                logger.exception("cascade_scanner_failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue


def _collect_scan_inputs(root: Path) -> list[ScanInput]:
    """Walk ``root`` once per registered kind, returning every match.

    ``stat()`` failure mode discrimination is **load-bearing**: the
    reconciler treats "in state but not in scan" as a deletion signal,
    so if we silently drop a path here under a *transient* OS error,
    the next reconcile sweep will emit ``change_type='deleted'`` for
    that healthy md and the handler will wipe its LanceDB rows.

    Two errno classes:

    - :class:`FileNotFoundError` (ENOENT) — the file was unlinked
      between ``glob`` and ``stat``. This is a genuine deletion; drop
      from inputs so the reconciler emits ``deleted`` (correct).
    - any other :class:`OSError` (EMFILE / ENFILE — FD exhaustion,
      EACCES — perms, EIO — disk error, etc.) — we don't know whether
      the file is gone. **Raise** to abort the whole sweep; the
      ``_run_loop`` outer ``try / except Exception`` catches and logs
      it, and we retry on the next interval. A partial scan is worse
      than no scan, because the reconciler can't tell the difference.

    Symptom this guards against (observed 2026-05-28 on LoCoMo
    benchmark conv_2): a search-time FD exhaustion bled into the
    concurrent scanner sweep, and 8 healthy md files got marked
    ``change_type=deleted, status=done`` with their LanceDB rows
    cleared — single-direction data loss until external intervention.
    """
    inputs: list[ScanInput] = []
    for spec in KIND_REGISTRY:
        for absolute in root.glob(spec.path_glob()):
            try:
                mtime = absolute.stat().st_mtime
            except FileNotFoundError:
                # Race between glob and stat; treat as a genuine deletion
                # by leaving this path out of inputs.
                continue
            # Any other OSError (EMFILE / EACCES / EIO ...) — propagate.
            # Partial inputs would trigger spurious deletes in reconcile().
            try:
                rel = absolute.relative_to(root).as_posix()
            except ValueError:
                continue
            if _is_ignored_scan_path(rel):
                continue
            inputs.append(ScanInput(md_path=rel, mtime=mtime, kind=spec.name))
    return inputs


def _is_ignored_scan_path(md_path: str) -> bool:
    return Path(md_path).parts[:1] == (".tmp",)


async def _find_stale_or_missing_done_projections(
    scan_inputs: list[ScanInput],
    state: dict[str, PriorState],
    root: Path,
) -> set[str]:
    """Find done md files whose LanceDB projection is missing or stale.

    The normal reconciler only compares md mtime against md_change_state.
    That misses rebuild/migration failures where the md file still exists
    and the state row is done, but the derived LanceDB row disappeared or
    still carries an older ``content_sha256`` than the md source of truth.
    """
    specs_by_kind = {spec.name: spec for spec in KIND_REGISTRY}
    dirty: set[str] = set()
    for item in scan_inputs:
        if item.kind not in PROJECTION_AUDITED_KINDS:
            continue
        prior = state.get(item.md_path)
        if (
            prior is None
            or prior.status != "done"
            or prior.change_type == "deleted"
            or prior.mtime != item.mtime
        ):
            continue
        spec = specs_by_kind.get(item.kind)
        repo = spec.lance_repo if spec is not None else None
        find_by_md_path = getattr(repo, "find_by_md_path", None)
        if find_by_md_path is None:
            continue
        try:
            projection = await find_by_md_path(item.md_path)
        except Exception as exc:  # noqa: BLE001 - scan should retry next interval.
            logger.warning(
                "cascade_projection_audit_failed",
                md_path=item.md_path,
                kind=item.kind,
                error=str(exc),
            )
            continue
        if projection is None:
            dirty.add(item.md_path)
            continue

        expected_digest = await _expected_projection_content_sha256(
            item.kind,
            item.md_path,
            root,
        )
        current_digest = getattr(projection, "content_sha256", None)
        if expected_digest is not None and current_digest != expected_digest:
            dirty.add(item.md_path)
    if dirty:
        logger.warning(
            "cascade_dirty_done_projections",
            count=len(dirty),
            kinds=sorted({state[path].kind for path in dirty if path in state}),
        )
    return dirty


async def _expected_projection_content_sha256(
    kind: str,
    md_path: str,
    root: Path,
) -> str | None:
    """Compute the md-side projection digest for single-file audited kinds.

    Daily-log kinds can contain multiple rows per md file, so the scanner
    currently only computes stale-projection digests for single-file kinds
    whose md path maps to one LanceDB row.
    """
    if kind != "user_profile":
        return None

    parsed = await MarkdownReader.read(root / md_path)
    fm = parsed.frontmatter
    return compute_content_sha256(
        {
            "frontmatter:summary": str(fm.get("summary", "")),
            "frontmatter:explicit_info_json": dump_profile_json(
                fm.get("explicit_info", [])
            ),
            "frontmatter:implicit_traits_json": dump_profile_json(
                fm.get("implicit_traits", [])
            ),
        }
    )


async def _find_missing_done_projections(
    scan_inputs: list[ScanInput],
    state: dict[str, PriorState],
) -> set[str]:
    """Backward-compatible wrapper for tests and older callers."""
    return await _find_stale_or_missing_done_projections(
        scan_inputs,
        state,
        MemoryRoot.default().root,
    )


async def _load_state_snapshot() -> dict[str, PriorState]:
    """Project every row in ``md_change_state`` into :class:`PriorState`."""
    factory = get_session_factory()
    async with session_scope(factory) as s:
        rows: Iterable[MdChangeState] = (
            (await s.execute(select(MdChangeState))).scalars().all()
        )
        return {
            row.md_path: PriorState(
                md_path=row.md_path,
                kind=row.kind,
                mtime=row.mtime,
                status=row.status,
                change_type=row.change_type,
            )
            for row in rows
        }
