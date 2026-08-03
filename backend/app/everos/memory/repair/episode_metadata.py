"""Repair stale Episode metadata in EverOS markdown files."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import anyio

from app.everos.component.llm import get_project_llm_client
from app.everos.component.llm.protocol import ChatMessage
from app.everos.core.observability.logging import get_logger
from app.everos.core.persistence import (
    MarkdownReader,
    MarkdownWriter,
    MemoryRoot,
    dump_frontmatter,
    render_structured_entry,
)
from app.everos.core.persistence.lancedb.repository import _q
from app.everos.infra.persistence.lancedb import episode_repo
from app.everos.memory.extract.pipeline.user_memory import (
    _fallback_episode_summary,
    _limit_episode_subject,
    _limit_episode_summary,
    _normalise_episode_subject,
    _summarize_episode_content,
    _summary_is_valid,
)
from app.everos.memory.language_policy import ensure_chinese_memory_llm

logger = get_logger(__name__)

_AGGREGATED_SUBJECT_PREFIX = "[聚合记忆]"
_LEGACY_AGGREGATED_SUBJECT_PREFIXES = ("[Aggregated Memory]",)


async def repair_episode_metadata(
    *,
    app_id: str,
    project_id: str,
    owner_id: str | None = None,
    entry_ids: Sequence[str] | None = None,
    limit: int = 1000,
    rewrite_content_chinese: bool = False,
) -> dict[str, int]:
    """Repair stale Episode Subject/Summary sections via markdown source of truth."""
    rows = await _load_episode_rows(
        app_id=app_id,
        project_id=project_id,
        owner_id=owner_id,
        entry_ids=entry_ids,
        limit=limit,
    )
    if not rows:
        return {"scanned": 0, "changed_entries": 0, "changed_files": 0}

    repairs_by_path: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    llm_by_project: dict[str, Any] = {}
    failed_entries = 0
    for row in rows:
        try:
            repairs = await _repairs_for_row(
                row,
                llm_by_project,
                rewrite_content_chinese=rewrite_content_chinese,
            )
        except Exception as exc:
            failed_entries += 1
            logger.warning(
                "episode_metadata_repair_entry_failed",
                entry_id=getattr(row, "entry_id", None),
                md_path=getattr(row, "md_path", None),
                error=str(exc),
            )
            continue
        if repairs:
            repairs_by_path[row.md_path][row.entry_id] = repairs

    if not repairs_by_path:
        return {
            "scanned": len(rows),
            "changed_entries": 0,
            "changed_files": 0,
            "failed_entries": failed_entries,
        }

    root = MemoryRoot.default()
    writer = MarkdownWriter(root)
    changed_files = 0
    changed_entries = 0
    for md_path, repairs in repairs_by_path.items():
        path = root.root / md_path
        async with writer.lock_for(path):
            raw = await anyio.Path(path).read_text(encoding="utf-8")
            repaired, changed = repair_episode_markdown_text(raw, repairs=repairs)
            if not changed:
                continue
            await writer.write(Path(path), repaired)
            changed_files += 1
            changed_entries += len(repairs)

    logger.info(
        "episode_metadata_repair_completed",
        app_id=app_id,
        project_id=project_id,
        owner_id=owner_id,
        scanned=len(rows),
        changed_entries=changed_entries,
        changed_files=changed_files,
        failed_entries=failed_entries,
    )
    return {
        "scanned": len(rows),
        "changed_entries": changed_entries,
        "changed_files": changed_files,
        "failed_entries": failed_entries,
    }


def repair_episode_markdown_text(
    text: str,
    *,
    repairs: Mapping[str, Mapping[str, str]],
) -> tuple[str, bool]:
    """Return markdown text with selected entry sections repaired."""
    parsed = MarkdownReader.parse(text)
    replacements: list[tuple[int, int, str]] = []
    for entry in parsed.entries:
        entry_repairs = repairs.get(entry.id)
        if not entry_repairs:
            continue
        structured = entry.as_structured()
        sections = dict(structured.sections)
        changed = False
        for section, value in entry_repairs.items():
            if sections.get(section) != value:
                sections[section] = value
                changed = True
        if not changed:
            continue
        entry_body = render_structured_entry(
            header=structured.header or entry.id,
            inline=structured.inline,
            sections=sections,
        )
        replacement = (
            f"<!-- entry:{entry.id} -->\n"
            f"{entry_body}\n"
            f"<!-- /entry:{entry.id} -->"
        )
        replacements.append((entry.start, entry.end, replacement))

    if not replacements:
        return text, False

    body = parsed.body
    for start, end, replacement in sorted(replacements, reverse=True):
        body = body[:start] + replacement + body[end:]
    if body and not body.endswith("\n"):
        body += "\n"
    return dump_frontmatter(parsed.frontmatter) + body, True


async def _load_episode_rows(
    *,
    app_id: str,
    project_id: str,
    owner_id: str | None,
    entry_ids: Sequence[str] | None,
    limit: int,
) -> list[Any]:
    clauses = [
        f"app_id = '{_q(app_id)}'",
        f"project_id = '{_q(project_id)}'",
        "deprecated_by IS NULL",
    ]
    if owner_id:
        clauses.append(f"owner_id = '{_q(owner_id)}'")
    if entry_ids:
        quoted = ", ".join(f"'{_q(entry_id)}'" for entry_id in entry_ids)
        clauses.append(f"entry_id IN ({quoted})")
    return await episode_repo.find_where(" AND ".join(clauses), limit=limit)


async def _repairs_for_row(
    row: Any,
    llm_by_project: dict[str, Any],
    *,
    rewrite_content_chinese: bool,
) -> dict[str, str]:
    content = str(getattr(row, "episode", "") or "")
    current_subject = str(getattr(row, "subject", "") or "")
    target_subject = _target_subject(row, content)

    repairs: dict[str, str] = {}
    if rewrite_content_chinese:
        llm_client = await _llm_for_project(str(row.project_id), llm_by_project)
        rewritten = await _rewrite_episode_in_chinese(
            row,
            content=content,
            target_subject=target_subject,
            llm_client=llm_client,
        )
        if rewritten:
            return rewritten

    if current_subject.strip() != target_subject:
        repairs["Subject"] = target_subject

    current_summary = getattr(row, "summary", None)
    if not _summary_is_valid(current_summary, content):
        llm_client = await _llm_for_project(str(row.project_id), llm_by_project)
        generated = await _summarize_episode_content(content, llm_client)
        repairs["Summary"] = (
            generated
            if _summary_is_valid(generated, content)
            else _fallback_episode_summary(content, target_subject)
        )
    return repairs


async def _rewrite_episode_in_chinese(
    row: Any,
    *,
    content: str,
    target_subject: str,
    llm_client: Any,
) -> dict[str, str] | None:
    response = await llm_client.chat(
        [
            ChatMessage(
                role="user",
                content=_episode_rewrite_prompt(
                    row,
                    content=content,
                    target_subject=target_subject,
                ),
            )
        ],
        temperature=0,
        max_tokens=2048,
    )
    parsed = _parse_episode_rewrite_response(str(response.content or ""))
    if not parsed:
        return None

    rewritten_content = str(parsed.get("content") or "").strip()
    if not rewritten_content:
        return None

    subject = _normalise_episode_subject(
        parsed.get("subject") or target_subject,
        rewritten_content,
    )
    if getattr(row, "parent_type", None) == "cluster":
        subject = _target_aggregated_subject(subject, rewritten_content)

    raw_summary = str(parsed.get("summary") or "").strip()
    summary = (
        _limit_episode_summary(raw_summary)
        if _summary_is_valid(raw_summary, rewritten_content)
        else _fallback_episode_summary(rewritten_content, subject)
    )

    return {
        "Subject": subject,
        "Summary": summary,
        "Content": rewritten_content,
    }


def _episode_rewrite_prompt(
    row: Any,
    *,
    content: str,
    target_subject: str,
) -> str:
    parent_type = str(getattr(row, "parent_type", "") or "")
    entry_id = str(getattr(row, "entry_id", "") or "")
    current_subject = str(getattr(row, "subject", "") or "")
    current_summary = str(getattr(row, "summary", "") or "")
    aggregate_rule = (
        f'- 这是聚合记忆，subject 必须以 "{_AGGREGATED_SUBJECT_PREFIX}" 开头。\n'
        if parent_type == "cluster"
        else ""
    )
    return (
        "请按照当前 EverOS 记忆规则，重写下面这条旧 Episode 记忆。\n"
        "要求：\n"
        "- 所有生成文本必须使用简体中文。\n"
        "- 保留原有事实、人物、日期、ID、法律条文、数量、结论和时间顺序，不要新增事实。\n"
        "- subject 最多一句话，最多 140 个字符。\n"
        "- summary 为独立摘要，1-3 句话，最多 360 个字符，不能只是 content 的开头截断。\n"
        "- content 为完整但精炼的第三人称叙事记忆。\n"
        f"{aggregate_rule}"
        '仅返回 JSON：{"subject":"...","summary":"...","content":"..."}。\n\n'
        f"entry_id: {entry_id}\n"
        f"parent_type: {parent_type}\n"
        f"目标 subject 参考: {target_subject}\n\n"
        f"当前 Subject:\n{current_subject}\n\n"
        f"当前 Summary:\n{current_summary}\n\n"
        f"当前 Content:\n{content}"
    )


def _parse_episode_rewrite_response(text: str) -> dict[str, Any] | None:
    candidate = _extract_json_object(text)
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        data = _parse_loose_episode_rewrite_object(candidate)
    if not isinstance(data, dict):
        return None
    return data


def _parse_loose_episode_rewrite_object(text: str) -> dict[str, str] | None:
    """Parse the flat repair JSON when the LLM forgets to escape inner quotes."""
    keys = ("subject", "summary", "content")
    matches: list[tuple[str, int, int]] = []
    for key in keys:
        marker = f'"{key}":"'
        index = text.find(marker)
        if index < 0:
            marker = f'"{key}": "'
            index = text.find(marker)
        if index < 0:
            return None
        matches.append((key, index, index + len(marker)))
    matches.sort(key=lambda item: item[1])
    if [key for key, _, _ in matches] != list(keys):
        return None

    parsed: dict[str, str] = {}
    for offset, (key, _index, value_start) in enumerate(matches):
        if offset + 1 < len(matches):
            value_end = matches[offset + 1][1]
            raw_value = text[value_start:value_end].rstrip()
            if raw_value.endswith(","):
                raw_value = raw_value[:-1].rstrip()
            if raw_value.endswith('"'):
                raw_value = raw_value[:-1]
        else:
            close_brace = text.rfind("}")
            if close_brace < value_start:
                return None
            value_end = text.rfind('"', value_start, close_brace)
            if value_end < value_start:
                return None
            raw_value = text[value_start:value_end]
        value = _decode_loose_json_string(raw_value.strip())
        if not value:
            return None
        parsed[key] = value
    return parsed


def _decode_loose_json_string(value: str) -> str:
    return (
        value.replace(r"\\", "\\")
        .replace(r"\"", '"')
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
    )


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


def _target_subject(row: Any, content: str) -> str:
    current = str(getattr(row, "subject", "") or "")
    if getattr(row, "parent_type", None) == "cluster":
        return _target_aggregated_subject(current, content)
    return _normalise_episode_subject(current, content)


def _target_aggregated_subject(subject: str, content: str) -> str:
    base = subject
    for prefix in (_AGGREGATED_SUBJECT_PREFIX, *_LEGACY_AGGREGATED_SUBJECT_PREFIXES):
        if base.lower().startswith(prefix.lower()):
            base = base[len(prefix):].strip()
            break
    base = base or content
    return _limit_episode_subject(f"{_AGGREGATED_SUBJECT_PREFIX} {base}")


async def _llm_for_project(project_id: str, cache: dict[str, Any]) -> Any:
    if project_id not in cache:
        client = await get_project_llm_client(
            project_id,
            default_timeout_seconds=180.0,
        )
        if client.__class__.__name__ == "JSONRepairingLLMClient":
            client = getattr(client, "_delegate", client)
        cache[project_id] = ensure_chinese_memory_llm(
            client
        )
    return cache[project_id]


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", default="joysafeter")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--owner-id")
    parser.add_argument("--entry-id", action="append", dest="entry_ids")
    parser.add_argument(
        "--rewrite-content-chinese",
        action="store_true",
        help="Use the configured memory LLM to rewrite Subject/Summary/Content in Simplified Chinese.",
    )
    args = parser.parse_args()
    result = await repair_episode_metadata(
        app_id=args.app_id,
        project_id=args.project_id,
        owner_id=args.owner_id,
        entry_ids=args.entry_ids,
        rewrite_content_chinese=args.rewrite_content_chinese,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
