"""``everos cascade`` subcommand group.

Three one-shot operations on the cascade subsystem, all run in-process
without standing up the FastAPI app:

- ``cascade sync [PATH]`` — flush the work queue. With ``PATH`` the
  command first force-enqueues that single file (used after a manual
  md edit when waiting for the watcher is impractical), then drains.
- ``cascade status`` — print the queue + LSN summary that the daemon
  sees right now.
- ``cascade fix`` — list every ``failed`` row. With ``--apply``, also
  reset ``retryable=TRUE`` rows back to ``pending`` and drain the
  worker once so the retry actually runs before the command returns.

CLI is in-process (12 doc §7.1 + 16 doc §9.2): it constructs the same
:class:`CascadeOrchestrator` as the daemon but only calls
``sync_once`` / ``drain_once`` / ``queue_summary``. No watcher /
scanner background task is started.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import typer
from sqlmodel import SQLModel

from app.everos.component.embedding import build_embedding_provider
from app.everos.component.tokenizer import build_tokenizer
from app.everos.component.utils.datetime import to_display_tz
from app.everos.config import load_settings
from app.everos.core.persistence import MemoryRoot
from app.everos.infra.persistence.lancedb import (
    dispose_connection,
    ensure_business_indexes,
    get_connection,
    verify_business_schemas,
)
from app.everos.infra.persistence.sqlite import (
    dispose_engine,
    get_engine,
    md_change_state_repo,
)
from app.everos.memory.cascade import CascadeOrchestrator, match_kind
from app.everos.memory.cascade.duplicate_entries import scan_duplicate_entry_files
from app.everos.memory.vector_rebuild import (
    default_vector_rebuild_specs,
    rebuild_fallback_rows,
)

app = typer.Typer(
    name="cascade",
    help="Inspect and operate the md → LanceDB sync queue",
    no_args_is_help=True,
)


@app.callback()
def _cascade_callback(
    root: str | None = typer.Option(
        None,
        "--root",
        help="Memory root directory (env: EVEROS_ROOT, default: ~/.everos)",
    ),
) -> None:
    """Set memory root before any cascade subcommand runs."""
    if root:
        os.environ["EVEROS_ROOT"] = root


# ── shared runtime context ───────────────────────────────────────────────


@asynccontextmanager
async def _runtime():  # type: ignore[no-untyped-def]
    """Stand up sqlite + lancedb the same way the API lifespan would.

    The CLI piggybacks on the same singletons as the running daemon
    (lazy + process-wide), so if a server happens to be running on
    the same memory root, both share state correctly.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await get_connection()
    await verify_business_schemas()
    await ensure_business_indexes()
    try:
        yield
    finally:
        await dispose_connection()
        await dispose_engine()


def _build_orchestrator() -> CascadeOrchestrator:
    settings = load_settings()
    memory_root = MemoryRoot.default()
    memory_root.ensure()
    embedder = build_embedding_provider(settings.embedding)
    tokenizer = build_tokenizer()
    return CascadeOrchestrator(
        memory_root=memory_root,
        embedder=embedder,
        tokenizer=tokenizer,
    )


# ── sync ─────────────────────────────────────────────────────────────────


@app.command("sync")
def sync(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Optional md path to force-enqueue before draining. "
            "If omitted, only the existing queue is drained.",
        ),
    ] = None,
) -> None:
    """Drain the cascade queue (and optionally re-enqueue a path first)."""

    async def _run() -> None:
        async with _runtime():
            orchestrator = _build_orchestrator()
            if path is not None:
                rel = _resolve_relative(path)
                spec = match_kind(rel)
                if spec is None:
                    typer.echo(
                        f"error: path does not match any registered cascade "
                        f"kind: {rel}",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                await md_change_state_repo.force_enqueue(rel, spec.name)
                typer.echo(f"force-enqueued {rel} (kind={spec.name})")
            processed = await orchestrator.sync_once()
            typer.echo(f"sync complete — processed {processed} row(s)")

    asyncio.run(_run())


# ── status ───────────────────────────────────────────────────────────────


@app.command("status")
def status() -> None:
    """Print the queue / LSN summary."""

    async def _run() -> None:
        async with _runtime():
            summary = await md_change_state_repo.queue_summary()
            lag = max(0, summary.max_lsn - summary.last_processed_lsn)
            typer.echo("queue:")
            typer.echo(f"  pending:                  {summary.pending}")
            typer.echo(f"  done:                     {summary.done}")
            typer.echo(
                f"  failed (retryable=TRUE):  {summary.failed_retryable}"
                + (
                    "     (eligible for `cascade fix --apply`)"
                    if summary.failed_retryable
                    else ""
                )
            )
            typer.echo(
                f"  failed (retryable=FALSE): {summary.failed_permanent}"
                + (
                    "     (fix md and re-save to recover)"
                    if summary.failed_permanent
                    else ""
                )
            )
            typer.echo("lsn:")
            typer.echo(f"  max:           {summary.max_lsn}")
            typer.echo(f"  last_processed: {summary.last_processed_lsn}")
            typer.echo(f"  lag:            {lag}")

    asyncio.run(_run())


# ── vector rebuild ───────────────────────────────────────────────────────


@app.command("vector-rebuild")
def vector_rebuild(
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help=(
                "Memory kind to rebuild: all, episode, atomic_fact, foresight, "
                "agent_case, or agent_skill."
            ),
        ),
    ] = "all",
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum fallback rows per kind."),
    ] = 1000,
) -> None:
    """Rebuild rows whose vectors were written with the zero-vector fallback."""

    async def _run() -> None:
        async with _runtime():
            settings = load_settings()
            embedder = build_embedding_provider(settings.embedding)
            specs = {spec.kind: spec for spec in default_vector_rebuild_specs()}
            selected = specs.keys() if kind == "all" else [kind]
            total = 0
            for selected_kind in selected:
                spec = specs.get(selected_kind)
                if spec is None:
                    typer.echo(f"error: unsupported kind {selected_kind!r}", err=True)
                    raise typer.Exit(code=1)
                try:
                    count = await rebuild_fallback_rows(
                        spec.repo,
                        text_getter=spec.text_getter,
                        embedder=embedder,
                        embedding_model=settings.embedding.model,
                        limit=limit,
                    )
                except Exception as exc:  # noqa: BLE001 - CLI should stay readable.
                    typer.echo(
                        f"{selected_kind}: vector rebuild failed: {exc}",
                        err=True,
                    )
                    raise typer.Exit(code=1) from exc
                total += count
                typer.echo(f"{selected_kind}: rebuilt {count} row(s)")
            typer.echo(f"vector rebuild complete — rebuilt {total} row(s)")

    asyncio.run(_run())


