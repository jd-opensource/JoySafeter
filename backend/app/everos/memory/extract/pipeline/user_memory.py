"""User memory pipeline — per-sender Episode fan-out on pre-cut cells.

Cells / memcell_ids / message_id-mapping / sender lists are produced by
:mod:`everos.service._boundary` (which also writes the single
``memcell`` sqlite row per cell). This pipeline only handles the
user-perspective output: Episode md + ``UserPipelineStarted`` emit (one
per cell, fired at the start of ``run`` so atomic_fact / foresight /
clustering strategies run in parallel with the in-pipeline Episode work).

Run inside ``service.memorize`` via ``asyncio.gather`` alongside
:class:`AgentMemoryPipeline` (the latter only in ``mode="agent"``).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from everalgo.types import MemCell as AlgoMemCell
from everalgo.user_memory import EpisodeExtractor

from app.everos.component.llm.protocol import ChatMessage
from app.everos.component.utils.datetime import from_timestamp, to_iso_format
from app.everos.core.observability.logging import get_logger
from app.everos.memory import Episode, IngestResult, PipelineOutcome
from app.everos.memory.events import EpisodeExtracted, UserPipelineStarted
from app.everos.memory.language_policy import ensure_chinese_memory_llm
from app.everos.memory.prompt_slots import PromptLoader

if TYPE_CHECKING:
    from everalgo.llm.protocols import LLMClient

    from app.everos.infra.ome.engine import OfflineEngine
    from app.everos.infra.persistence.markdown import EpisodeWriter

logger = get_logger(__name__)

_TRACK = "user_memory"
_EPISODE_SUMMARY_EXTRACTION_ATTEMPTS = 3
_EPISODE_SUMMARY_MAX_SENTENCES = 3
_EPISODE_SUMMARY_MAX_CHARS = 360
_EPISODE_SUBJECT_MAX_CHARS = 140
_SUMMARY_SENTENCE_RE = re.compile(r"[^。！？.!?]+[。！？.!?]+(?:[\"'”’)\]]+)?|[^。！？.!?]+$")


class UserMemoryPipeline:
    """Per-sender Episode extraction on a list of pre-cut MemCells."""

    def __init__(
        self,
        episode_writer: EpisodeWriter,
        prompt_loader: PromptLoader,
        llm_client: LLMClient | None,
        engine: OfflineEngine,
    ) -> None:
        # EpisodeExtractor requires `llm` at construction. Skip-with-warning
        # when no LLM is configured — the boundary stage will have skipped
        # the run already; this is just a defensive null check.
        memory_llm_client = (
            ensure_chinese_memory_llm(llm_client) if llm_client is not None else None
        )
        self._ep_ext = (
            EpisodeExtractor(llm=memory_llm_client)
            if memory_llm_client is not None
            else None
        )
        self._llm_client = memory_llm_client
        self._episode_writer = episode_writer
        self._prompt_loader = prompt_loader
        self._engine = engine

    async def run(
        self,
        ingested: IngestResult,
        cells: list[AlgoMemCell],
        memcell_ids: list[str],
        per_cell_all_senders: list[list[str]],
    ) -> PipelineOutcome:
        """Emit UserPipelineStarted per cell, then extract Episodes + write md."""
        if not cells:
            return PipelineOutcome(track=_TRACK, status="accumulated", message_count=0)
        if self._ep_ext is None:
            logger.warning(
                "user_memory_pipeline_no_llm_client",
                extra={"session_id": ingested.session_id, "cells": len(cells)},
            )
            return PipelineOutcome(track=_TRACK, status="skipped", message_count=0)

        # Emit upfront so OME-async strategies (atomic_fact / foresight /
        # cluster) start in parallel with the in-pipeline Episode work; they
        # consume the MemCell directly and do not depend on Episode output.
        for cell, memcell_id in zip(cells, memcell_ids, strict=True):
            await self._emit_pipeline_started(
                memcell_id=memcell_id,
                session_id=ingested.session_id,
                app_id=ingested.app_id,
                project_id=ingested.project_id,
                cell=cell,
            )

        episode_prompt = self._prompt_loader.load("episode_extract")
        md_paths: list[str] = []
        msg_count = 0
        for cell, memcell_id, all_senders in zip(
            cells, memcell_ids, per_cell_all_senders, strict=True
        ):
            msg_count += len(cell.items)
            user_senders = _unique_user_senders(cell)
            if not user_senders:
                continue
            # One generic LLM call per cell (sender_id=None drives the algo's
            # whole-memcell EPISODE_GENERATION_PROMPT — explicitly cheaper
            # than the per-user fan-out per the algo's docstring). Fan-out
            # is then md-only: every user sender owns a copy of the same
            # narrative under its own owner_id path.
            algo_ep = await _extract_episode_with_summary_retry(
                self._ep_ext,
                cell=cell,
                prompt=episode_prompt,
            )
            for sender_id in user_senders:
                ep = Episode.from_algo(
                    algo_ep,
                    owner_id=sender_id,
                    session_id=ingested.session_id,
                    sender_ids=all_senders,
                    parent_id=memcell_id,
                    source_timestamp_ms=cell.timestamp,
                )
                ep = await _ensure_episode_summary(ep, self._llm_client)
                inline, sections = _episode_to_entry_body(ep)
                eid = await self._episode_writer.append_entry(
                    ep.owner_id,
                    inline=inline,
                    sections=sections,
                    app_id=ingested.app_id,
                    project_id=ingested.project_id,
                )
                md_paths.append(
                    str(
                        self._episode_writer.path_for(
                            ep.owner_id,
                            eid.date,
                            app_id=ingested.app_id,
                            project_id=ingested.project_id,
                        )
                    )
                )
                await self._engine.emit(
                    EpisodeExtracted(
                        memcell_id=memcell_id,
                        episode_entry_id=eid.format(),
                        episode_text=ep.episode,
                        episode_timestamp_ms=ep.timestamp,
                        owner_id=ep.owner_id,
                        session_id=ingested.session_id,
                        app_id=ingested.app_id,
                        project_id=ingested.project_id,
                        source="pipeline",
                    )
                )

        return PipelineOutcome(
            track=_TRACK,
            status="extracted",
            message_count=msg_count,
            extracted_md_paths=md_paths,
        )

    async def _emit_pipeline_started(
        self,
        memcell_id: str,
        session_id: str,
        app_id: str,
        project_id: str,
        cell: AlgoMemCell,
    ) -> None:
        await self._engine.emit(
            UserPipelineStarted(
                memcell_id=memcell_id,
                session_id=session_id,
                app_id=app_id,
                project_id=project_id,
                memcell=cell,
            )
        )


# ── Helpers ───────────────────────────────────────────────────────────────


def _unique_user_senders(cell: AlgoMemCell) -> list[str]:
    """Distinct role=user sender_ids in a cell, preserving order.

    Drives per-sender Episode fan-out: each user perspective gets its own
    Episode for the cell. Skips non-``ChatMessage`` items (agent
    trajectories' ``ToolCallResult`` has no ``role``).
    """
    senders: list[str] = []
    for item in cell.items:
        if getattr(item, "role", None) != "user":
            continue
        sid = getattr(item, "sender_id", None)
        if sid and sid not in senders:
            senders.append(sid)
    return senders


def _episode_to_entry_body(
    episode: Episode,
) -> tuple[dict[str, object], dict[str, str]]:
    """Split a domain Episode into ``(inline, sections)`` for md rendering.

    Lives in the pipeline (memory) layer rather than the writer (infra)
    because it depends on :class:`everos.memory.Episode` — infra is not
    allowed to import memory per the layered architecture contract.

    Inline persists the audit / scope fields cascade needs to rebuild
    the LanceDB row: ``owner_id`` / ``session_id`` / ``timestamp`` /
    ``parent_id`` / ``sender_ids``. ``parent_id`` is the source memcell
    id (minted by the boundary stage), and the cascade handler reads it
    back so the LanceDB ``episode`` row keeps its back-link to the source.

    The md entry's ``entry_id`` (managed by the chassis writer) is the
    in-file entry identity; cascade derives a global episode id from
    ``<md_path>#<entry_id>`` on the fly.
    """
    ts_iso = (
        to_iso_format(from_timestamp(episode.timestamp))
        if isinstance(episode.timestamp, int)
        else str(episode.timestamp)
    )

    inline: dict[str, object] = {
        "owner_id": episode.owner_id,
        "session_id": episode.session_id,
        "timestamp": ts_iso,
        "parent_type": "memcell",
        "parent_id": episode.parent_id,
    }
    if episode.sender_ids:
        inline["sender_ids"] = list(episode.sender_ids)

    extra = episode.model_dump(
        exclude={
            "owner_id",
            "episode",
            "timestamp",
            "session_id",
            "sender_ids",
            "parent_id",
        }
    )
    subject = extra.pop("subject", None)
    summary = extra.pop("summary", None)

    sections: dict[str, str] = {
        "Subject": _normalise_episode_subject(subject, episode.episode),
    }
    if summary:
        sections["Summary"] = str(summary)
    sections["Content"] = episode.episode
    return inline, sections


async def _extract_episode_with_summary_retry(
    extractor: Any,
    *,
    cell: AlgoMemCell,
    prompt: str | None,
) -> Any:
    """Run the primary episode extractor up to three times for a valid summary."""
    last_episode: Any | None = None
    for _attempt in range(_EPISODE_SUMMARY_EXTRACTION_ATTEMPTS):
        last_episode = await extractor.aextract(cell, sender_id=None, prompt=prompt)
        if _summary_is_valid(
            getattr(last_episode, "summary", None),
            str(getattr(last_episode, "episode", "")),
        ):
            return last_episode
    return last_episode


async def _ensure_episode_summary(
    episode: Episode,
    llm_client: LLMClient | None,
) -> Episode:
    """Guarantee a usable summary before an Episode reaches md persistence."""
    summary = getattr(episode, "summary", None)
    if _summary_is_valid(summary, episode.episode):
        limited = _limit_episode_summary(summary)
        if limited == summary.strip():
            return episode
        return episode.model_copy(update={"summary": limited})

    generated = await _summarize_episode_content(episode.episode, llm_client)
    if _summary_is_valid(generated, episode.episode):
        return episode.model_copy(update={"summary": _limit_episode_summary(generated)})

    return episode.model_copy(
        update={
            "summary": _fallback_episode_summary(
                episode.episode,
                getattr(episode, "subject", None),
            )
        }
    )


def _summary_is_valid(summary: object, content: str) -> bool:
    if not isinstance(summary, str):
        return False
    summary = summary.strip()
    content = content.strip()
    if not summary or not content:
        return False
    summary_norm = _normalise_summary_text(summary)
    content_norm = _normalise_summary_text(content)
    if summary_norm == content_norm:
        return False
    return not (len(summary_norm) >= 12 and content_norm.startswith(summary_norm))


async def _summarize_episode_content(
    content: str,
    llm_client: LLMClient | None,
) -> str | None:
    if llm_client is None:
        return None
    try:
        response = await llm_client.chat(
            [
                ChatMessage(
                    role="user",
                    content=(
                        "Generate an independent summary for this Episode "
                        "Content. The summary must be 1-3 sentences, must "
                        "preserve the key actions and outcome, and must not "
                        "copy the opening sentence or return a content prefix. "
                        "Write the summary in Simplified Chinese. "
                        'Return only JSON in this shape: {"summary": "..."}.\n\n'
                        f"Content:\n{content}"
                    ),
                )
            ],
            temperature=0,
            max_tokens=256,
        )
    except Exception as exc:  # pragma: no cover - defensive around provider IO
        logger.warning(
            "episode_secondary_summary_failed",
            extra={"error": str(exc)},
        )
        return None
    parsed = _parse_summary_response(response.content)
    return _limit_episode_summary(parsed) if parsed else None


def _parse_summary_response(text: str) -> str | None:
    json_text = _extract_json_object(text)
    if json_text is not None:
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("summary"), str):
            return data["summary"]
    stripped = text.strip()
    return stripped or None


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _truncate_episode_summary(content: str) -> str:
    return _limit_episode_summary(content.strip()[:200])


def _fallback_episode_summary(content: str, subject: object = None) -> str:
    subject_text = _normalise_episode_subject(subject, content)
    summary = f"记忆摘要：{subject_text}"
    if _summary_is_valid(summary, content):
        return _limit_episode_summary(summary)
    return "记忆摘要暂不可用；请查看正文了解详情。"


def _limit_episode_summary(summary: str) -> str:
    text = " ".join(summary.strip().split())
    if not text:
        return ""

    matches = list(_SUMMARY_SENTENCE_RE.finditer(text))
    if len(matches) >= _EPISODE_SUMMARY_MAX_SENTENCES:
        text = text[: matches[_EPISODE_SUMMARY_MAX_SENTENCES - 1].end()].strip()

    if len(text) <= _EPISODE_SUMMARY_MAX_CHARS:
        return text

    clipped = text[:_EPISODE_SUMMARY_MAX_CHARS].rstrip()
    last_space = clipped.rfind(" ")
    if last_space >= int(_EPISODE_SUMMARY_MAX_CHARS * 0.7):
        clipped = clipped[:last_space].rstrip()
    return clipped


def _normalise_episode_subject(
    subject: object,
    content: str,
    *,
    fallback: str = "记忆片段",
) -> str:
    text = str(subject or "").strip()
    if not text:
        text = str(content or "").strip()
    if not text:
        text = fallback
    return _limit_episode_subject(text) or fallback


def _limit_episode_subject(subject: str) -> str:
    text = " ".join(subject.strip().split())
    if not text:
        return ""

    match = _SUMMARY_SENTENCE_RE.match(text)
    if match is not None:
        text = text[: match.end()].strip()

    if len(text) <= _EPISODE_SUBJECT_MAX_CHARS:
        return text

    clipped = text[:_EPISODE_SUBJECT_MAX_CHARS].rstrip()
    last_space = clipped.rfind(" ")
    if last_space >= int(_EPISODE_SUBJECT_MAX_CHARS * 0.7):
        clipped = clipped[:last_space].rstrip()
    return clipped


def _normalise_summary_text(value: str) -> str:
    return " ".join(value.split()).casefold()
