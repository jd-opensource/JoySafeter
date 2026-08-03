"""extract_atomic_facts strategy — derive AtomicFacts from an Episode.

Triggered per :class:`EpisodeExtracted` event (one per episode per
sender). Uses :meth:`AtomicFactExtractor.aextract_from_text` to extract
facts from the episode narrative. Each event carries a single
``owner_id``; all facts are written under that owner in one batched
:meth:`append_entries` call.
"""

from __future__ import annotations

import json

from everalgo.user_memory import AtomicFactExtractor

from app.everos.component.llm import get_project_llm_client
from app.everos.component.llm.protocol import ChatMessage, LLMClient
from app.everos.component.utils.datetime import from_timestamp, to_iso_format
from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import MemoryRoot
from app.everos.infra.ome.context import StrategyContext
from app.everos.infra.ome.decorator import offline_strategy
from app.everos.infra.ome.triggers import Immediate
from app.everos.infra.persistence.markdown import AtomicFactWriter
from app.everos.memory.chinese_validation import (
    is_valid_chinese_memory_text,
    normalise_memory_text,
)
from app.everos.memory.events import EpisodeExtracted
from app.everos.memory.language_policy import ensure_chinese_memory_llm
from app.everos.memory.models import AtomicFact

logger = get_logger(__name__)

_writer: AtomicFactWriter | None = None
_FACT_REWRITE_MAX_ATTEMPTS = 3


def _get_writer() -> AtomicFactWriter:
    """Return the lazily-initialised AtomicFactWriter singleton."""
    global _writer
    if _writer is None:
        _writer = AtomicFactWriter(root=MemoryRoot.default())
    return _writer


@offline_strategy(
    name="extract_atomic_facts",
    trigger=Immediate(on=[EpisodeExtracted]),
    emits=[],
    max_retries=2,
)
async def extract_atomic_facts(event: EpisodeExtracted, ctx: StrategyContext) -> None:
    """Extract atomic facts from an episode and persist as markdown entries."""
    # 1. Run LLM extractor on episode text.
    llm_client = ensure_chinese_memory_llm(await get_project_llm_client(event.project_id))
    extractor = AtomicFactExtractor(
        llm=llm_client
    )
    algo_facts = await extractor.aextract_from_text(
        event.episode_text, timestamp=event.episode_timestamp_ms
    )
    if not algo_facts:
        logger.info(
            "atomic_facts_extracted",
            memcell_id=event.memcell_id,
            session_id=event.session_id,
            count=0,
            owner_id=event.owner_id,
        )
        return

    # 2. Build domain AtomicFacts (single owner from event).
    facts: list[AtomicFact] = []
    skipped_non_chinese = 0
    for af in algo_facts:
        fact = AtomicFact.from_algo(
            af,
            owner_id=event.owner_id,
            session_id=event.session_id,
            parent_id=event.episode_entry_id,
            source_timestamp_ms=event.episode_timestamp_ms,
        )
        chinese_fact = await _ensure_chinese_fact_text(
            fact.fact,
            llm_client,
            source_episode=event.episode_text,
        )
        if chinese_fact is None:
            skipped_non_chinese += 1
            continue
        facts.append(fact.model_copy(update={"fact": chinese_fact}))

    if not facts:
        logger.info(
            "atomic_facts_extracted",
            memcell_id=event.memcell_id,
            session_id=event.session_id,
            count=0,
            skipped_non_chinese=skipped_non_chinese,
            owner_id=event.owner_id,
        )
        return

    # 3. Write all facts in one batched append.
    writer = _get_writer()
    items = [_atomic_fact_to_entry_body(f) for f in facts]
    await writer.append_entries(
        event.owner_id, items, app_id=event.app_id, project_id=event.project_id
    )

    logger.info(
        "atomic_facts_extracted",
        memcell_id=event.memcell_id,
        session_id=event.session_id,
        count=len(facts),
        skipped_non_chinese=skipped_non_chinese,
        owner_id=event.owner_id,
    )