# ── fix ──────────────────────────────────────────────────────────────────


@app.command("fix")
def fix(
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Re-enqueue every `retryable=TRUE` row and drain the worker.",
        ),
    ] = False,
) -> None:
    """List failed rows (default) or re-enqueue retryable ones (``--apply``)."""

    async def _run() -> None:
        async with _runtime():
            rows = await md_change_state_repo.list_failed()
            if not rows:
                typer.echo("no failed rows")
                return

            if not apply:
                _print_failed_table(rows)
                retryable = sum(1 for r in rows if r.retryable)
                permanent = sum(1 for r in rows if not r.retryable)
                typer.echo("")
                if retryable:
                    typer.echo(
                        f"run `everos cascade fix --apply` to re-enqueue "
                        f"the {retryable} retryable row(s)."
                    )
                if permanent:
                    typer.echo(
                        f"the {permanent} retryable=FALSE row(s) require "
                        "editing the md and re-saving."
                    )
                return

            moved = await md_change_state_repo.reset_retryable_to_pending()
            typer.echo(f"re-enqueued {moved} retryable row(s)")
            if moved:
                orchestrator = _build_orchestrator()
                processed = await orchestrator.drain_once()
                typer.echo(f"[worker] processed {processed} row(s) on drain")
            permanent_rows = [r for r in rows if not r.retryable]
            if permanent_rows:
                typer.echo(
                    f"{len(permanent_rows)} retryable=FALSE row(s) left untouched:"
                )
                for r in permanent_rows:
                    typer.echo(f"  {r.md_path}")

    asyncio.run(_run())


@app.command("repair-duplicates")
def repair_duplicates(
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="Daily-log kind to scan: all, episode, atomic_fact, foresight, agent_case.",
        ),
    ] = "all",
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Rewrite files, keeping the last duplicate entry block for each id.",
        ),
    ] = False,
) -> None:
    """Report or repair duplicate daily-log entry ids in markdown files."""
    memory_root = MemoryRoot.default()
    try:
        reports = scan_duplicate_entry_files(memory_root.root, apply=apply, kind=kind)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not reports:
        typer.echo("no duplicate daily-log entry ids found")
        return

    action = "repaired" if apply else "found"
    typer.echo(f"{action} {len(reports)} file(s) with duplicate entry ids:")
    for report in reports:
        try:
            display_path = report.path.relative_to(memory_root.root)
        except ValueError:
            display_path = report.path
        duplicates = ", ".join(
            f"{entry_id} x{count}"
            for entry_id, count in sorted(report.duplicate_counts.items())
        )
        typer.echo(
            f"  {display_path}: {duplicates} "
            f"({report.original_count} entries -> {report.unique_count})"
        )

    if not apply:
        typer.echo("run `everos cascade repair-duplicates --apply` to rewrite files.")
    else:
        typer.echo("duplicate repair complete; run `everos cascade sync` if needed.")


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_relative(p: Path) -> str:
    """Translate an absolute / relative path arg into the memory-root rel form.

    The state table stores paths relative to memory root, so the CLI
    must match that convention before calling :meth:`force_enqueue`.
    Outside-the-root inputs surface as an error in the caller.
    """
    memory_root = MemoryRoot.default()
    absolute = p.expanduser().resolve()
    try:
        rel = absolute.relative_to(memory_root.root)
    except ValueError as exc:
        raise typer.BadParameter(
            f"path {p!s} is not under memory root {memory_root.root!s}"
        ) from exc
    return rel.as_posix()


def _print_failed_table(rows: list) -> None:  # type: ignore[type-arg]
    headers = ("md_path", "retryable", "retries", "last_attempt", "error")
    widths = [
        max(len(headers[0]), max(len(r.md_path) for r in rows)),
        len(headers[1]),
        len(headers[2]),
        len(headers[3]),
        max(len(headers[4]), max(len(r.error or "") for r in rows)),
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(f"{len(rows)} failed row(s):\n")
    typer.echo(fmt.format(*headers))
    for r in rows:
        typer.echo(
            fmt.format(
                r.md_path,
                "TRUE" if r.retryable else "FALSE",
                r.retry_count,
                to_display_tz(r.last_attempt_at).isoformat()
                if r.last_attempt_at
                else "",
                r.error or "",
            )
        )
