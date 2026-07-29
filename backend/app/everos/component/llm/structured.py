"""Structured-output resilience for EverOS LLM calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .protocol import ChatMessage, ChatResponse, LLMClient


class JSONRepairingLLMClient:
    """LLM wrapper that repairs malformed JSON responses.

    Everalgo memory extractors parse ``ChatResponse.content`` themselves. When
    a provider returns almost-JSON with syntax defects, this wrapper asks the
    same configured LLM to repair only the JSON syntax before everalgo sees it.
    """

    def __init__(
        self,
        delegate: LLMClient,
        *,
        max_repair_attempts: int = 5,
        repair_max_tokens: int = 8192,
    ) -> None:
        self._delegate = delegate
        self._max_repair_attempts = max(0, max_repair_attempts)
        self._repair_max_tokens = max(1, repair_max_tokens)

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Any | None = None,
        schema_name: str | None = None,
        **extra: Any,
    ) -> ChatResponse:
        response = await self._delegate.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=_provider_response_format(response_format),
            **extra,
        )
        if response.parsed is not None or not _should_validate_json(
            messages,
            response.content,
            response_format=response_format,
        ):
            return response
        schema = _resolve_schema(messages, schema_name=schema_name)
        structured = _validate_structured_response(
            response.content,
            schema=schema,
            response_format=response_format,
        )
        validation = structured.validation
        if validation.json_text is not None:
            if structured.parsed is None:
                return response
            return _with_structured_content(
                response,
                content=validation.json_text,
                parsed=structured.parsed,
            )

        latest_response = response
        for attempt in range(1, self._max_repair_attempts + 1):
            repair = await self._delegate.chat(
                [
                    ChatMessage(
                        role="user",
                        content=_repair_prompt(
                            latest_response.content,
                            validation.error or "Invalid JSON object.",
                            validation.category,
                            attempt=attempt,
                            max_attempts=self._max_repair_attempts,
                            schema=schema,
                        ),
                    )
                ],
                model=model,
                temperature=0,
                max_tokens=max(max_tokens or 0, self._repair_max_tokens),
            )
            structured = _validate_structured_response(
                repair.content,
                schema=schema,
                response_format=response_format,
            )
            validation = structured.validation
            if validation.json_text is not None:
                return ChatResponse(
                    content=validation.json_text,
                    model=repair.model,
                    usage=repair.usage,
                    finish_reason=repair.finish_reason,
                    parsed=repair.parsed if repair.parsed is not None else structured.parsed,
                    raw=repair.raw,
                )
            latest_response = repair

        return ChatResponse(
            content=response.content,
            model=response.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
            parsed=response.parsed,
            raw=response.raw,
        )


class SchemaBoundLLMClient:
    """LLM wrapper that supplies a default structured-output schema name."""

    def __init__(self, delegate: LLMClient, schema_name: str) -> None:
        self._delegate = delegate
        self._schema_name = schema_name

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Any | None = None,
        schema_name: str | None = None,
        **extra: Any,
    ) -> ChatResponse:
        return await self._delegate.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            schema_name=schema_name or self._schema_name,
            **extra,
        )


def ensure_json_repairing_llm(client: LLMClient) -> LLMClient:
    """Wrap a client once with JSON repair behavior."""
    if isinstance(client, JSONRepairingLLMClient):
        return client
    return JSONRepairingLLMClient(client)


def bind_json_schema(client: LLMClient, schema_name: str) -> LLMClient:
    """Bind an explicit schema name for extractor calls that cannot pass one."""
    if isinstance(client, SchemaBoundLLMClient) and client._schema_name == schema_name:
        return client
    return SchemaBoundLLMClient(ensure_json_repairing_llm(client), schema_name)


def _should_validate_json(
    messages: list[ChatMessage],
    text: str,
    *,
    response_format: Any | None,
) -> bool:
    if response_format is not None:
        return True
    if _looks_like_json_object(text):
        return True
    return any(_message_requests_json(message) for message in messages)


def _looks_like_json_object(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("{"):
        return True
    return "```json" in stripped.lower()


def _message_requests_json(message: ChatMessage) -> bool:
    content = message.content
    if not isinstance(content, str):
        return False
    lowered = content.lower()
    return "json" in lowered or "schema" in lowered


@dataclass(frozen=True)
class _JSONValidation:
    json_text: str | None
    error: str | None
    category: str


@dataclass(frozen=True)
class _JSONSchema:
    name: str
    instructions: str
    validate: Callable[[dict[str, Any]], str | None]


@dataclass(frozen=True)
class _StructuredValidation:
    validation: _JSONValidation
    parsed: Any | None = None


def _valid_json_object(text: str) -> str | None:
    return _validate_json_object(text).json_text


def _provider_response_format(response_format: Any | None) -> Any | None:
    if _is_pydantic_model_class(response_format):
        return None
    return response_format


def _is_pydantic_model_class(value: Any | None) -> bool:
    return isinstance(value, type) and callable(getattr(value, "model_validate_json", None))


def _validate_structured_response(
    text: str,
    *,
    schema: _JSONSchema | None = None,
    response_format: Any | None = None,
) -> _StructuredValidation:
    validation = _validate_json_object(text, schema=schema)
    if validation.json_text is None:
        return _StructuredValidation(validation)
    if not _is_pydantic_model_class(response_format):
        return _StructuredValidation(validation)
    try:
        parsed = response_format.model_validate_json(validation.json_text)
    except Exception as exc:
        return _StructuredValidation(
            _JSONValidation(
                None,
                f"JSON object does not match response_format: {exc}",
                "response_format_invalid",
            )
        )
    return _StructuredValidation(validation, parsed)


def _with_structured_content(
    response: ChatResponse,
    *,
    content: str,
    parsed: Any,
) -> ChatResponse:
    return ChatResponse(
        content=content,
        model=response.model,
        usage=response.usage,
        finish_reason=response.finish_reason,
        parsed=parsed,
        raw=response.raw,
    )


def _validate_json_object(
    text: str,
    *,
    schema: _JSONSchema | None = None,
) -> _JSONValidation:
    candidate = _extract_json_object(text)
    if candidate is None:
        return _JSONValidation(None, "No complete JSON object found.", "json_incomplete")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return _JSONValidation(
            None,
            (f"JSON parse error: {exc.msg} at line {exc.lineno}, column {exc.colno}, character {exc.pos}."),
            "json_parse_error",
        )
    if not isinstance(parsed, dict):
        return _JSONValidation(
            None,
            "Parsed JSON value is not an object.",
            "json_not_object",
        )
    if schema is not None:
        schema_error = schema.validate(parsed)
        if schema_error is not None:
            return _JSONValidation(
                None,
                f"JSON object does not match schema {schema.name}: {schema_error}",
                _schema_error_category(schema_error),
            )
    return _JSONValidation(candidate, None, "valid")


def _repair_prompt(
    malformed_content: str,
    validation_error: str,
    validation_category: str,
    *,
    attempt: int,
    max_attempts: int,
    schema: _JSONSchema | None = None,
) -> str:
    schema_text = ""
    if schema is not None:
        schema_text = (
            "\n\nRequired schema:\n"
            f"Name: {schema.name}\n"
            f"{schema.instructions}\n"
            "If a required field is missing, derive it only from the original "
            "text or prompt context; otherwise use an empty value with the "
            "correct JSON type."
        )
    return (
        "Fix only the JSON syntax in the following text. "
        "Do not translate or change any facts. "
        "Return only one valid JSON object.\n\n"
        f"Repair attempt: {attempt} of {max_attempts}\n"
        f"Validation category: {validation_category}\n"
        f"Previous validation error: {validation_error}"
        f"{schema_text}\n\n"
        "Malformed JSON text:\n"
        f"{malformed_content}"
    )


def _schema_error_category(schema_error: str) -> str:
    if "missing required field" in schema_error:
        return "schema_missing_required_field"
    if "must be" in schema_error:
        return "schema_type_error"
    return "schema_invalid"


def _resolve_schema(
    messages: list[ChatMessage],
    *,
    schema_name: str | None,
) -> _JSONSchema | None:
    if schema_name:
        return _SCHEMAS.get(schema_name)
    prompt = "\n".join(message.content for message in messages if isinstance(message.content, str)).lower()
    if not prompt:
        return None
    if "compressed_messages" in prompt:
        return _SCHEMAS["agent_tool_precompress"]
    if "has_exploration" in prompt or "has_user_correction" in prompt:
        return _SCHEMAS["agent_case_filter"]
    if "task_intent" in prompt and "approach" in prompt:
        return _SCHEMAS["agent_case_compress"]
    if "explicit_info" in prompt and "implicit_traits" in prompt:
        return _SCHEMAS["profile_snapshot"]
    if "foresights" in prompt:
        return _SCHEMAS["foresight_extract"]
    if "atomic_fact" in prompt or "atomic_facts" in prompt or "event_log" in prompt:
        return _SCHEMAS["atomic_fact_extract"]
    if "operations" in prompt:
        return _SCHEMAS["operations_list"]
    if "title" in prompt and "content" in prompt:
        return _SCHEMAS["episode_extract"]
    return None


def _require_fields(data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    missing = [field for field in fields if field not in data]
    if missing:
        return f"missing required field(s): {', '.join(missing)}"
    return None


def _require_list(data: dict[str, Any], field: str) -> str | None:
    if field not in data:
        return f"missing required field: {field}"
    if not isinstance(data[field], list):
        return f"{field} must be a list"
    return None


def _require_bool(data: dict[str, Any], field: str) -> str | None:
    if field not in data:
        return f"missing required field: {field}"
    if not isinstance(data[field], bool):
        return f"{field} must be a boolean"
    return None


def _require_non_empty_str(data: dict[str, Any], field: str) -> str | None:
    if field not in data:
        return f"missing required field: {field}"
    if not isinstance(data[field], str):
        return f"{field} must be a string"
    if not data[field].strip():
        return f"{field} must be a non-empty string"
    return None


def _require_int(data: dict[str, Any], field: str) -> str | None:
    if field not in data:
        return f"missing required field: {field}"
    if not isinstance(data[field], int) or isinstance(data[field], bool):
        return f"{field} must be an integer"
    return None


def _require_number_in_range(
    data: dict[str, Any],
    field: str,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> str | None:
    if field not in data:
        return f"missing required field: {field}"
    if not isinstance(data[field], int | float) or isinstance(data[field], bool):
        return f"{field} must be a number"
    value = float(data[field])
    if value < minimum or value > maximum:
        return f"{field} must be between {minimum:g} and {maximum:g}"
    return None


def _require_str_list(data: dict[str, Any], field: str) -> str | None:
    err = _require_list(data, field)
    if err is not None:
        return err
    for index, item in enumerate(data[field]):
        if not isinstance(item, str):
            return f"{field}[{index}] must be a string"
    return None


def _validate_profile_snapshot(data: dict[str, Any]) -> str | None:
    return _require_list(data, "explicit_info") or _require_list(data, "implicit_traits")


def _validate_operations_list(data: dict[str, Any]) -> str | None:
    return _require_list(data, "operations")


def _validate_agent_case_compress(data: dict[str, Any]) -> str | None:
    err = _require_fields(
        data,
        ("task_intent", "approach", "quality_score", "key_insight"),
    )
    if err is not None:
        return err
    err = _require_non_empty_str(data, "task_intent") or _require_non_empty_str(data, "approach")
    if err is not None:
        return err
    err = _require_number_in_range(data, "quality_score")
    if err is not None:
        return err
    if not isinstance(data["key_insight"], str):
        return "key_insight must be a string"
    return None


def _validate_agent_case_filter(data: dict[str, Any]) -> str | None:
    return _require_bool(data, "has_exploration") or _require_bool(data, "has_user_correction")


def _validate_tool_precompress(data: dict[str, Any]) -> str | None:
    return _require_list(data, "compressed_messages")


def _validate_episode(data: dict[str, Any]) -> str | None:
    err = _require_fields(data, ("title", "summary", "content"))
    if err is not None:
        return err
    err = (
        _require_non_empty_str(data, "title")
        or _require_non_empty_str(data, "summary")
        or _require_non_empty_str(data, "content")
    )
    if err is not None:
        return err
    summary = data["summary"].strip()
    content = data["content"].strip()
    if _normalise_episode_text(summary) == _normalise_episode_text(content):
        return "summary must be an independent summary of content, not a copy"
    if _is_content_prefix(summary, content):
        return "summary must be an independent summary of content, not a content prefix"
    return None


def _normalise_episode_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _is_content_prefix(summary: str, content: str) -> bool:
    summary_norm = _normalise_episode_text(summary)
    content_norm = _normalise_episode_text(content)
    return len(summary_norm) >= 12 and content_norm.startswith(summary_norm)


def _validate_atomic_fact(data: dict[str, Any]) -> str | None:
    if "event_log" in data:
        block = data["event_log"]
    elif "atomic_facts" in data:
        block = data["atomic_facts"]
    else:
        return "missing required field: event_log or atomic_facts"
    if not isinstance(block, dict):
        return "event_log/atomic_facts must be an object"
    if "atomic_fact" not in block:
        return "inner atomic_fact field is required"
    if not isinstance(block["atomic_fact"], list):
        return "inner atomic_fact must be a list"
    for index, item in enumerate(block["atomic_fact"]):
        if not isinstance(item, str) or not item.strip():
            return f"atomic_fact[{index}] must be a non-empty string"
    return None


def _validate_foresight(data: dict[str, Any]) -> str | None:
    err = _require_list(data, "foresights")
    if err is not None:
        return err
    for index, item in enumerate(data["foresights"]):
        if not isinstance(item, dict):
            return f"foresights[{index}] must be an object"
        for field in ("owner_id", "foresight", "evidence"):
            err = _require_non_empty_str(item, field)
            if err is not None:
                return f"foresights[{index}].{err}"
        if "duration_days" in item and item["duration_days"] is not None:
            err = _require_int(item, "duration_days")
            if err is not None:
                return f"foresights[{index}].{err}"
        for field in ("start_time", "end_time"):
            if field in item and item[field] is not None and not isinstance(item[field], str):
                return f"foresights[{index}].{field} must be a string"
    return None


def _validate_agent_skill_extract(data: dict[str, Any]) -> str | None:
    err = _require_list(data, "operations")
    if err is not None:
        return err
    for index, operation in enumerate(data["operations"]):
        if not isinstance(operation, dict):
            return f"operations[{index}] must be an object"
        op_name = operation.get("operation") or operation.get("op") or operation.get("type")
        if not isinstance(op_name, str) or not op_name.strip():
            return f"operations[{index}].operation must be a non-empty string"
        if op_name in {"delete", "retire", "remove"}:
            continue
        skill = operation.get("skill")
        if not isinstance(skill, dict):
            return f"operations[{index}].skill must be an object"
        for field in ("name", "description", "content"):
            err = _require_non_empty_str(skill, field)
            if err is not None:
                return f"operations[{index}].skill.{err}"
        for field in ("confidence", "maturity_score"):
            err = _require_number_in_range(skill, field)
            if err is not None:
                return f"operations[{index}].skill.{err}"
        err = _require_str_list(skill, "source_case_ids")
        if err is not None:
            return f"operations[{index}].skill.{err}"
    return None


_SCHEMAS: dict[str, _JSONSchema] = {
    "episode_extract": _JSONSchema(
        name="episode_extract",
        instructions=(
            "Object with required non-empty string fields: title, summary, "
            "content. The summary must be an independent summary of content, "
            "not a copy, first sentence, or content prefix."
        ),
        validate=_validate_episode,
    ),
    "atomic_fact_extract": _JSONSchema(
        name="atomic_fact_extract",
        instructions=(
            "Object with either event_log or atomic_facts. The selected value "
            "must be an object containing atomic_fact as a list. Each item must "
            "be a non-empty string. EverOS supplies timestamp from the source "
            "context."
        ),
        validate=_validate_atomic_fact,
    ),
    "foresight_extract": _JSONSchema(
        name="foresight_extract",
        instructions=(
            "Object with required list field foresights. Each item must contain "
            "non-empty string owner_id, foresight, and evidence. Optional "
            "start_time/end_time are strings; duration_days is integer. EverOS "
            "supplies timestamp from the source context."
        ),
        validate=_validate_foresight,
    ),
    "profile_snapshot": _JSONSchema(
        name="profile_snapshot",
        instructions=("Object with required list fields: explicit_info, implicit_traits."),
        validate=_validate_profile_snapshot,
    ),
    "profile_update": _JSONSchema(
        name="profile_update",
        instructions="Object with required list field: operations.",
        validate=_validate_operations_list,
    ),
    "operations_list": _JSONSchema(
        name="operations_list",
        instructions="Object with required list field: operations.",
        validate=_validate_operations_list,
    ),
    "agent_case_filter": _JSONSchema(
        name="agent_case_filter",
        instructions=("Object with required boolean fields: has_exploration, has_user_correction."),
        validate=_validate_agent_case_filter,
    ),
    "agent_case_compress": _JSONSchema(
        name="agent_case_compress",
        instructions=(
            "Object with required fields: non-empty task_intent string, "
            "non-empty approach string, quality_score number in [0, 1], "
            "key_insight string."
        ),
        validate=_validate_agent_case_compress,
    ),
    "agent_tool_precompress": _JSONSchema(
        name="agent_tool_precompress",
        instructions="Object with required list field: compressed_messages.",
        validate=_validate_tool_precompress,
    ),
    "agent_skill_extract": _JSONSchema(
        name="agent_skill_extract",
        instructions=(
            "Object with required list field operations. Each operation must be "
            "an object with a non-empty operation string. Upsert/add/update "
            "operations must include skill with non-empty string name, "
            "description, content; confidence and maturity_score numbers in "
            "[0, 1]; source_case_ids as a list of strings."
        ),
        validate=_validate_agent_skill_extract,
    ),
}


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
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