async def _ensure_chinese_fact_text(
    fact: str,
    llm_client: LLMClient,
    *,
    source_episode: str,
) -> str | None:
    text = _normalise_fact_text(fact)
    if _fact_is_valid(text):
        return text
    coerced = _parse_fact_rewrite_response(text)
    coerced = _normalise_fact_text(coerced or "")
    if _fact_is_valid(coerced):
        return coerced

    latest = coerced or text
    for attempt in range(1, _FACT_REWRITE_MAX_ATTEMPTS + 1):
        try:
            response = await llm_client.chat(
                [
                    ChatMessage(
                        role="user",
                        content=_fact_rewrite_prompt(
                            latest,
                            source_episode=source_episode,
                            attempt=attempt,
                        ),
                    )
                ],
                temperature=0,
                max_tokens=256,
            )
        except Exception as exc:  # pragma: no cover - provider IO
            logger.warning(
                "atomic_fact_chinese_rewrite_failed",
                attempt=attempt,
                error=str(exc),
            )
            continue
        rewritten = _parse_fact_rewrite_response(str(response.content or ""))
        rewritten = _normalise_fact_text(rewritten or "")
        if _fact_is_valid(rewritten):
            return rewritten
        latest = rewritten or latest

    logger.warning(
        "atomic_fact_discarded_non_chinese",
        fact=text,
    )
    return None


def _fact_is_chinese(fact: object) -> bool:
    return is_valid_chinese_memory_text(fact)


def _fact_is_valid(fact: object) -> bool:
    return is_valid_chinese_memory_text(fact)


def _normalise_fact_text(fact: str) -> str:
    return normalise_memory_text(fact)


def _fact_rewrite_prompt(fact: str, *, source_episode: str, attempt: int) -> str:
    return (
        "请把下面这条 EverOS AtomicFact 改写成简体中文。\n"
        "要求：\n"
        "- 只保留原事实，不新增信息。\n"
        "- 用一句完整、具体、可独立理解的中文事实句表达。\n"
        "- 保留必要的人名、ID、法律条文、数字、文件路径和精确引用。\n"
        "- 仅返回 JSON：{\"fact\":\"...\"}。\n\n"
        f"尝试次数: {attempt}\n\n"
        f"原 Fact:\n{fact}\n\n"
        f"来源 Episode:\n{source_episode}"
    )


def _parse_fact_rewrite_response(text: str) -> str | None:
    json_text = _extract_json_object(text)
    if json_text is not None:
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("fact"), str):
            return data["fact"]
        coerced = _coerce_fact_from_json(data)
        if coerced:
            return coerced
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return stripped or None


def _coerce_fact_from_json(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    candidates: list[object] = []
    for key in ("fact", "content", "evidence", "foresight"):
        candidates.append(data.get(key))
    for block_key in ("atomic_facts", "foresights"):
        block = data.get(block_key)
        if isinstance(block, dict):
            candidates.extend(block.values())
        elif isinstance(block, list):
            candidates.extend(block)
    while candidates:
        candidate = candidates.pop(0)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, dict):
            for key in ("fact", "content", "foresight", "evidence"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            candidates.extend(candidate.values())
        elif isinstance(candidate, list):
            candidates.extend(candidate)
    return None


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _atomic_fact_to_entry_body(
    fact: AtomicFact,
) -> tuple[dict[str, object], dict[str, str]]:
    """Split a domain AtomicFact into ``(inline, sections)`` for md rendering.

    Mirrors ``_episode_to_entry_body`` in the user_memory pipeline. Lives in
    the memory layer (strategy module) rather than the writer (infra)
    because it depends on :class:`everos.memory.AtomicFact` — infra is
    not allowed to import memory per the layered architecture contract.
    """
    inline: dict[str, object] = {
        "owner_id": fact.owner_id,
        "timestamp": to_iso_format(from_timestamp(fact.timestamp)),
        "parent_type": "episode",
        "parent_id": fact.parent_id,
    }
    if fact.session_id is not None:
        inline["session_id"] = fact.session_id
    sections = {"Fact": fact.fact}
    return inline, sections
